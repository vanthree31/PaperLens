"""Flask 后端 - API 路由"""

import os
import sys
import re
import json
import html
import threading
import yaml
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
from search_engine import SearchEngine
from exporters import export_ris, export_bibtex, export_csv, export_endnote_xml
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
        try:
            with open(user_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ERROR] Failed to load config from {user_path}: {e}")
    # 打包模式：从内置默认加载
    if getattr(sys, 'frozen', False):
        bundled = os.path.join(getattr(sys, '_MEIPASS', ''), "config.yaml")
        if os.path.exists(bundled):
            try:
                with open(bundled, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[ERROR] Failed to load bundled config: {e}")
    return {}


def save_config(config):
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        print(f"[ERROR] Failed to save config to {path}: {e}")
        raise


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


def _build_paper_prompt(papers, mode, lang="zh"):
    """构建不同模式的分析 prompt

    Args:
        papers: 论文列表
        mode: 分析模式 (summary/detail/compare)
        lang: 语言 (zh/en)
    """
    paper_info = []
    for i, p in enumerate(papers, 1):
        if lang == "en":
            info = f"""[Paper {i}]
Title: {p.title}
Authors: {', '.join(p.authors[:10])}
Journal: {p.journal} ({p.year})
DOI: {p.doi}  PMID: {p.pmid}  Citations: {p.citation_count}
Abstract: {p.abstract if p.abstract else 'No abstract'}
Keywords: {', '.join(p.keywords) if p.keywords else 'None'}"""
        else:
            info = f"""【论文 {i}】
标题: {p.title}
作者: {', '.join(p.authors[:10])}
期刊: {p.journal} ({p.year})
DOI: {p.doi}  PMID: {p.pmid}  被引: {p.citation_count}
摘要: {p.abstract if p.abstract else '无摘要'}
关键词: {', '.join(p.keywords) if p.keywords else '无'}"""
        paper_info.append(info)
    papers_text = "\n\n".join(paper_info)

    if lang == "en":
        fmt = """Format requirements:
- Answer in English, use plain text without Markdown symbols (# * - ` > etc.)
- Use numbered sections (1. 2. 3.), with blank lines between paragraphs
- Write professionally and concisely, as a senior professor reviewing for peers"""

        if mode == "detail":
            prompt = f"""You are a senior researcher and university professor with deep expertise in this field. Analyze the following paper in depth for fellow experts. No introductory filler — go straight to substance.

{fmt}

Analyze each paper across these dimensions:

1. Core Contribution
What does this paper actually do? What key problem does it solve? Do not repeat the title.

2. Methodology
What methods were used? What are the key experiments/algorithms/apparatus? What is methodologically novel?

3. Key Findings
What are the most important quantitative or qualitative results? Are there any surprising outcomes?

4. Academic Value and Limitations
Where does this contribution sit in the field? What are the clear limitations or debatable points?

5. Relationship to Prior Work
How does this paper compare to contemporaneous or classic work? Does it resolve open problems from previous research?

{papers_text}"""

        elif mode == "compare":
            prompt = f"""You are a senior researcher with deep expertise in this field. Provide a systematic comparative analysis of the following papers for fellow experts.

{fmt}

Analyze from these perspectives:

1. Research Approach Comparison
What are the similarities and differences in technical approaches? What are the strengths and weaknesses of each?

2. Innovation Comparison
What is the core innovation of each? Which is more groundbreaking?

3. Complementarity and Research Gaps
What complementary relationships exist between these works? Do they collectively expose unresolved problems in the field?

4. Recommendations for Future Research
What are the most noteworthy questions for continuing in this direction? Which technical approaches are more promising?

{papers_text}"""

        elif mode == "novelty":
            prompt = f"""You are a senior researcher with deep expertise in this field. Analyze the following papers and identify research gaps, unexplored directions, and opportunities for novel contributions.

{fmt}

Analyze from these perspectives:

1. Under-explored Areas
What aspects of this research topic have not been adequately studied? What questions remain unanswered?

2. Methodological Gaps
Are there methodological limitations that could be addressed with new approaches? What alternative methods could be applied?

3. Contradictions and Tensions
Are there conflicting findings or unresolved debates in the literature? What might explain these discrepancies?

4. Cross-disciplinary Opportunities
What insights from other fields could be applied to advance this research? Where do disciplinary boundaries limit progress?

5. Promising Research Directions
What are the most promising next steps? What experiments or studies would have the highest impact?

{papers_text}"""

        else:  # summary
            prompt = f"""You are a senior researcher with deep expertise in this field. Summarize the following papers with maximum conciseness.

{fmt}

For each paper, summarize in 3-5 sentences covering:
- What was done (one sentence on the core work)
- How it was done (key technology)
- What was found (core results)
- Why it matters (academic or applied value)

No pleasantries — straight to content.

{papers_text}"""

    else:  # Chinese
        fmt = """格式要求：
- 用中文回答，使用纯文本，不要用 Markdown 符号（# * - ` > 等）
- 用"一、二、三"或"1. 2. 3."编号，段落之间空一行
- 语言专业精炼，像资深教授写给同行的评审意见"""

        if mode == "detail":
            prompt = f"""你是一位在该领域有深厚造诣的资深学者和大学教授，请对以下论文进行深度解析。你的读者是同行专家，不需要科普，直接说干货。

{fmt}

请从以下维度逐篇解析：

一、核心贡献
用一两句话说清楚这篇论文到底做了什么、解决了什么关键问题。不要复述标题。

二、研究动机
为什么需要这项工作？它填补了此前研究的什么空白？

三、技术路线
用了什么方法？关键实验/算法/装置是什么？方法上有什么创新？用通俗语言解释公式和模型。

四、关键结果
最重要的定量或定性发现是什么？有没有出乎意料的结果？实验设计是否合理？

五、学术价值与局限
这篇论文的贡献在领域内处于什么水平？有什么明显的局限性或可商榷之处？

六、与本领域其他工作的关系
这篇论文和同期或经典工作相比，有什么异同？是否解决了前人遗留的问题？

七、未来方向
这项研究开启了哪些新的研究机会？

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

        elif mode == "novelty":
            prompt = f"""你是一位在该领域有深厚造诣的资深学者，请分析以下论文，识别研究空白、未探索方向和创新机会。你的读者是同行专家。

{fmt}

请从以下维度分析：

一、未充分探索的领域
这个研究主题有哪些方面还没有被充分研究？哪些关键问题仍然悬而未决？

二、方法学空白
现有方法有什么局限性？有哪些新的方法论可以尝试？技术路线上有什么可以突破的点？

三、矛盾与争议
文献中是否存在矛盾的发现或未解决的争论？这些分歧可能的原因是什么？

四、跨学科机会
其他领域有哪些思路可以借鉴来推动这项研究？学科边界在哪里限制了进展？

五、有前景的研究方向
最有价值的下一步是什么？哪些实验或研究会有最高的影响力？

{papers_text}"""

        else:  # summary
            prompt = f"""你是一位在该领域有深厚造诣的资深学者和大学教授，请用最精炼的语言总结以下论文，如同写给同行的研究笔记。

{fmt}

每篇论文用 3-5 句话概括，必须包含：
- 做了什么（一句话说清核心工作，不要复述标题）
- 怎么做的（关键技术，用通俗语言）
- 发现了什么（核心结果，尽量定量）
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
    cache_lock = threading.Lock()

    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.route("/api/search", methods=["POST"])
    def search():
        data = request.json or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "no_query"}), 400
        current_year = datetime.now().year
        max_results = min(int(data.get("max_results", 50)), 200)
        year_from = max(1900, min(int(data.get("year_from", 2020)), current_year))
        year_to = max(year_from, min(int(data.get("year_to", current_year)), current_year))
        try:
            papers = engine.search(
                query=query, year_from=year_from, year_to=year_to,
                sort=data.get("sort", "relevance"), max_results=max_results,
                use_pubmed=data.get("use_pubmed", True), use_openalex=data.get("use_openalex", True),
                use_google_scholar=data.get("use_google_scholar", False),
                use_cnki=data.get("use_cnki", False),
                use_wanfang=data.get("use_wanfang", False),
                use_vip=data.get("use_vip", False),
                use_bing_academic=data.get("use_bing_academic", False),
                journal=data.get("journal", "").strip(), field=data.get("field", "").strip(),
                mesh_term=data.get("mesh_term", "").strip(), pub_type=data.get("pub_type", "").strip(),
            )
        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            return jsonify({"error": "search_failed", "detail": str(e)}), 500
        with cache_lock:
            cached_papers["papers"] = papers
            cached_papers["query"] = query
        results = [_escape_paper(p) for p in papers]
        return jsonify({"total": len(results), "query": query, "papers": results})

    @app.route("/api/ai-search", methods=["POST"])
    def ai_search():
        if not search_ai.is_available():
            return jsonify({"error": "ai_search_not_enabled"}), 400
        data = request.json or {}
        user_input = data.get("query", "").strip()
        if not user_input:
            return jsonify({"error": "no_query"}), 400

        try:
            analysis = search_ai.analyze_query(user_input)
            current_year = datetime.now().year
            max_results = min(int(data.get("max_results", 50)), 200)
            papers = engine.search(
                query=analysis.get("query", user_input),
                year_from=analysis.get("year_from", 2020), year_to=analysis.get("year_to", current_year),
                sort="relevance", max_results=max_results,
                use_pubmed=data.get("use_pubmed", True), use_openalex=data.get("use_openalex", True),
                use_google_scholar=data.get("use_google_scholar", False),
                use_cnki=data.get("use_cnki", False),
                use_wanfang=data.get("use_wanfang", False),
                use_vip=data.get("use_vip", False),
                use_bing_academic=data.get("use_bing_academic", False),
                journal=analysis.get("journal", ""), field=analysis.get("field", ""),
                mesh_term=analysis.get("mesh_term", ""), pub_type=analysis.get("pub_type", ""),
            )
        except Exception as e:
            print(f"[ERROR] AI search failed: {e}")
            return jsonify({"error": "ai_search_failed", "detail": str(e)}), 500
        with cache_lock:
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
            return jsonify({"error": "ai_analysis_not_enabled"}), 400

        data = request.json or {}
        indices = sorted(data.get("indices", []))
        mode = data.get("mode", "summary")
        if mode not in ("summary", "detail", "compare", "novelty"):
            mode = "summary"
        force_refresh = data.get("force_refresh", False)
        use_stream = data.get("stream", False)
        lang = data.get("lang", "zh")

        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "no_papers"}), 400
        if not indices:
            return jsonify({"error": "no_selection"}), 400

        selected = [papers[i] for i in indices if 0 <= i < len(papers)]
        if not selected:
            return jsonify({"error": "invalid_selection"}), 400

        paper_ids = "_".join(sorted(set(p.doi or p.pmid or str(i) for i, p in zip(indices, selected))))
        cache_key = f"{mode}_{lang}_{paper_ids}"
        if not force_refresh and cache_key in ai_cache and ai_cache[cache_key]:
            return jsonify({"response": ai_cache[cache_key], "count": len(selected), "mode": mode, "cached": True})

        prompt = _build_paper_prompt(selected, mode, lang)
        if lang == "en":
            context = "You are a senior academic paper analysis expert. Provide precise, insightful, and concise paper analysis for fellow researchers. Automatically identify the research field and use domain-appropriate professional language."
        else:
            context = "你是一位资深学术论文分析专家，擅长用中文为同行学者提供精准、深刻、不啰嗦的论文分析。根据论文内容自动判断所属领域，用该领域的专业语言进行分析。"

        if use_stream:
            def generate():
                full_response = []
                for chunk in analysis_ai.chat_stream(prompt, context):
                    full_response.append(chunk)
                    yield chunk
                result = "".join(full_response)
                if result and not result.startswith("AI_ERROR:"):
                    ai_cache[cache_key] = result
            return Response(generate(), mimetype="text/plain; charset=utf-8",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        result = analysis_ai.chat(prompt, context)
        if result and not result.startswith("AI_ERROR:"):
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
            return jsonify({"error": "no_doi_list"}), 400

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
        with cache_lock:
            existing_dois = {p.doi.lower() for p in cached_papers["papers"] if p.doi}
            for p in found_papers:
                if p.doi and p.doi.lower() not in existing_dois:
                    cached_papers["papers"].append(p)
                    existing_dois.add(p.doi.lower())

        return jsonify({"total": len(found_escaped), "papers": found_escaped, "not_found": valid_count - len(found_escaped)})

    @app.route("/api/paper-by-doi", methods=["POST"])
    def paper_by_doi():
        """通过 DOI 获取单篇论文详情"""
        data = request.json or {}
        doi = data.get("doi", "").strip()
        if not doi:
            return jsonify({"error": "no_doi"}), 400

        paper = engine.search_by_doi(doi)
        if not paper:
            return jsonify({"error": "paper_not_found"}), 404

        # 添加到缓存（避免重复）
        with cache_lock:
            existing_dois = {p.doi.lower() for p in cached_papers["papers"] if p.doi}
            if paper.doi and paper.doi.lower() not in existing_dois:
                cached_papers["papers"].append(paper)

        return jsonify({"paper": _escape_paper(paper)})

    @app.route("/api/citation-graph", methods=["POST"])
    def citation_graph():
        """获取论文引用关系图谱数据"""
        data = request.json or {}
        doi = data.get("doi", "").strip()
        if not doi:
            return jsonify({"error": "no_doi"}), 400

        try:
            import requests as req
            # 通过 OpenAlex 获取论文引用关系
            email = config.get("sources", {}).get("openalex", {}).get("email", "")
            params = {"mailto": email} if email else {}

            # 获取论文信息
            r = req.get(f"https://api.openalex.org/works/doi:{doi}", params=params, timeout=15)
            if r.status_code != 200:
                return jsonify({"error": "paper_not_found"}), 404

            work = r.json()
            work_id = work.get("id", "")
            title = re.sub(r'<[^>]+>', '', work.get("title", "") or "").strip()
            year = work.get("publication_year", 0)
            cited_count = work.get("cited_by_count", 0)

            # 获取引用这篇论文的文献（cited_by）
            cited_by_params = {**params, "filter": f"cites:{work_id}", "per_page": 20, "sort": "cited_by_count:desc"}
            r_cited = req.get("https://api.openalex.org/works", params=cited_by_params, timeout=15)
            citing_papers = []
            if r_cited.status_code == 200:
                for w in r_cited.json().get("results", []):
                    citing_papers.append({
                        "doi": (w.get("doi", "") or "").replace("https://doi.org/", ""),
                        "title": re.sub(r'<[^>]+>', '', w.get("title", "") or "").strip(),
                        "year": w.get("publication_year", 0),
                        "citations": w.get("cited_by_count", 0),
                    })

            # 获取这篇论文引用的文献（references）
            refs = work.get("referenced_works", [])
            referenced_papers = []
            if refs:
                # 取前 20 个引用
                ref_ids = "|".join([r.split("/")[-1] for r in refs[:20]])
                ref_params = {**params, "filter": f"openalex:{ref_ids}", "per_page": 20}
                r_refs = req.get("https://api.openalex.org/works", params=ref_params, timeout=15)
                if r_refs.status_code == 200:
                    for w in r_refs.json().get("results", []):
                        referenced_papers.append({
                            "doi": (w.get("doi", "") or "").replace("https://doi.org/", ""),
                            "title": re.sub(r'<[^>]+>', '', w.get("title", "") or "").strip(),
                            "year": w.get("publication_year", 0),
                            "citations": w.get("cited_by_count", 0),
                        })

            return jsonify({
                "paper": {"doi": doi, "title": title, "year": year, "citations": cited_count},
                "citing": citing_papers,
                "referenced": referenced_papers,
            })
        except Exception as e:
            return jsonify({"error": "citation_fetch_failed", "detail": str(e)}), 500

    @app.route("/api/related-papers", methods=["POST"])
    def related_papers():
        """通过共同引用关系发现相关论文"""
        data = request.json or {}
        doi = data.get("doi", "").strip()
        if not doi:
            return jsonify({"error": "no_doi"}), 400

        try:
            import requests as req
            from collections import Counter
            email = config.get("sources", {}).get("openalex", {}).get("email", "")
            params = {"mailto": email} if email else {}

            # 获取论文信息
            r = req.get(f"https://api.openalex.org/works/doi:{doi}", params=params, timeout=15)
            if r.status_code != 200:
                return jsonify({"error": "paper_not_found"}), 404

            work = r.json()
            work_id = work.get("id", "")
            refs = work.get("referenced_works", [])
            if not refs:
                return jsonify({"papers": [], "message": "no_citation_data"})

            # 取前 8 个引用，查找同时引用这些论文的其他论文
            ref_ids = [r.split("/")[-1] for r in refs[:8]]
            candidate_counter = Counter()
            candidate_info = {}

            for ref_id in ref_ids[:6]:  # 限制 API 调用次数
                try:
                    cited_by_params = {
                        **params,
                        "filter": f"cites:{ref_id},type:article",
                        "sort": "cited_by_count:desc",
                        "per_page": 10,
                    }
                    rc = req.get("https://api.openalex.org/works", params=cited_by_params, timeout=10)
                    if rc.status_code == 200:
                        for w in rc.json().get("results", []):
                            wid = w.get("id", "")
                            if wid == work_id:
                                continue  # 排除自身
                            candidate_counter[wid] += 1
                            if wid not in candidate_info:
                                candidate_info[wid] = {
                                    "doi": (w.get("doi", "") or "").replace("https://doi.org/", ""),
                                    "title": re.sub(r'<[^>]+>', '', w.get("title", "") or "").strip(),
                                    "year": w.get("publication_year", 0),
                                    "citations": w.get("cited_by_count", 0),
                                }
                except Exception:
                    continue

            # 按共同引用数排序，取前 10
            top_related = candidate_counter.most_common(10)
            results = []
            for wid, shared_count in top_related:
                info = candidate_info.get(wid, {})
                if info.get("title"):
                    info["shared_refs"] = shared_count
                    results.append(info)

            return jsonify({"papers": results, "source_doi": doi})
        except Exception as e:
            return jsonify({"error": "related_papers_failed", "detail": str(e)}), 500

    @app.route("/api/keyword-network", methods=["POST"])
    def keyword_network():
        """关键词共现网络"""
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "no_papers_data"}), 400

        from itertools import combinations
        from collections import Counter

        keyword_count = Counter()
        cooccurrence = Counter()

        for p in papers:
            kws = [kw.strip().lower() for kw in p.keywords if kw.strip()]
            kws = list(dict.fromkeys(kws))  # 去重保序
            for kw in kws:
                keyword_count[kw] += 1
            for a, b in combinations(sorted(kws), 2):
                cooccurrence[(a, b)] += 1

        # 取出现频次 >= 2 的关键词
        top_keywords = {kw for kw, cnt in keyword_count.items() if cnt >= 2}
        if len(top_keywords) < 3:
            # 不够则取 top 20
            top_keywords = {kw for kw, _ in keyword_count.most_common(20)}

        nodes = [{"id": kw, "label": kw, "count": keyword_count[kw]}
                 for kw in top_keywords]
        links = [{"source": a, "target": b, "weight": w}
                 for (a, b), w in cooccurrence.items()
                 if a in top_keywords and b in top_keywords and w >= 1]

        return jsonify({"nodes": nodes, "links": links})

    @app.route("/api/author-network", methods=["POST"])
    def author_network():
        """作者合作网络"""
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "no_papers_data"}), 400

        from itertools import combinations
        from collections import Counter

        author_count = Counter()
        cooccurrence = Counter()

        for p in papers:
            authors = [a.strip() for a in p.authors if a.strip()]
            authors = list(dict.fromkeys(authors))  # 去重保序
            for a in authors:
                author_count[a] += 1
            for a, b in combinations(sorted(authors), 2):
                cooccurrence[(a, b)] += 1

        # 取发文 >= 2 的作者
        top_authors = {a for a, cnt in author_count.items() if cnt >= 2}
        if len(top_authors) < 3:
            top_authors = {a for a, _ in author_count.most_common(30)}

        nodes = [{"id": a, "label": a, "count": author_count[a]}
                 for a in top_authors]
        links = [{"source": a, "target": b, "weight": w}
                 for (a, b), w in cooccurrence.items()
                 if a in top_authors and b in top_authors and w >= 1]

        return jsonify({"nodes": nodes, "links": links})

    @app.route("/api/download-pdf", methods=["POST"])
    def download_pdf():
        """验证 OA 论文 PDF 链接并下载到指定目录"""
        import urllib.request
        import ipaddress
        from urllib.parse import urlparse
        data = request.json or {}
        url = data.get("url", "").strip()
        title = data.get("title", "paper")[:50]
        save_to_disk = data.get("save_to_disk", False)

        if not url:
            return jsonify({"error": "no_download_link"}), 400

        # SSRF 防护：校验协议和内网 IP
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return jsonify({"error": "invalid_url_scheme"}), 400
            hostname = parsed.hostname or ""
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return jsonify({"error": "blocked_internal_url"}), 403
            except ValueError:
                # hostname 不是 IP，是域名，允许通过
                pass
        except Exception:
            return jsonify({"error": "invalid_url"}), 400

        safe_title = re.sub(r'[^\w\-]', '_', title).strip('_') or "paper"
        filename = f"{safe_title}.pdf"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-7"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                header = resp.read(8)
                if not header.startswith(b'%PDF'):
                    return jsonify({"error": "not_pdf"}), 400

            if save_to_disk:
                export_dir = load_config().get("export_path", "")
                if not export_dir:
                    return jsonify({"error": "no_export_path", "filename": filename, "url": url})
                try:
                    os.makedirs(export_dir, exist_ok=True)
                    filepath = os.path.join(export_dir, filename)
                    urllib.request.urlretrieve(url, filepath)
                    return jsonify({"ok": True, "path": filepath, "filename": filename})
                except Exception as e:
                    return jsonify({"error": "download_failed", "detail": str(e)}), 500

            return jsonify({"filename": filename, "url": url})
        except Exception as e:
            return jsonify({"error": "link_verify_failed", "detail": str(e)}), 500

    @app.route("/api/reading-history", methods=["POST"])
    def save_reading_history():
        """记录用户阅读行为（点击、查看摘要、下载等）"""
        data = request.json or {}
        action = data.get("action", "")  # view, abstract, download, cite
        paper = data.get("paper", {})
        if not paper.get("doi") and not paper.get("title"):
            return jsonify({"error": "missing_paper_info"}), 400

        path = _get_user_data_path("reading_history.json")
        history = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        # 添加记录
        record = {
            "action": action,
            "timestamp": datetime.now().isoformat(),
            "doi": paper.get("doi", ""),
            "title": paper.get("title", ""),
            "journal": paper.get("journal", ""),
            "year": paper.get("year", 0),
            "authors": paper.get("authors", []),
            "keywords": paper.get("keywords", []),
            "abstract": paper.get("abstract", "")[:500],  # 只保存前500字符
        }
        history.append(record)

        # 只保留最近500条记录
        history = history[-500:]

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/recommendations", methods=["GET"])
    def get_recommendations():
        """基于阅读历史推荐论文"""
        path = _get_user_data_path("reading_history.json")
        if not os.path.exists(path):
            return jsonify({"papers": [], "keywords": []})

        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            return jsonify({"papers": [], "keywords": []})

        if not history:
            return jsonify({"papers": [], "keywords": []})

        # 分析阅读历史，提取关键词和主题
        from collections import Counter
        keyword_counter = Counter()
        journal_counter = Counter()
        recent_dois = set()

        for record in history[-100:]:  # 分析最近100条记录
            # 统计关键词
            for kw in record.get("keywords", []):
                if kw:
                    keyword_counter[kw.lower()] += 1

            # 统计期刊
            journal = record.get("journal", "")
            if journal:
                journal_counter[journal] += 1

            # 记录最近查看的DOI
            doi = record.get("doi", "")
            if doi:
                recent_dois.add(doi.lower())

        # 提取Top关键词
        top_keywords = [kw for kw, _ in keyword_counter.most_common(10)]
        top_journals = [j for j, _ in journal_counter.most_common(5)]

        if not top_keywords and not top_journals:
            return jsonify({"papers": [], "keywords": []})

        # 构建推荐查询
        # 策略1：基于高频关键词
        # 策略2：基于高频期刊
        # 策略3：结合关键词和期刊

        recommended_papers = []

        # 策略1：基于关键词推荐
        if top_keywords:
            query = " OR ".join(top_keywords[:5])
            try:
                papers = engine.search(
                    query=query,
                    year_from=datetime.now().year - 2,  # 最近2年
                    year_to=datetime.now().year,
                    sort="citations",
                    max_results=20,
                    use_pubmed=True,
                    use_openalex=True,
                )
                # 过滤掉已经看过的论文
                for p in papers:
                    if p.doi and p.doi.lower() not in recent_dois:
                        recommended_papers.append(p)
            except Exception as e:
                print(f"Recommendation search error: {e}")

        # 策略2：基于期刊推荐（如果关键词推荐不够）
        if len(recommended_papers) < 10 and top_journals:
            for journal in top_journals[:2]:
                try:
                    # 用关键词作为查询，结合期刊过滤
                    journal_query = " OR ".join(top_keywords[:3]) if top_keywords else "research"
                    papers = engine.search(
                        query=journal_query,
                        year_from=datetime.now().year - 1,
                        year_to=datetime.now().year,
                        sort="citations",
                        max_results=10,
                        use_pubmed=True,
                        use_openalex=True,
                        journal=journal,
                    )
                    for p in papers:
                        if p.doi and p.doi.lower() not in recent_dois:
                            # 检查是否已经存在
                            if not any(r.doi == p.doi for r in recommended_papers):
                                recommended_papers.append(p)
                except Exception:
                    continue

        # 限制推荐数量
        recommended_papers = recommended_papers[:15]

        # 转换为前端格式
        results = [_escape_paper(p) for p in recommended_papers]

        return jsonify({
            "papers": results,
            "keywords": top_keywords,
            "journals": top_journals,
            "total": len(results),
        })

    @app.route("/api/reading-history", methods=["GET"])
    def get_reading_history():
        """获取阅读历史统计"""
        path = _get_user_data_path("reading_history.json")
        if not os.path.exists(path):
            return jsonify({"total": 0, "keywords": [], "journals": []})

        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            return jsonify({"total": 0, "keywords": [], "journals": []})

        from collections import Counter
        keyword_counter = Counter()
        journal_counter = Counter()

        for record in history:
            for kw in record.get("keywords", []):
                if kw:
                    keyword_counter[kw.lower()] += 1
            journal = record.get("journal", "")
            if journal:
                journal_counter[journal] += 1

        return jsonify({
            "total": len(history),
            "keywords": [kw for kw, _ in keyword_counter.most_common(20)],
            "journals": [j for j, _ in journal_counter.most_common(10)],
        })

    @app.route("/api/export", methods=["POST"])
    def export():
        data = request.json or {}
        fmt = data.get("format", "ris")
        indices = data.get("indices", [])
        save_to_disk = data.get("save_to_disk", False)
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "no_export_data"}), 400
        selected = [papers[i] for i in indices if 0 <= i < len(papers)] if indices else papers
        safe_q = re.sub(r'[^\w\-]', '_', cached_papers['query'][:40]).strip('_') or "results"
        if fmt == "ris":
            content, filename, mime = export_ris(selected), f"lit_search_{safe_q}.ris", "application/x-research-info-systems"
        elif fmt == "bibtex":
            content, filename, mime = export_bibtex(selected), f"lit_search_{safe_q}.bib", "application/x-bibtex"
        elif fmt == "csv":
            content, filename, mime = export_csv(selected), f"lit_search_{safe_q}.csv", "text/csv"
        elif fmt == "endnotexml":
            content, filename, mime = export_endnote_xml(selected), f"lit_search_{safe_q}.xml", "application/xml"
        else:
            return jsonify({"error": "unsupported_format", "format": fmt}), 400

        if save_to_disk:
            export_dir = load_config().get("export_path", "")
            if not export_dir:
                return jsonify({"error": "no_export_path", "content": content, "filename": filename, "mime": mime})
            try:
                os.makedirs(export_dir, exist_ok=True)
                filepath = os.path.join(export_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                return jsonify({"ok": True, "path": filepath, "filename": filename})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        return jsonify({"content": content, "filename": filename, "mime": mime})

    @app.route("/api/collections", methods=["GET"])
    def get_collections():
        """获取所有收藏"""
        path = _get_user_data_path("collections.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception as e:
                print(f"[WARN] Failed to read collections.json: {e}")
        return jsonify({"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []})

    @app.route("/api/collections", methods=["POST"])
    def add_collection():
        """添加收藏"""
        data = request.json or {}
        paper = data.get("paper")
        group_id = data.get("group_id", "default")
        if not paper or not paper.get("doi"):
            return jsonify({"error": "missing_paper_info"}), 400

        path = _get_user_data_path("collections.json")
        collections = {"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    collections = json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to read collections.json for add: {e}")
                return jsonify({"error": "collection_read_failed"}), 500

        # 检查是否已收藏
        doi = paper.get("doi", "").lower()
        for item in collections.get("items", []):
            if item.get("doi", "").lower() == doi and item.get("group_id") == group_id:
                return jsonify({"ok": True, "message": "已收藏"})

        collections.setdefault("items", []).append({
            "doi": paper.get("doi", ""),
            "title": paper.get("title", ""),
            "authors": paper.get("authors", []),
            "journal": paper.get("journal", ""),
            "year": paper.get("year", 0),
            "citation_count": paper.get("citation_count", 0),
            "oa_url": paper.get("oa_url", ""),
            "pmid": paper.get("pmid", ""),
            "abstract": paper.get("abstract", ""),
            "group_id": group_id,
            "added_at": datetime.now().isoformat(),
        })

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/collections", methods=["DELETE"])
    def remove_collection():
        """删除收藏"""
        data = request.json or {}
        doi = data.get("doi", "").lower()
        group_id = data.get("group_id", "default")
        if not doi:
            return jsonify({"error": "no_doi"}), 400

        path = _get_user_data_path("collections.json")
        if not os.path.exists(path):
            return jsonify({"ok": True})

        try:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
            collections["items"] = [
                item for item in collections.get("items", [])
                if not (item.get("doi", "").lower() == doi and item.get("group_id") == group_id)
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/collections/groups", methods=["POST"])
    def save_collection_groups():
        """保存收藏夹分组"""
        data = request.json or {}
        groups = data.get("groups", [])
        path = _get_user_data_path("collections.json")
        collections = {"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    collections = json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to read collections.json for group save: {e}")
                return jsonify({"error": "collection_read_failed"}), 500
        collections["groups"] = groups
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/collections/groups", methods=["DELETE"])
    def delete_collection_group():
        """删除收藏夹及其所有收藏"""
        data = request.json or {}
        group_id = data.get("group_id", "")
        if not group_id or group_id == "default":
            return jsonify({"error": "cannot_delete_default"}), 400

        path = _get_user_data_path("collections.json")
        if not os.path.exists(path):
            return jsonify({"ok": True})

        try:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)

            # 删除该收藏夹
            collections["groups"] = [
                g for g in collections.get("groups", [])
                if g.get("id") != group_id
            ]

            # 删除该收藏夹下的所有收藏
            collections["items"] = [
                item for item in collections.get("items", [])
                if item.get("group_id") != group_id
            ]

            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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
        try:
            cfg = load_config()
            _deep_update(cfg, data)
            save_config(cfg)
            nonlocal engine, search_ai, analysis_ai
            engine = SearchEngine(cfg)
            search_ai = SearchAI(cfg)
            analysis_ai = AnalysisAI(cfg)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Config update failed: {e}")
            return jsonify({"error": "config_save_failed", "detail": str(e)}), 500

    @app.route("/api/ai/chat", methods=["POST"])
    def ai_chat():
        if not analysis_ai.is_available():
            return jsonify({"error": "ai_analysis_not_enabled"}), 400
        data = request.json or {}
        try:
            return jsonify({"response": analysis_ai.chat(data.get("message", ""), data.get("context", ""))})
        except Exception as e:
            print(f"[ERROR] AI chat failed: {e}")
            return jsonify({"error": "request_failed", "detail": str(e)}), 500

    @app.route("/api/ai/summarize", methods=["POST"])
    def ai_summarize():
        if not analysis_ai.is_available():
            return jsonify({"error": "ai_analysis_not_enabled"}), 400
        papers = cached_papers["papers"]
        if not papers:
            return jsonify({"error": "no_papers"}), 400
        try:
            return jsonify({"response": analysis_ai.summarize(papers)})
        except Exception as e:
            print(f"[ERROR] AI summarize failed: {e}")
            return jsonify({"error": "request_failed", "detail": str(e)}), 500

    @app.route("/api/zotero/test", methods=["POST"])
    def zotero_test():
        """测试 Zotero API 连接"""
        data = request.json or {}
        api_key = data.get("api_key", "").strip()
        user_id = data.get("user_id", "").strip()
        if not api_key or not user_id:
            return jsonify({"error": "missing_zotero_config"}), 400

        try:
            import requests as req
            headers = {"Zotero-API-Key": api_key}
            r = req.get(f"https://api.zotero.org/users/{user_id}/collections?limit=1",
                       headers=headers, timeout=10)
            if r.status_code == 200:
                return jsonify({"ok": True})
            elif r.status_code == 403:
                return jsonify({"error": "zotero_auth_failed"}), 403
            else:
                return jsonify({"error": "zotero_connection_failed", "status": r.status_code}), 400
        except Exception as e:
            return jsonify({"error": "zotero_connection_failed", "detail": str(e)}), 500

    @app.route("/api/zotero/collections", methods=["POST"])
    def zotero_get_collections():
        """获取用户的 Zotero 收藏夹列表"""
        data = request.json or {}
        api_key = data.get("api_key", "").strip()
        user_id = data.get("user_id", "").strip()
        if not api_key or not user_id:
            return jsonify({"error": "missing_zotero_config"}), 400

        try:
            import requests as req
            headers = {"Zotero-API-Key": api_key}
            r = req.get(f"https://api.zotero.org/users/{user_id}/collections?limit=100&sort=title",
                       headers=headers, timeout=15)
            if r.status_code != 200:
                return jsonify({"error": "zotero_fetch_failed"}), 400

            collections = []
            for col in r.json():
                data_col = col.get("data", {})
                collections.append({
                    "key": data_col.get("key", ""),
                    "name": data_col.get("name", ""),
                    "parentCollection": data_col.get("parentCollection", ""),
                    "numItems": col.get("meta", {}).get("numItems", 0),
                })

            return jsonify({"collections": collections})
        except Exception as e:
            return jsonify({"error": "zotero_fetch_failed", "detail": str(e)}), 500

    @app.route("/api/zotero/sync", methods=["POST"])
    def zotero_sync():
        """将论文同步到 Zotero"""
        data = request.json or {}
        api_key = data.get("api_key", "").strip()
        user_id = data.get("user_id", "").strip()
        collection_key = data.get("collection_key", "").strip()
        papers = data.get("papers", [])

        if not api_key or not user_id:
            return jsonify({"error": "missing_zotero_config"}), 400
        if not papers:
            return jsonify({"error": "no_papers"}), 400

        try:
            import requests as req
            headers = {
                "Zotero-API-Key": api_key,
                "Content-Type": "application/json",
            }

            # 构建 Zotero items
            items = []
            for p in papers[:50]:  # 限制每次最多50篇
                item = {
                    "itemType": "journalArticle",
                    "title": p.get("title", ""),
                    "creators": [
                        {"creatorType": "author", "name": author}
                        for author in p.get("authors", [])[:10]
                    ],
                    "publicationTitle": p.get("journal", ""),
                    "date": str(p.get("year", "")),
                    "DOI": p.get("doi", ""),
                    "abstractNote": p.get("abstract", ""),
                    "tags": [
                        {"tag": kw} for kw in p.get("keywords", [])[:5]
                    ],
                }
                if collection_key:
                    item["collections"] = [collection_key]
                items.append(item)

            # 批量创建 items
            r = req.post(
                f"https://api.zotero.org/users/{user_id}/items",
                headers=headers,
                json=items,
                timeout=30,
            )

            # Zotero API 返回 200 成功，409 表示部分冲突（重复项）
            if r.status_code in (200, 201, 409):
                result = r.json()
                successful = len(result.get("successful", []))
                failed = len(result.get("failed", []))
                # 409 时 successful 中仍包含已存在的项，算作成功
                return jsonify({
                    "ok": True,
                    "successful": successful,
                    "failed": failed,
                    "total": len(items),
                })
            else:
                return jsonify({"error": "zotero_sync_failed", "status": r.status_code}), 400
        except Exception as e:
            return jsonify({"error": "zotero_sync_failed", "detail": str(e)}), 500

    @app.route("/api/zotero/config", methods=["GET"])
    def zotero_get_config():
        """获取 Zotero 配置"""
        path = _get_user_data_path("zotero_config.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({"api_key": "", "user_id": ""})

    @app.route("/api/zotero/config", methods=["POST"])
    def zotero_save_config():
        """保存 Zotero 配置"""
        data = request.json or {}
        path = _get_user_data_path("zotero_config.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "api_key": data.get("api_key", ""),
                    "user_id": data.get("user_id", ""),
                }, f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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
