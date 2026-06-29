"""AI 辅助端口 - 支持双模型配置（检索模型 + 分析模型）"""

import json
import re
from datetime import datetime
import requests


class WebSearcher:
    @staticmethod
    def search(query: str, max_results: int = 5) -> list:
        try:
            url = "https://html.duckduckgo.com/html/"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.post(url, data={"q": query}, headers=headers, timeout=10)
            r.raise_for_status()
            results = []
            blocks = re.findall(
                r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                r.text, re.DOTALL
            )
            if not blocks:
                blocks = re.findall(
                    r'<a[^>]+href="(https?://[^"]*)"[^>]*>(.*?)</a>.*?<span[^>]*>(.*?)</span>',
                    r.text, re.DOTALL
                )
            for href, title, snippet in blocks[:max_results]:
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                if title and href.startswith("http"):
                    results.append({"title": title, "snippet": snippet, "url": href})
            return results
        except Exception as e:
            print(f"Web search error: {e}")
            return []


PROVIDERS = {
    "openai": {"base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini"]},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-reasoner"]},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]},
    "ollama": {"base_url": "http://localhost:11434/v1", "models": ["llama3", "qwen2", "deepseek-r1"]},
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
        if not self.base_url and self.provider in PROVIDERS:
            self.base_url = PROVIDERS[self.provider]["base_url"]
        if not self.model and self.provider in PROVIDERS:
            models = PROVIDERS[self.provider]["models"]
            self.model = models[0] if models else ""
        self.session = requests.Session()

    def is_available(self) -> bool:
        return self.enabled and self.api_key and self.base_url

    def _build_headers(self) -> dict:
        if self.provider == "anthropic":
            return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _build_payload(self, messages: list, stream: bool = False) -> dict:
        if self.provider == "anthropic":
            system_msg = ""
            user_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_messages.append(m)
            payload = {"model": self.model, "max_tokens": self.max_tokens, "messages": user_messages, "stream": stream}
            if system_msg:
                payload["system"] = system_msg
            return payload
        return {"model": self.model, "messages": messages, "temperature": 0.7, "max_tokens": self.max_tokens, "stream": stream}

    def _get_endpoint(self) -> str:
        url = self.base_url.rstrip("/")
        # 如果用户配置的 URL 已经包含完整路径，直接使用
        if url.endswith("/chat/completions") or url.endswith("/messages"):
            return url
        if self.provider == "anthropic":
            return f"{url}/messages"
        return f"{url}/chat/completions"

    def _extract_content(self, data: dict) -> str:
        if self.provider == "anthropic":
            content = data.get("content", [])
            return content[0].get("text", "") if content else ""
        choices = data.get("choices", [])
        return choices[0].get("message", {}).get("content", "") if choices else ""

    def chat(self, message: str, context: str = "") -> str:
        if not self.is_available():
            return "AI_ERROR:ai_not_enabled"
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})
        try:
            r = self.session.post(self._get_endpoint(), headers=self._build_headers(),
                              json=self._build_payload(messages, stream=False), timeout=120)
            r.raise_for_status()
            return self._extract_content(r.json())
        except Exception as e:
            print(f"[ERROR] AI request failed: {e}")
            return "AI_ERROR:request_failed"

    def chat_stream(self, message: str, context: str = ""):
        if not self.is_available():
            yield "AI_ERROR:ai_not_enabled"
            return
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})
        try:
            r = self.session.post(self._get_endpoint(), headers=self._build_headers(),
                              json=self._build_payload(messages, stream=True),
                              timeout=120, stream=True)
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
                            content = choices[0].get("delta", {}).get("content", "")
                            if content:
                                yield content
                    elif chunk.get("type") == "content_block_delta":
                        content = chunk.get("delta", {}).get("text", "")
                        if content:
                            yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        except Exception as e:
            print(f"[ERROR] AI stream failed: {e}")
            yield "\nAI_ERROR:request_failed"


class SearchAI:
    """AI 智能检索助手（用快速模型）"""

    def __init__(self, config: dict):
        self.assistant = _create_assistant(config.get("ai_search", {}))
        # 兼容旧配置：如果没有 ai_search 节，用 ai 节
        if not self.assistant:
            self.assistant = _create_assistant(config.get("ai", {}))

    def is_available(self) -> bool:
        return self.assistant is not None and self.assistant.is_available()

    def analyze_query(self, user_input: str) -> dict:
        web_context = ""
        try:
            current_year = datetime.now().year
            web_results = WebSearcher.search(f"{user_input} latest research {current_year-1} {current_year}", max_results=5)
            if web_results:
                web_context = "\n\n以下是联网搜索到的相关信息，供你参考：\n"
                for i, r in enumerate(web_results, 1):
                    web_context += f"\n{i}. {r['title']}\n   {r['snippet']}\n"
        except Exception:
            pass

        system_prompt = """你是一个 PubMed 文献检索专家。用户用自然语言描述想搜索的论文，你生成最优的 PubMed 检索参数。

请严格按以下 JSON 格式返回，不要包含其他内容：
{
  "query": "PubMed 检索式（可含字段标签 [ti] [tiab] [ta] [mh]，布尔运算 AND/OR/NOT）",
  "journal": "期刊名或缩写（无则空字符串）",
  "field": "默认字段标签（默认 tiab）",
  "year_from": 年份数字,
  "year_to": 年份数字,
  "mesh_term": "MeSH 主题词（无则空）",
  "pub_type": "文献类型 review/clinical trial（无则空）",
  "explanation": "用中文详细说明检索策略，包括：1）为什么选择这些关键词；2）检索式的逻辑结构；3）预期的检索范围",
  "suggested_keywords": ["3-5个专业英文关键词"],
  "search_reasoning": "简要说明检索策略的推理过程，帮助用户理解为什么这样设计检索式"
}"""

        # 截断过长输入
        if len(user_input) > 2000:
            user_input = user_input[:2000]
        result = self.assistant.chat(user_input + web_context, system_prompt)
        try:
            # 尝试从结果中提取 JSON（支持嵌套）
            start = result.find('{')
            if start >= 0:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(result[start:])
                return obj
        except Exception:
            pass
        return {
            "query": user_input, "journal": "", "field": "tiab",
            "year_from": 2020, "year_to": datetime.now().year,
            "mesh_term": "", "pub_type": "",
            "explanation": f"AI 解析失败，使用原始输入: {user_input}",
            "suggested_keywords": [],
        }


class AnalysisAI:
    """AI 论文分析助手（用高质量模型）"""

    def __init__(self, config: dict):
        self.assistant = _create_assistant(config.get("ai_analysis", {}))
        # 兼容旧配置
        if not self.assistant:
            self.assistant = _create_assistant(config.get("ai", {}))

    def is_available(self) -> bool:
        return self.assistant is not None and self.assistant.is_available()

    def chat(self, message: str, context: str = "") -> str:
        if not self.assistant:
            return "AI_ERROR:ai_not_enabled"
        return self.assistant.chat(message, context)

    def chat_stream(self, message: str, context: str = ""):
        if not self.assistant:
            yield "AI_ERROR:ai_not_enabled"
            return
        yield from self.assistant.chat_stream(message, context)

    def summarize(self, papers: list) -> str:
        context = "你是一个学术文献分析助手。请用中文总结以下文献的主要发现和趋势。"
        paper_text = "\n\n".join([
            f"标题: {getattr(p, 'title', 'Unknown')}\n"
            f"作者: {', '.join((getattr(p, 'authors', None) or [])[:3])}\n"
            f"期刊: {getattr(p, 'journal', '')} ({getattr(p, 'year', '')})\n"
            f"摘要: {(getattr(p, 'abstract', '') or '')[:300]}"
            for p in papers[:10]
        ])
        return self.chat(f"请总结以下文献的主要研究方向和关键发现:\n\n{paper_text}", context)
