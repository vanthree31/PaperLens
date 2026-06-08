"""Flask 后端 - API 路由"""

import os
import sys
import re
import json
import html
import yaml
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
from search_engine import SearchEngine
from exporters import export_ris, export_bibtex, export_csv
from ai_assistant import SearchAI, AnalysisAI


def _get_app_data_dir() -> str:
    """应用数据目录：%APPDATA%/LitSearch/（Windows 标准位置）"""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        data_dir = os.path.join(appdata, "LitSearch")
    else:
        # 非 Windows 或 APPDATA 未设置时回退到 exe 同目录
        if getattr(sys, 'frozen', False):
            data_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
        else:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_config_path():
    """配置文件路径"""
    return os.path.join(_get_app_data_dir(), "config.yaml")


def load_config():
    """加载配置：优先 data/config.yaml，否则用打包内置默认"""
    user_path = get_config_path()
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    # 打包模式：从内置默认加载
    if getattr(sys, 'frozen', False):
        bundled = os.path.join(getattr(sys, '_MEIPASS', ''), "config.yaml")
        if os.path.exists(bundled):
            with open(bundled, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    return {}


def save_config(config):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


def _get_user_data_path(filename: str) -> str:
    """获取用户数据文件路径"""
    return os.path.join(_get_app_data_dir(), filename)


def _escape_paper(paper) -> dict:
    def esc(s):
        if s is None:
            return ""
        return html.escape(str(s))
    return {
        "title": esc(paper.title), "authors": [esc(a) for a in paper.authors],
        "journal": esc(paper.journal), "year": paper.year,
        "doi": esc(paper.doi), "pmid": esc(paper.pmid),
        "abstract": esc(paper.abstract), "citation_count": paper.citation_count,
        "oa_url": esc(paper.oa_url), "keywords": [esc(k) for k in paper.keywords],
        "source": esc(paper.source),
    }


def _build_paper_prompt(papers, mode):
    """构建不同模式的分析 prompt"""
    paper_info = []
    for i, p in enumerate(papers, 1):
        info = f"""【论文 {i}】
标题: {p.title}
作者: {', '.join(p.authors[:10])}
期刊: {p.journal} ({p.year})
DOI: {p.doi}  PMID: {p.pmid}  被引: {p.citation_count}
摘要: {p.abstract if p.abstract else '无摘要'}
关键词: {', '.join(p.keywords) if p.keywords else '无'}"""
        paper_info.append(info)
    papers_text = "\n\n".join(paper_info)

    fmt = """格式要求：
- 用中文回答，使用纯文本，不要用 Markdown 符号（# * - ` > 等）
- 用"一、二、三"或"1. 2. 3."编号，段落之间空一行
- 语言专业精炼，像资深教授写给同行的评审意见"""

    if mode == "detail":
        prompt = f"""你是一位在该领域有深厚造诣的资深学者，请对以下论文进行深度解析。你的读者是同行专家，不需要科普，直接说干货。

{fmt}

请从以下维度逐篇解析：

一、核心贡献
用一两句话说清楚这篇论文到底做了什么、解决了什么关键问题。不要复述标题。

二、技术路线
用了什么方法？关键实验/算法/装置是什么？方法上有什么创新？

三、关键结果
最重要的定量或定性发现是什么？有没有出乎意料的结果？

四、学术价值与局限
这篇论文的贡献在领域内处于什么水平？有什么明显的局限性或可商榷之处？

五、与本领域其他工作的关系
这篇论文和同期或经典工作相比，有什么异同？是否解决了前人遗留的问题？

{papers_text}"""

    elif mode == "compare":
        prompt = f"""你是一位在该领域有深厚造诣的资深学者，请对以下论文进行系统对比分析。你的读者是同行专家。

{fmt}

请从以下角度展开：

一、研究路线对比
这几篇论文的技术路线有何异同？各自的优劣势是什么？

二、创新点对比
各自的最核心创新是什么？哪个更有突破性？

三、互补性与研究空白
这些工作之间有什么互补关系？是否共同暴露了领域中尚未解决的问题？

四、对后续研究的建议
如果要在这个方向继续深入，最值得关注的问题是什么？哪些技术路线更有前景？

{papers_text}"""

    else:  # summary
        prompt = f"""你是一位在该领域有深厚造诣的资深学者，请用最精炼的语言总结以下论文。

{fmt}

每篇论文用 3-5 句话概括，必须包含：
- 做了什么（一句话说清核心工作）
- 怎么做的（关键技术）
- 发现了什么（核心结果）
- 有什么用（学术或应用价值）

不需要客套话，直接说内容。

{papers_text}"""

    return prompt


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    config = load_config()
    engine = SearchEngine(config)
    search_ai = SearchAI(config)
    analysis_ai = AnalysisAI(config)

    cached_papers = {"papers": [], "query": ""}
    ai_cache = {}

    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.route("/api/search", methods=["POST"])
    def search():
        data = request.json or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "请输入检索词"}), 400
        current_year = datetime.now().year
        papers = engine.search(
            query=query, year_from=data.get("year_from", 2020), year_to=data.get("year_to", current_year),
            sort=data.get("sort", "relevance"), max_results=data.get("max_results", 50),
            use_pubmed=data.get("use_pubmed", True), use_openalex=data.get("use_openalex", True),
            journal=data.get("journal", "").strip(), field=data.get("field", "").strip(),
            mesh_term=data.get("mesh_term", "").strip(), pub_type=data.get("pub_type", "").strip(),
        )
        cached_papers["papers"] = papers
        cached_papers["query"] = query
        results = [_escape_paper(p) for p in papers]
        return jsonify({"total": len(results), "query": query, "papers": results})

    @app.route("/api/ai-search", methods=["POST"])
    def ai_search():
        if not search_ai.is_available():
            return jsonify({"error": "AI 检索功能未启用，请在设置中配置检索模型的 API Key"}), 400
        data = request.json or {}
        user_input = data.get("query", "").strip()
        if not user_input:
            return jsonify({"error": "请输入检索描述"}), 400

        analysis = search_ai.analyze_query(user_input)
        current_year = datetime.now().year
        papers = engine.search(
            query=analysis.get("query", user_input),
            year_from=analysis.get("year_from", 2020), year_to=analysis.get("year_to", current_year),
            sort="relevance", max_results=data.get("max_results", 50),
            use_pubmed=data.get("use_pubmed", True), use_openalex=data.get("use_openalex", True),
            journal=analysis.get("journal", ""), field=analysis.get("field", ""),
            mesh_term=analysis.get("mesh_term", ""), pub_type=analysis.get("pub_type", ""),
        )
        cached_papers["papers"] = papers
        cached_papers["query"] = analysis.get("query", user_input)
        results = [_escape_paper(p) for p in papers]
        return jsonify({
            "total": len(results), "query": analysis.get("query", ""),
            "explanation": analysis.get("explanation", ""), "analysis": analysis, "papers": results,
        })

    @app.route("/api/ai/analyze-papers", methods=["POST"])
    def ai_analyze_papers():
        if not analysis_ai.is_available():
            return jsonify({"error": "AI 分析功能未启用，请在设置中配置分析模型的 API Key"}), 400

        data = request.json or {}
        indices = sorted(data.get("indices", []))
        mode = data.get("mode", "summary")
        if mode not in ("summary", "detail", "compare"):
            mode = "summary"
        force_refresh = data.get("force_refresh", False)
        use_stream = data.get("stream", False)

        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "没有文献可分析"}), 400
        if not indices:
            return jsonify({"error": "请先勾选要分析的论文"}), 400

        selected = [papers[i] for i in indices if 0 <= i < len(papers)]
        if not selected:
            return jsonify({"error": "选中的论文无效"}), 400

        cache_key = f"{mode}_{'_'.join(str(i) for i in indices)}"
        if not force_refresh and cache_key in ai_cache and ai_cache[cache_key]:
            return jsonify({"response": ai_cache[cache_key], "count": len(selected), "mode": mode, "cached": True})

        prompt = _build_paper_prompt(selected, mode)
        context = "你是一位资深学术论文分析专家，擅长用中文为同行学者提供精准、深刻、不啰嗦的论文分析。根据论文内容自动判断所属领域，用该领域的专业语言进行分析。"

        if use_stream:
            def generate():
                full_response = []
                for chunk in analysis_ai.chat_stream(prompt, context):
                    full_response.append(chunk)
                    yield chunk
                result = "".join(full_response)
                if result and not result.startswith("AI 请求失败"):
                    ai_cache[cache_key] = result
            return Response(generate(), mimetype="text/plain; charset=utf-8",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        result = analysis_ai.chat(prompt, context)
        if result and not result.startswith("AI 请求失败"):
            ai_cache[cache_key] = result
        return jsonify({"response": result, "count": len(selected), "mode": mode, "cached": False})

    @app.route("/api/history", methods=["GET"])
    def get_history():
        path = _get_user_data_path("history.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify([])

    @app.route("/api/history", methods=["POST"])
    def save_history():
        data = request.json or []
        path = _get_user_data_path("history.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data[:30], f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/preferences", methods=["GET"])
    def get_preferences():
        path = _get_user_data_path("preferences.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({})

    @app.route("/api/preferences", methods=["POST"])
    def save_preferences():
        data = request.json or {}
        path = _get_user_data_path("preferences.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/batch-doi", methods=["POST"])
    def batch_doi():
        """批量 DOI 查询"""
        data = request.json or {}
        dois = data.get("dois", [])
        if not dois:
            return jsonify({"error": "请提供 DOI 列表"}), 400

        found_papers = []
        found_escaped = []
        valid_count = 0
        for doi in dois[:50]:
            doi = doi.strip()
            if not doi:
                continue
            valid_count += 1
            paper = engine.search_by_doi(doi)
            if paper:
                found_papers.append(paper)
                found_escaped.append(_escape_paper(paper))

        # 合并到 cached_papers（确保后续导出/AI分析可用）
        existing_dois = {p.doi.lower() for p in cached_papers["papers"] if p.doi}
        for p in found_papers:
            if p.doi and p.doi.lower() not in existing_dois:
                cached_papers["papers"].append(p)
                existing_dois.add(p.doi.lower())

        return jsonify({"total": len(found_escaped), "papers": found_escaped, "not_found": valid_count - len(found_escaped)})

    @app.route("/api/download-pdf", methods=["POST"])
    def download_pdf():
        """验证 OA 论文 PDF 链接是否可用"""
        import urllib.request
        data = request.json or {}
        url = data.get("url", "").strip()
        title = data.get("title", "paper")[:50]

        if not url:
            return jsonify({"error": "无下载链接"}), 400

        safe_title = re.sub(r'[^\w\-]', '_', title).strip('_') or "paper"
        filename = f"{safe_title}.pdf"

        try:
            # 只读取前 8 字节验证 PDF 魔数，不下载整个文件
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-7"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                header = resp.read(8)
                if not header.startswith(b'%PDF'):
                    return jsonify({"error": "链接不是 PDF 文件"}), 400
            return jsonify({"filename": filename, "url": url})
        except Exception as e:
            return jsonify({"error": f"链接验证失败: {e}"}), 500

    @app.route("/api/export", methods=["POST"])
    def export():
        data = request.json or {}
        fmt = data.get("format", "ris")
        indices = data.get("indices", [])
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "没有可导出的文献"}), 400
        selected = [papers[i] for i in indices if 0 <= i < len(papers)] if indices else papers
        safe_q = re.sub(r'[^\w\-]', '_', cached_papers['query'][:40]).strip('_') or "results"
        if fmt == "ris":
            return jsonify({"content": export_ris(selected), "filename": f"lit_search_{safe_q}.ris", "mime": "application/x-research-info-systems"})
        elif fmt == "bibtex":
            return jsonify({"content": export_bibtex(selected), "filename": f"lit_search_{safe_q}.bib", "mime": "application/x-bibtex"})
        elif fmt == "csv":
            return jsonify({"content": export_csv(selected), "filename": f"lit_search_{safe_q}.csv", "mime": "text/csv"})
        return jsonify({"error": f"不支持的格式: {fmt}"}), 400

    @app.route("/api/data-dir", methods=["GET"])
    def get_data_dir():
        return jsonify({"path": _get_app_data_dir()})

    @app.route("/api/open-data-dir", methods=["POST"])
    def open_data_dir():
        import subprocess
        data_dir = _get_app_data_dir()
        try:
            subprocess.Popen(["explorer", data_dir])
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["GET"])
    def get_config():
        return jsonify(_mask_keys(load_config()))

    @app.route("/api/config", methods=["POST"])
    def update_config():
        data = request.json or {}
        cfg = load_config()
        _deep_update(cfg, data)
        save_config(cfg)
        nonlocal engine, search_ai, analysis_ai
        engine = SearchEngine(cfg)
        search_ai = SearchAI(cfg)
        analysis_ai = AnalysisAI(cfg)
        return jsonify({"ok": True})

    @app.route("/api/ai/chat", methods=["POST"])
    def ai_chat():
        if not analysis_ai.is_available():
            return jsonify({"error": "AI 分析功能未启用"}), 400
        data = request.json or {}
        return jsonify({"response": analysis_ai.chat(data.get("message", ""), data.get("context", ""))})

    @app.route("/api/ai/summarize", methods=["POST"])
    def ai_summarize():
        if not analysis_ai.is_available():
            return jsonify({"error": "AI 分析功能未启用"}), 400
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "没有文献可总结"}), 400
        return jsonify({"response": analysis_ai.summarize(papers)})

    return app


def _mask_keys(obj):
    """递归隐藏敏感字段（精确匹配，避免误杀）"""
    SENSITIVE_KEYS = {"api_key", "apikey", "api_secret", "secret", "password", "token", "access_token", "secret_key"}

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k.lower() in SENSITIVE_KEYS:
                if isinstance(v, str) and len(v) > 4:
                    result[k] = v[:4] + "****" + v[-4:]
                else:
                    result[k] = v
            else:
                result[k] = _mask_keys(v)
        return result
    elif isinstance(obj, list):
        return [_mask_keys(i) for i in obj]
    return obj


def _deep_update(base, update):
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
