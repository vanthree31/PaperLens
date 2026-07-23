"""AI 辅助端口 - 支持分层模型配置（轻量模型 + 检索模型 + 分析模型）

查询分级：
  simple  - DOI/PMID/单关键词 → 跳过 AI，规则引擎直接构建参数
  moderate - 基本关键词组合 → 轻量模型（Ollama 优先）
  complex - 完整自然语言 → 主模型

分析分级：
  summary → 轻量模型
  detail/compare/novelty → 主模型
"""

import json
import re
import time
import hashlib
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 轻量级模型工厂
# ---------------------------------------------------------------------------


def create_lightweight_assistant(config: dict):
    """创建轻量级 AI 助手实例（用于简单分析和 moderate 查询）

    优先级：ai_lightweight 配置 > ai_search 配置
    如果都未启用，返回 None
    """
    # 优先使用独立的轻量级配置
    lw_cfg = config.get("ai_lightweight", {})
    if lw_cfg.get("enabled"):
        return AIAssistant(lw_cfg)

    # 回退：如果 ai_search 已启用，复用它作为轻量级模型
    search_cfg = config.get("ai_search", {})
    if search_cfg.get("enabled"):
        return AIAssistant(search_cfg)

    return None


# ---------------------------------------------------------------------------
# 查询分析缓存（TTL 1小时，最大200条）
# ---------------------------------------------------------------------------


class _TTLCache:
    """带 TTL 的简易内存缓存"""

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 200):
        self._store = {}  # key -> (value, expire_time)
        self._ttl = ttl_seconds
        self._max_size = max_size

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if time.time() > expire_at:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value):
        now = time.time()
        # 淘汰过期条目
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        # 超出容量时淘汰最早的一半
        if len(self._store) >= self._max_size:
            sorted_keys = sorted(self._store, key=lambda k: self._store[k][1])
            for k in sorted_keys[: len(sorted_keys) // 2 + 1]:
                del self._store[k]
        self._store[key] = (value, now + self._ttl)

    def stats(self) -> dict:
        now = time.time()
        active = sum(1 for _, (_, exp) in self._store.items() if now <= exp)
        return {"size": active, "maxsize": self._max_size}


# 全局查询分析缓存
_query_analysis_cache = _TTLCache(ttl_seconds=3600, max_size=200)


# ---------------------------------------------------------------------------
# 查询复杂度分级
# ---------------------------------------------------------------------------

# DOI 模式
_DOI_RE = re.compile(r'10\.\d{4,9}/[^\s,;)\]}"、。]+')
# PMID 模式（纯数字或 PMID:前缀）
_PMID_RE = re.compile(r"(?:PMID[:\s]*)?(\d{6,9})\b")
# 简单关键词模式：2-4个英文单词，无布尔运算符，无时间约束
_SIMPLE_KW_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9\s\-]{0,80}$"  # 只含英文、数字、空格、连字符
)
# 复杂度指示词
_COMPLEXITY_MARKERS = [
    # 布尔运算
    r"\b(?:AND|OR|NOT)\b",
    r"且",
    r"或",
    r"非",
    # 比较/综述
    r"对比",
    r"比较",
    r"区别",
    r"差异",
    r"综述",
    r"全面",
    r"compare",
    r"versus",
    r"difference",
    r"review",
    # 时间约束（支持阿拉伯数字和中文数字）
    r"近[一二三四五六七八九十\d]+年",
    r"最近",
    r"since\s+\d{4}",
    r"last\s+\d+\s+year",
    # 作者+主题复合查询
    r"作者",
    r"发表",
    r"author",
    # 多条件
    r"以及",
    r"同时",
    r"并且",
    r"中的",
    r"关于",
]


def _classify_query_complexity(user_input: str) -> str:
    """将查询分为三级复杂度

    Returns:
        "simple"   - DOI/PMID 精确查找、1-2个关键词 → 跳过 AI
        "moderate" - 基本关键词组合、含年份范围 → 轻量模型
        "complex"  - 自然语言描述、多条件、比较分析 → 主模型
    """
    q = user_input.strip()

    # simple: DOI 查找
    if _DOI_RE.search(q):
        return "simple"

    # simple: PMID 查找（纯数字或 PMID:前缀）
    pmid_match = _PMID_RE.match(q)
    if pmid_match and len(q.strip()) <= 20:
        return "simple"

    # simple: 单个关键词或 2-3个简单英文词（无复杂结构）
    words = q.split()
    if len(words) <= 3 and _SIMPLE_KW_RE.match(q):
        # 排除含中文的情况（中文短查询可能是自然语言）
        if not re.search(r"[一-鿿]", q):
            return "simple"

    # simple: 单个中文词（无空格，<=4字）→ 纯关键词
    if not re.search(r"\s", q) and len(q) <= 4 and re.search(r"[一-鿿]", q):
        return "simple"

    # complex: 包含复杂度指示词
    for pattern in _COMPLEXITY_MARKERS:
        if re.search(pattern, q, re.IGNORECASE):
            return "complex"

    # complex: 中文自然语言查询（通常包含隐含条件）
    if re.search(r"[一-鿿]", q) and len(q) > 15:
        return "complex"

    # moderate: 其他情况（多关键词组合、中等长度查询）
    return "moderate"


class WebSearcher:
    @staticmethod
    def search(query: str, max_results: int = 5) -> list:
        try:
            url = "https://html.duckduckgo.com/html/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            r = requests.post(url, data={"q": query}, headers=headers, timeout=10)
            r.raise_for_status()
            results = []
            blocks = re.findall(
                r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                r.text,
                re.DOTALL,
            )
            if not blocks:
                blocks = re.findall(
                    r'<a[^>]+href="(https?://[^"]*)"[^>]*>(.*?)</a>.*?<span[^>]*>(.*?)</span>',
                    r.text,
                    re.DOTALL,
                )
            for href, title, snippet in blocks[:max_results]:
                title = re.sub(r"<[^>]+>", "", title).strip()
                snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                if title and href.startswith("http"):
                    results.append({"title": title, "snippet": snippet, "url": href})
            return results
        except Exception as e:
            print(f"Web search error: {e}")
            return []


PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3", "qwen2", "deepseek-r1"],
    },
}


def _create_assistant(cfg_section: dict):
    """从配置节创建 AIAssistant 实例"""
    if not cfg_section or not cfg_section.get("enabled"):
        return None
    return AIAssistant(cfg_section)


class AIAssistant:
    def __init__(self, cfg: dict):
        self.enabled = cfg.get("enabled", False)
        self.provider = cfg.get("provider", "deepseek")
        self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "")
        self.base_url = cfg.get("base_url", "")
        self.max_tokens = cfg.get("max_tokens", 16384)
        # DeepSeek-V3/R1 API 硬限制 8192，超出会静默截断
        if self.provider == "deepseek" and self.max_tokens > 8192:
            self.max_tokens = 8192
        if not self.base_url and self.provider in PROVIDERS:
            self.base_url = PROVIDERS[self.provider]["base_url"]
        if not self.model and self.provider in PROVIDERS:
            models = PROVIDERS[self.provider]["models"]
            self.model = models[0] if models else ""
        self.session = requests.Session()

    def close(self):
        """关闭 HTTP Session"""
        if hasattr(self, "session") and self.session:
            try:
                self.session.close()
            except Exception:
                pass

    def is_available(self) -> bool:
        if not self.enabled or not self.base_url:
            return False
        # Ollama 是本地部署，不需要 API Key
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def _build_headers(self) -> dict:
        if self.provider == "anthropic":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        if self.provider == "ollama":
            return {"Content-Type": "application/json"}
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, messages: list, stream: bool = False) -> dict:
        if self.provider == "anthropic":
            system_msg = ""
            user_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_messages.append(m)
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": user_messages,
                "stream": stream,
            }
            if system_msg:
                payload["system"] = system_msg
            return payload
        return {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    def _get_endpoint(self) -> str:
        url = self.base_url.rstrip("/")
        # 如果用户配置的 URL 已经包含完整路径，直接使用
        if url.endswith("/chat/completions") or url.endswith("/messages"):
            return url
        # Ollama OpenAI 兼容端点需要 /v1 前缀
        if self.provider == "ollama" and not url.endswith("/v1"):
            url = f"{url}/v1"
        if self.provider == "anthropic":
            return f"{url}/messages"
        return f"{url}/chat/completions"

    def _extract_content(self, data: dict) -> str:
        if self.provider == "anthropic":
            content = data.get("content", [])
            return content[0].get("text", "") if content else ""
        choices = data.get("choices", [])
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        reasoning = msg.get("reasoning", "")
        # Ollama 思考模型（如 qwen3.5）将回复放在 reasoning 字段
        if reasoning:
            content = f"<think>{reasoning}</think>" + (content or "")
        # 保留 <think> 标签，由前端 formatAIText 处理显示
        return content

    def chat(self, message: str, context: str = "", max_retries: int = 2) -> str:
        """调用 AI API，支持重试机制"""
        if not self.is_available():
            return "AI_ERROR:ai_not_enabled"

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})

        import time

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                print(f"[INFO] AI request attempt {attempt + 1}/{max_retries + 1}")
                r = self.session.post(
                    self._get_endpoint(),
                    headers=self._build_headers(),
                    json=self._build_payload(messages, stream=False),
                    timeout=180,
                )
                r.raise_for_status()
                return self._extract_content(r.json())
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                last_error = e
                print(
                    f"[WARN] AI request network error (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )
                if attempt < max_retries:
                    wait_time = 2 * (attempt + 1)  # 指数退避：2秒、4秒
                    print(f"[INFO] Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
            except Exception as e:
                last_error = e
                print(
                    f"[ERROR] AI request failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )
                # 非网络错误，不重试
                return "AI_ERROR:request_failed"

        print(
            f"[ERROR] AI request failed after {max_retries + 1} attempts: {last_error}"
        )
        return "AI_ERROR:request_failed"

    def chat_stream(self, message: str, context: str = "", max_retries: int = 2):
        """流式调用 AI API，支持重试机制"""
        if not self.is_available():
            yield "AI_ERROR:ai_not_enabled"
            return

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})

        import time

        last_error = None

        for attempt in range(max_retries + 1):
            in_think = False
            finish_reason = None
            content_started = False  # 标记是否已经开始输出内容
            try:
                print(
                    f"[INFO] AI stream request attempt {attempt + 1}/{max_retries + 1}"
                )
                r = self.session.post(
                    self._get_endpoint(),
                    headers=self._build_headers(),
                    json=self._build_payload(messages, stream=True),
                    timeout=180,
                    stream=True,
                )
                r.raise_for_status()

                for line in r.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8", errors="ignore")
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        if "choices" in chunk:
                            choices = chunk["choices"]
                            if choices:
                                # 检测 finish_reason（截断信号）
                                finish = choices[0].get("finish_reason")
                                if finish:
                                    finish_reason = finish
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                # Ollama 思考模型的流式回复在 reasoning 字段
                                reasoning = delta.get("reasoning", "")
                                if reasoning:
                                    content_started = True
                                    if not in_think:
                                        yield "<think>"
                                        in_think = True
                                    yield reasoning
                                elif in_think:
                                    yield "</think>"
                                    in_think = False
                                if content:
                                    content_started = True
                                    yield content
                        elif chunk.get("type") == "content_block_delta":
                            content = chunk.get("delta", {}).get("text", "")
                            if content:
                                content_started = True
                                yield content
                        elif chunk.get("type") == "message_delta":
                            # Anthropic 的 message_delta 包含 stop_reason
                            stop_reason = chunk.get("delta", {}).get("stop_reason")
                            if stop_reason == "max_tokens":
                                finish_reason = "length"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

                # 确保关闭 think 标签
                if in_think:
                    yield "</think>"

                # 输出被 max_tokens 截断的警告
                if finish_reason == "length":
                    print("[WARN] AI output truncated by max_tokens limit")
                    yield "\nAI_WARNING:output_truncated"

                # 请求成功，退出重试循环
                return

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                last_error = e
                print(
                    f"[WARN] AI stream network error (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )

                # 确保关闭 think 标签
                if in_think:
                    yield "</think>"

                # 如果已经开始输出内容，无法重试，直接返回错误
                if content_started:
                    print(
                        "[ERROR] AI stream failed after content started, cannot retry"
                    )
                    yield "\nAI_ERROR:network_interrupted"
                    return

                # 还有重试次数，等待后重试
                if attempt < max_retries:
                    wait_time = 2 * (attempt + 1)  # 指数退避：2秒、4秒
                    print(f"[INFO] Retrying in {wait_time} seconds...")
                    yield f"\n⏳ 网络连接中断，{wait_time}秒后重试... (尝试 {attempt + 2}/{max_retries + 1})\n"
                    time.sleep(wait_time)
                continue

            except Exception as e:
                last_error = e
                print(
                    f"[ERROR] AI stream failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )

                # 确保关闭 think 标签
                if in_think:
                    yield "</think>"

                # 如果已经开始输出内容，无法重试
                if content_started:
                    yield "\nAI_ERROR:request_failed"
                    return

                # 非网络错误，不重试
                yield "\nAI_ERROR:request_failed"
                return

        # 所有重试都失败
        print(
            f"[ERROR] AI stream failed after {max_retries + 1} attempts: {last_error}"
        )
        yield "\nAI_ERROR:request_failed"


class SearchAI:
    """AI 智能检索助手（支持分层模型：轻量 + 快速 + 主模型）"""

    def __init__(self, config: dict):
        self.assistant = _create_assistant(config.get("ai_search", {}))
        # 兼容旧配置：如果没有 ai_search 节，用 ai 节
        if not self.assistant:
            self.assistant = _create_assistant(config.get("ai", {}))
        # 轻量级模型（用于 moderate 查询）
        self.lightweight_assistant = create_lightweight_assistant(config)

    def close(self):
        """关闭底层 HTTP Session"""
        if self.assistant:
            self.assistant.close()
        if (
            self.lightweight_assistant
            and self.lightweight_assistant is not self.assistant
        ):
            self.lightweight_assistant.close()

    def is_available(self) -> bool:
        return self.assistant is not None and self.assistant.is_available()

    @staticmethod
    def _build_simple_query_params(user_input: str, lang: str = "zh") -> dict:
        """规则引擎直接构建简单查询的搜索参数（跳过 AI）

        适用于 DOI/PMID 查找和简单关键词查询。
        """
        from search_engine import _contains_chinese, _translate_zh_to_en

        current_year = datetime.now().year
        q = user_input.strip()

        # DOI 查询
        doi_match = _DOI_RE.search(q)
        if doi_match:
            doi = doi_match.group(0)
            return {
                "query_en": doi,
                "query_zh": doi,
                "year_from": 1900,
                "year_to": current_year,
                "data_sources": [],
                "journal": "",
                "pub_type": "",
                "field": "",
                "explanation": f"DOI 精确查找: {doi}"
                if lang == "en"
                else f"DOI 精确查找: {doi}",
                "suggested_keywords": [],
            }

        # PMID 查询
        pmid_match = _PMID_RE.match(q)
        if pmid_match:
            pmid = pmid_match.group(1)
            return {
                "query_en": pmid,
                "query_zh": pmid,
                "year_from": 1900,
                "year_to": current_year,
                "data_sources": ["pubmed"],
                "journal": "",
                "pub_type": "",
                "field": "",
                "explanation": f"PMID 精确查找: {pmid}"
                if lang == "en"
                else f"PMID 精确查找: {pmid}",
                "suggested_keywords": [],
            }

        # 简单关键词查询
        if _contains_chinese(q):
            query_en = _translate_zh_to_en(q)
            query_zh = q
        else:
            query_en = q
            query_zh = q

        return {
            "query_en": query_en,
            "query_zh": query_zh,
            "year_from": current_year - 10,
            "year_to": current_year,
            "data_sources": [],
            "journal": "",
            "pub_type": "",
            "field": "",
            "explanation": f"简单关键词直接检索: {q}"
            if lang == "en"
            else f"简单关键词直接检索: {q}",
            "suggested_keywords": [query_en] if query_en else [],
        }

    def _get_web_context(self, user_input: str, lang: str = "zh") -> str:
        """获取联网搜索上下文"""
        web_context = ""
        try:
            current_year = datetime.now().year
            web_results = WebSearcher.search(
                f"{user_input} latest research {current_year - 1} {current_year}",
                max_results=5,
            )
            if web_results:
                if lang == "en":
                    web_context = (
                        "\n\nHere are related web search results for reference:\n"
                    )
                else:
                    web_context = "\n\n以下是联网搜索到的相关信息，供你参考：\n"
                for i, r in enumerate(web_results, 1):
                    web_context += f"\n{i}. {r['title']}\n   {r['snippet']}\n"
        except Exception:
            pass
        return web_context

    def _get_system_prompt(self, stream: bool = False, lang: str = "zh") -> str:
        """获取系统提示词"""
        current_year = datetime.now().year
        base_prompt = f"""You are a literature search expert. Users describe papers in natural language (Chinese or English), and you generate optimal search parameters.

Current year: {current_year}. Calculate accurate years from user's time description.
Chinese examples: "近两年" → year_from={current_year - 1}; "最近三年" → year_from={current_year - 2}
English examples: "last 2 years" → year_from={current_year - 1}; "recent 3 years" → year_from={current_year - 2}; "since 2023" → year_from=2023

CRITICAL RULE - JOURNAL EXTRACTION (HIGHEST PRIORITY):
If user mentions ANY journal names, you MUST include them in the journal field!
- Multiple journals: use comma-separated format, e.g. "nature,cell,science"
- Journal groups: "Nature系列"/"Nature及子刊"/"Nature series" → "nature"; "Cell系列"/"Cell series" → "cell"; "Science系列"/"Science series" → "science"
- Single journal: "Nature Methods" → "nature methods"
- Not specified → empty ""
- Examples:
  - "近两年在 cell、nature 和 science 及子刊上发表的光镊文献" → journal: "nature,cell,science"
  - "搜Nature和Science上的光镊文献" → journal: "nature,science"
  - "Cell系列的干细胞研究" → journal: "cell"
  - "papers in Nature and Science about CRISPR" → journal: "nature,science"
  - "recent Nature Reviews Neuroscience papers" → journal: "nature reviews neuroscience"
  - "find optical tweezers papers" → journal: ""

Data sources:
- pubmed: PubMed (biomedical, supports Boolean syntax)
- openalex: OpenAlex (open academic database, broad coverage)
- cnki: CNKI (Chinese papers, simple keywords only)
- wanfang: Wanfang (Chinese papers, simple keywords only)
- vip: VIP (Chinese papers, simple keywords only)
- google_scholar: Google Scholar (experimental, rate-limit risk)
- bing_academic: Bing Academic (experimental)

query field rules (IMPORTANT):
1. **Default: simple keywords** unless user explicitly asks for Boolean syntax
   - Correct: "atomic clock", "CRISPR gene editing", "光镊"
   - Wrong: ("atomic clock" OR "Atomic Clock") AND ("precision" OR "improvement")
2. **Use Boolean only when**: user explicitly requests PubMed syntax or AND/OR/NOT
3. **Chinese databases (CNKI/Wanfang/VIP)**: always simple keywords
4. **Query language**: if user writes in Chinese, generate English keywords for international databases

CRITICAL RULE - AUTHOR NAME CONVERSION:
When user mentions a Chinese author name, you MUST include BOTH Chinese and English formats in query!
- Chinese name "周金华" → English: "Jinhua Zhou" (given name FIRST, family name LAST)
- Chinese name "张伟" → English: "Wei Zhang"
- For pure author search: query should be "ChineseName OR EnglishName" to search all databases
- For author + topic: use Boolean with both formats
- Use field: "au" when user specifically asks about an author's papers
- Examples:
  - "找周金华教授的论文" → query: "周金华 OR Jinhua Zhou", field: "au"
  - "孙雯雯的论文" → query: "孙雯雯 OR Wenwen Sun", field: "au"
  - "张伟发表的CRISPR研究" → query: "(张伟 OR Wei Zhang) AND CRISPR", field: ""
  - "papers by Jinhua Zhou" → query: "Jinhua Zhou", field: "au"
  - Remove suffixes like 教授/博士/Dr./Prof. from author names

data_sources rules:
- User mentions a specific source → return that source, e.g. "search CNKI" → ["cnki"]
- User doesn't specify → return empty array [] (backend defaults to all)
- Chinese: "搜知网" → ["cnki"]; "找论文" → []
- English: "search PubMed" → ["pubmed"]; "find papers" → []

pub_type rules (publication type):
- User mentions document type → fill it, otherwise empty ""
- Values: ""(all) / "review" / "clinical trial" / "meta-analysis"
- Chinese: "找CRISPR的综述" → pub_type: "review"; "搜索临床试验" → pub_type: "clinical trial"
- English: "find CRISPR reviews" → pub_type: "review"; "search for clinical trials" → pub_type: "clinical trial"; "meta-analysis on diabetes" → pub_type: "meta-analysis"

field rules (search field):
- User specifies search scope → fill it, otherwise empty "" (default: title+abstract)
- Values: ""(default) / "ti"(title only) / "tiab"(title+abstract) / "au"(author) / "tw"(free text)
- Chinese: "标题含有光镊的论文" → field: "ti"; "作者是张三" → field: "au"
- English: "papers with CRISPR in title" → field: "ti"; "author: Zhang Wei" → field: "au"

REMINDER: Always check for journal names in user input! This is the most important extraction task."""

        # 语言指令
        if lang == "en":
            lang_instruction = "\nYou MUST respond in English. All analysis text, explanation, and search_reasoning fields must be in English."
        else:
            lang_instruction = "\n你必须用中文回答。所有分析文本、explanation 和 search_reasoning 字段都必须使用中文。"

        if stream:
            # 流式模式：先输出简短分析，最后输出JSON
            # 注意：DeepSeek max_tokens=8192，分析文本必须简洁，确保 JSON 完整输出
            return (
                base_prompt
                + lang_instruction
                + """

Output format (STRICT - follow exactly):
1. Brief analysis (2-3 sentences ONLY, do NOT exceed!)
2. Then on a NEW line, output this EXACT marker followed IMMEDIATELY by JSON:
__SEARCH_JSON__{"query_en":"English keywords","query_zh":"中文关键词","year_from":2025,"year_to":2026,"data_sources":[],"journal":"","pub_type":"","field":"","suggested_keywords":["keyword1","keyword2"]}

CRITICAL RULES:
- Analysis MUST be 2-3 sentences MAX (otherwise JSON gets truncated and search fails!)
- Marker is exactly __SEARCH_JSON__ (two underscores each side)
- JSON must be valid and complete
- year_from/year_to: use actual numbers (e.g., 2025, 2026), NOT relative terms like "近两年"
- query_en: English keywords for international databases (PubMed, OpenAlex, etc.)
- query_zh: Chinese keywords for Chinese databases (CNKI, Wanfang, VIP)
- If user writes in Chinese, translate to English for query_en, keep Chinese for query_zh
- If user writes in English, query_en and query_zh can be the same
- If user says "近两年": year_from=2025, year_to=2026 (current year is 2026)
- If user says "最近三年": year_from=2024, year_to=2026"""
            )

        # 非流式模式：直接返回 JSON
        return (
            base_prompt
            + lang_instruction
            + """

Return strictly in the following JSON format, no other content:
{{
  "query_en": "English keywords for international databases (PubMed, OpenAlex, etc.)",
  "query_zh": "中文关键词用于中文数据库（CNKI、万方、维普）",
  "year_from": year number,
  "year_to": year number,
  "data_sources": ["recommended data sources, based on user intent"],
  "journal": "journal names or group name (nature/cell/science). Use comma-separated for multiple journals. MUST include if user mentions any journals!",
  "pub_type": "review/clinical trial/meta-analysis, empty if not specified",
  "field": "ti/tiab/au/tw, empty if not specified",
  "explanation": "explain search strategy in user's language",
  "suggested_keywords": ["3-5 professional English keywords"],
  "search_reasoning": "brief reasoning for the search strategy"
}}"""
        )

    # 期刊名称映射表（用于从用户输入中提取期刊）
    # 格式: (关键词列表, 期刊名称)
    JOURNAL_KEYWORDS = [
        # 期刊系列（优先匹配，避免被单个期刊名覆盖）
        (["nature series", "nature及子刊", "nature系列", "nature子刊"], "nature"),
        (["cell series", "cell及子刊", "cell系列", "cell子刊"], "cell"),
        (["science series", "science及子刊", "science系列", "science子刊"], "science"),
        # 具体期刊名
        (["nature reviews"], "nature reviews"),
        (["nature methods"], "nature methods"),
        (["nature medicine"], "nature medicine"),
        (["nature physics"], "nature physics"),
        (["nature chemistry"], "nature chemistry"),
        (["nature biotechnology"], "nature biotechnology"),
        (["nature communications"], "nature communications"),
        (["cell reports"], "cell reports"),
        (["cell metabolism"], "cell metabolism"),
        (["cell stem cell"], "cell stem cell"),
        # 顶级期刊（单独出现时匹配）
        (["nature"], "nature"),
        (["cell"], "cell"),
        (["science"], "science"),
        (["lancet"], "lancet"),
        (["柳叶刀"], "lancet"),
        (["nejm", "new england journal"], "nejm"),
        (["新英格兰"], "nejm"),
        (["jama"], "jama"),
        (["pnas"], "pnas"),
        # 中文期刊名
        (["自然"], "nature"),
        (["细胞"], "cell"),
        (["科学"], "science"),
    ]

    def _extract_journals_from_input(self, user_input: str) -> str:
        """从用户输入中提取期刊名称（后备机制）"""
        input_lower = user_input.lower()
        journals = set()

        # 单字期刊关键词需要更精确的匹配（避免"单细胞"误匹配"cell"）
        single_word_journals = {"nature", "cell", "science"}

        for keywords, journal in self.JOURNAL_KEYWORDS:
            for keyword in keywords:
                if keyword in input_lower:
                    # 单字关键词需要检查是否是独立的词（前后有空格或标点）
                    if keyword in single_word_journals and len(keyword) <= 7:
                        # [Fix] 扩展分隔符集合，支持中文连接词（和、及、与）
                        import re

                        pattern = (
                            r"(?:^|[\s,，、和及与])"
                            + re.escape(keyword)
                            + r"(?:$|[\s,，、和及与])"
                        )
                        if re.search(pattern, input_lower):
                            journals.add(journal)
                            break
                    else:
                        journals.add(journal)
                        break

        return ",".join(sorted(journals)) if journals else ""

    def _parse_result(self, result: str, fallback_query: str, lang: str = "zh") -> dict:
        """解析 AI 返回的 JSON 结果"""
        try:
            # AI 搜索不需要显示思考过程，剥离 think 标签避免干扰 JSON 解析
            result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
            # 尝试从结果中提取 JSON（支持嵌套）
            start = result.find("{")
            if start >= 0:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(result[start:])
                # [Fix] 处理双语言查询字段
                # 如果 AI 返回了 query_en 和 query_zh，直接使用
                # 如果只返回了 query（旧格式），则进行兼容处理
                if "query_en" not in obj and "query_zh" not in obj:
                    # 兼容旧格式：只有一个 query 字段
                    old_query = obj.get("query", fallback_query)
                    from search_engine import _contains_chinese, _translate_zh_to_en

                    if _contains_chinese(old_query):
                        # 中文查询：query_zh=原始中文，query_en=翻译英文
                        obj["query_zh"] = old_query
                        obj["query_en"] = _translate_zh_to_en(old_query)
                    else:
                        # 英文查询：query_en=英文，query_zh=原始（可能也是英文）
                        obj["query_en"] = old_query
                        obj["query_zh"] = old_query
                    logger.info(
                        f"兼容旧格式: query_en={obj['query_en']}, query_zh={obj['query_zh']}"
                    )
                else:
                    # 新格式：确保两个字段都有值
                    if not obj.get("query_en"):
                        obj["query_en"] = obj.get("query_zh", fallback_query)
                    if not obj.get("query_zh"):
                        obj["query_zh"] = obj.get("query_en", fallback_query)

                # 后备机制：如果 AI 未返回 journal，从用户输入中提取
                if not obj.get("journal"):
                    extracted = self._extract_journals_from_input(fallback_query)
                    if extracted:
                        obj["journal"] = extracted
                        logger.info(f"AI 未返回 journal，从用户输入提取: {extracted}")
                return obj
        except Exception:
            pass

        # 解析失败时，从用户输入中提取期刊作为后备
        extracted_journal = self._extract_journals_from_input(fallback_query)

        # [Fix] 解析失败时也要处理双语言查询
        from search_engine import _contains_chinese, _translate_zh_to_en

        if _contains_chinese(fallback_query):
            query_en = _translate_zh_to_en(fallback_query)
            query_zh = fallback_query
        else:
            query_en = fallback_query
            query_zh = fallback_query

        return {
            "query_en": query_en,
            "query_zh": query_zh,
            "query": fallback_query,  # 保持兼容性
            "year_from": 2020,
            "year_to": datetime.now().year,
            "data_sources": [],
            "journal": extracted_journal,
            "pub_type": "",
            "field": "",
            "explanation": f"AI parsing failed, using original input: {fallback_query}"
            if lang == "en"
            else f"AI 解析失败，使用原始输入: {fallback_query}",
            "suggested_keywords": [],
        }

    def analyze_query(self, user_input: str, lang: str = "zh") -> dict:
        """非流式分析查询（支持分级路由）

        simple  → 跳过 AI，规则引擎直接构建
        moderate → 轻量模型 + 缓存
        complex  → 主模型 + 缓存
        """
        # --- 检查缓存 ---
        cache_key = hashlib.md5(f"{user_input}:{lang}".encode()).hexdigest()
        cached = _query_analysis_cache.get(cache_key)
        if cached is not None:
            print(f"[CACHE HIT] AI search analysis: '{user_input[:50]}'")
            return cached

        # --- 查询复杂度分级 ---
        complexity = _classify_query_complexity(user_input)
        print(f"[QUERY TIER] complexity={complexity}, query='{user_input[:50]}'")

        # simple: 跳过 AI，规则引擎直接构建参数
        if complexity == "simple":
            result = self._build_simple_query_params(user_input, lang=lang)
            _query_analysis_cache.put(cache_key, result)
            return result

        # 选择模型
        if (
            complexity == "moderate"
            and self.lightweight_assistant
            and self.lightweight_assistant.is_available()
        ):
            assistant = self.lightweight_assistant
        else:
            assistant = self.assistant

        web_context = self._get_web_context(user_input, lang=lang)
        system_prompt = self._get_system_prompt(lang=lang)

        # 截断过长输入
        if len(user_input) > 2000:
            user_input = user_input[:2000]
        result = assistant.chat(user_input + web_context, system_prompt)
        parsed = self._parse_result(result, user_input, lang=lang)
        _query_analysis_cache.put(cache_key, parsed)
        return parsed

    def _find_json_marker(self, text: str) -> tuple:
        """查找 JSON 标记的位置，支持多种格式和截断情况。返回 (pos, marker_len)，未找到返回 (-1, 0)"""
        # 按优先级查找各种可能的完整标记格式
        markers = [
            "__SEARCH_JSON__",
            "SEARCH_JSON__",
            "__SEARCH_JSON",
            "SEARCH_JSON",
            "SEARCHJSON",
            "__SEARCH_",
            "__SEARCH",
        ]
        for marker in markers:
            pos = text.find(marker)
            if pos >= 0:
                return pos, len(marker)

        # 处理截断情况：标记不完整但后面跟着 JSON
        # 例如 "__SEARCH" 后面直接跟 "{"
        # 查找可能的截断标记后跟 JSON 对象
        truncated_match = re.search(
            r"(__SEARCH(?:_JSON(?:__)?)?|SEARCH_JSON(?:__)?|SEARCHJSON)\s*(\{)", text
        )
        if truncated_match:
            # 只返回标记部分的长度，不包含 {
            marker_text = truncated_match.group(1)
            return truncated_match.start(), len(marker_text)

        # 最后尝试：查找 "__SEARCH_" 后面跟任意内容再跟 "{"
        last_search = text.rfind("__SEARCH")
        if last_search >= 0:
            # 检查这个位置之后是否有 JSON 对象
            after_search = text[last_search:]
            json_match = re.search(r"__SEARCH[_A-Z]*\s*(\{)", after_search)
            if json_match:
                # 返回标记文本的长度（到 { 之前）
                marker_text = json_match.group(0).rstrip("{").rstrip()
                return last_search, len(marker_text)

        return -1, 0

    def analyze_query_stream(self, user_input: str, lang: str = "zh"):
        """流式分析查询，yield 每个 chunk，最后 yield 完整的分析结果 dict

        支持分级路由：
          simple  → 跳过 AI，直接 yield 规则引擎结果
          moderate → 轻量模型流式 + 缓存
          complex  → 主模型流式 + 缓存
        """
        # --- 检查缓存 ---
        cache_key = hashlib.md5(f"{user_input}:{lang}".encode()).hexdigest()
        cached = _query_analysis_cache.get(cache_key)
        if cached is not None:
            print(f"[CACHE HIT] AI search analysis (stream): '{user_input[:50]}'")
            # 缓存命中：yield 简短提示 + 结果 dict
            if lang == "en":
                yield "(Using cached analysis)\n"
            else:
                yield "（使用缓存分析结果）\n"
            yield cached
            return

        # --- 查询复杂度分级 ---
        complexity = _classify_query_complexity(user_input)
        print(f"[QUERY TIER] complexity={complexity}, query='{user_input[:50]}'")

        # simple: 跳过 AI，规则引擎直接构建
        if complexity == "simple":
            result = self._build_simple_query_params(user_input, lang=lang)
            _query_analysis_cache.put(cache_key, result)
            if lang == "en":
                yield f"Direct search for: {user_input}\n"
            else:
                yield f"直接检索: {user_input}\n"
            yield result
            return

        # 选择模型
        if (
            complexity == "moderate"
            and self.lightweight_assistant
            and self.lightweight_assistant.is_available()
        ):
            assistant = self.lightweight_assistant
        else:
            assistant = self.assistant

        web_context = self._get_web_context(user_input, lang=lang)
        system_prompt = self._get_system_prompt(stream=True, lang=lang)

        # 截断过长输入
        if len(user_input) > 2000:
            user_input = user_input[:2000]

        full_response = []
        marker_found = False
        already_yielded = 0

        for chunk in assistant.chat_stream(user_input + web_context, system_prompt):
            full_response.append(chunk)

            if marker_found:
                continue

            current_text = "".join(full_response)

            # 查找标记
            marker_pos, marker_len = self._find_json_marker(current_text)
            if marker_pos >= 0:
                before_marker = current_text[:marker_pos]
                new_content = before_marker[already_yielded:]
                if new_content:
                    yield new_content
                marker_found = True
                continue

            # 没有标记，正常 yield
            yield chunk
            already_yielded = len(current_text)

        # 解析结果
        result = "".join(full_response)
        explanation = ""
        search_json = None

        # 尝试标记方式解析
        marker_pos, marker_len = self._find_json_marker(result)
        if marker_pos >= 0:
            explanation = result[:marker_pos]
            explanation = re.sub(
                r"<think>.*?</think>", "", explanation, flags=re.DOTALL
            ).strip()
            json_str = result[marker_pos + marker_len :]
            try:
                decoder = json.JSONDecoder()
                search_json, _ = decoder.raw_decode(json_str.strip())
            except Exception:
                pass

        # 如果标记方式失败，尝试直接解析 JSON（非思考模型）
        if not search_json:
            result_cleaned = re.sub(
                r"<think>.*?</think>", "", result, flags=re.DOTALL
            ).strip()
            # 逐个尝试前向查找 { 位置，使用 raw_decode 验证
            search_start = 0
            while search_start < len(result_cleaned):
                brace_pos = result_cleaned.find("{", search_start)
                if brace_pos < 0:
                    break
                try:
                    decoder = json.JSONDecoder()
                    search_json, _ = decoder.raw_decode(result_cleaned, brace_pos)
                    explanation = result_cleaned[:brace_pos].strip()
                    break
                except (json.JSONDecodeError, ValueError):
                    search_start = brace_pos + 1
                    continue

        if search_json:
            search_json["explanation"] = explanation
            search_json["search_reasoning"] = explanation
            # 后备机制：如果AI未返回journal，从用户输入中提取
            if not search_json.get("journal"):
                extracted = self._extract_journals_from_input(user_input)
                if extracted:
                    search_json["journal"] = extracted
                    logger.info(
                        f"流式搜索：AI未返回journal，从用户输入提取: {extracted}"
                    )
            _query_analysis_cache.put(cache_key, search_json)
            yield search_json
        else:
            fallback = self._parse_result(result, user_input, lang=lang)
            _query_analysis_cache.put(cache_key, fallback)
            yield fallback


class AnalysisAI:
    """AI 论文分析助手（支持分级：summary 用轻量模型，detail/compare 用主模型）"""

    # 分析模式对应的模型层级
    _LIGHTWEIGHT_MODES = {"summary"}

    def __init__(self, config: dict):
        self.assistant = _create_assistant(config.get("ai_analysis", {}))
        # 兼容旧配置
        if not self.assistant:
            self.assistant = _create_assistant(config.get("ai", {}))
        # 轻量级模型（用于 summary 模式）
        self.lightweight_assistant = create_lightweight_assistant(config)

    def close(self):
        """关闭底层 HTTP Session"""
        if self.assistant:
            self.assistant.close()
        if (
            self.lightweight_assistant
            and self.lightweight_assistant is not self.assistant
        ):
            self.lightweight_assistant.close()

    def is_available(self) -> bool:
        return self.assistant is not None and self.assistant.is_available()

    def _pick_assistant(self, mode: str = "summary"):
        """根据分析模式选择模型

        summary → 轻量模型（省 token，够用）
        detail/compare/novelty → 主模型（需要深度推理）
        """
        if (
            mode in self._LIGHTWEIGHT_MODES
            and self.lightweight_assistant
            and self.lightweight_assistant.is_available()
        ):
            return self.lightweight_assistant
        return self.assistant

    def chat(self, message: str, context: str = "", mode: str = "detail") -> str:
        assistant = self._pick_assistant(mode)
        if not assistant:
            return "AI_ERROR:ai_not_enabled"
        return assistant.chat(message, context)

    def chat_stream(self, message: str, context: str = "", mode: str = "detail"):
        assistant = self._pick_assistant(mode)
        if not assistant:
            yield "AI_ERROR:ai_not_enabled"
            return
        yield from assistant.chat_stream(message, context)

    def summarize(self, papers: list, lang: str = "zh") -> str:
        """总结文献（使用轻量模型）"""
        if lang == "en":
            context = "You are an academic literature analysis assistant. Please summarize the main findings and trends of the following literature in English."
            prompt = "Please summarize the main research directions and key findings of the following papers:\n\n"
        else:
            context = "你是一个学术文献分析助手。请用中文总结以下文献的主要发现和趋势。"
            prompt = "请总结以下文献的主要研究方向和关键发现:\n\n"

        # 估算 token 数，动态调整论文数量和摘要长度
        # 粗略估算：1 个 token ≈ 4 个字符（英文）或 2 个字符（中文）
        max_tokens = (
            8000
            if (self.assistant and self.assistant.provider == "deepseek")
            else 12000
        )
        abstract_limit = 300
        selected_papers = []

        for p in papers[:10]:
            # 估算每篇论文的 token
            title = getattr(p, "title", "") or ""
            abstract = getattr(p, "abstract", "") or ""
            # 简单估算：(标题 + 摘要) / 3 ≈ token 数
            paper_tokens = (len(title) + len(abstract)) // 3
            # 加上固定开销（作者、期刊等）
            paper_tokens += 50

            if len(selected_papers) >= 3 and paper_tokens > 500:
                # 超过 3 篇后，大幅截断摘要以控制总 token
                abstract_limit = 150
            if len(selected_papers) >= 5:
                abstract_limit = 100

            selected_papers.append(p)

        paper_text = "\n\n".join(
            [
                f"{'Title' if lang == 'en' else '标题'}: {getattr(p, 'title', 'Unknown')}\n"
                f"{'Authors' if lang == 'en' else '作者'}: {', '.join((getattr(p, 'authors', None) or [])[:3])}\n"
                f"{'Journal' if lang == 'en' else '期刊'}: {getattr(p, 'journal', '')} ({getattr(p, 'year', '')})\n"
                f"{'Abstract' if lang == 'en' else '摘要'}: {(getattr(p, 'abstract', '') or '')[:abstract_limit]}"
                for p in selected_papers
            ]
        )
        return self.chat(f"{prompt}{paper_text}", context, mode="summary")
