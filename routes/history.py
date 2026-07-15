"""History and recommendations routes for PaperLens"""

import os
import json
import re
from datetime import datetime
from collections import Counter
from flask import Blueprint, request, jsonify, current_app
from core.config import load_config
from core.utils import _get_user_data_path, _escape_paper
from search_engine import Paper

history_bp = Blueprint('history', __name__)


def _state():
    return current_app.config["APP_STATE"]


@history_bp.route("/api/history", methods=["GET"])
def get_history():
    state = _state()
    path = _get_user_data_path("history.json")
    with state.history_lock:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception as e:
                print(f"[WARN] Failed to read history.json: {e}")
    return jsonify([])


@history_bp.route("/api/history", methods=["POST"])
def save_history():
    state = _state()
    data = request.json or []
    if not isinstance(data, list):
        return jsonify({"error": "invalid_data"}), 400
    path = _get_user_data_path("history.json")
    with state.history_lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data[:30], f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@history_bp.route("/api/preferences", methods=["GET"])
def get_preferences():
    state = _state()
    path = _get_user_data_path("preferences.json")
    with state.preferences_lock:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception as e:
                print(f"[ERROR] Failed to read preferences.json: {e}")
    return jsonify({})


@history_bp.route("/api/preferences", methods=["POST"])
def save_preferences():
    state = _state()
    data = request.json or {}
    path = _get_user_data_path("preferences.json")
    with state.preferences_lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@history_bp.route("/api/reading-history", methods=["POST"])
def save_reading_history():
    """记录用户阅读行为（点击、查看摘要、下载等）"""
    state = _state()
    data = request.json or {}
    action = data.get("action", "")  # view, abstract, download, cite
    paper = data.get("paper", {})
    if not paper.get("doi") and not paper.get("title"):
        return jsonify({"error": "missing_paper_info"}), 400

    path = _get_user_data_path("reading_history.json")
    with state.history_lock:
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
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@history_bp.route("/api/recommendations", methods=["GET"])
def get_recommendations():
    """基于阅读历史推荐论文"""
    state = _state()
    lang = request.args.get("lang", "zh")
    path = _get_user_data_path("reading_history.json")
    with state.history_lock:
        if not os.path.exists(path):
            return jsonify({"papers": [], "keywords": []})

        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            return jsonify({"papers": [], "keywords": []})

    if not history:
        return jsonify({"papers": [], "keywords": []})

    # 判断是否包含中文字符
    def has_chinese(text):
        return any('一' <= c <= '鿿' for c in text)

    # 分析阅读历史，提取关键词和主题
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

    # 双向语言过滤：英文模式过滤中文关键词，中文模式过滤纯英文关键词
    if lang == "en":
        top_keywords = [kw for kw in top_keywords if not has_chinese(kw)]
    elif lang == "zh":
        top_keywords = [kw for kw in top_keywords if has_chinese(kw) or not kw.isascii()]

    if not top_keywords and not top_journals:
        return jsonify({"papers": [], "keywords": []})

    # 构建推荐查询
    # 策略1：基于高频关键词（深耕性推荐）
    # 策略2：基于高频期刊
    # 策略3：基于引用关系（探索性推荐）

    recommended_papers = []
    recommendation_types = set()  # 跟踪实际使用的推荐策略

    # 策略1：基于关键词推荐（深耕性：与已读内容相似）
    if top_keywords:
        query = " OR ".join(top_keywords[:5])
        try:
            papers, _ = state.engine.search(
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
            if recommended_papers:
                recommendation_types.add("keyword")
        except Exception as e:
            print(f"Recommendation search error: {e}")

    # 策略2：基于期刊推荐
    if len(recommended_papers) < 10 and top_journals:
        for journal in top_journals[:2]:
            try:
                journal_query = " OR ".join(top_keywords[:3]) if top_keywords else "research"
                papers, _ = state.engine.search(
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
                        if not any(r.doi == p.doi for r in recommended_papers):
                            recommended_papers.append(p)
                if recommended_papers:
                    recommendation_types.add("journal")
            except Exception:
                continue

    # 策略3：基于引用关系（探索性推荐）
    # 从收藏的论文中找引用关系（始终执行，补充跨领域发现）
    s3_count_before = len(recommended_papers)
    if len(recommended_papers) < 20:
        try:
            collections_path = _get_user_data_path("collections.json")
            if os.path.exists(collections_path):
                with state.collections_lock:
                    with open(collections_path, "r", encoding="utf-8") as f:
                        collections = json.load(f)
                # 取收藏中最近的论文 DOI
                collection_dois = [item.get("doi") for item in collections.get("items", []) if item.get("doi")][-5:]
                for doi in collection_dois[:3]:
                    try:
                        import requests as req
                        with state.cache_lock:
                            email = state.config.get("sources", {}).get("openalex", {}).get("email", "")
                            api_key = state.config.get("sources", {}).get("openalex", {}).get("api_key", "")
                        params = {}
                        if email:
                            params["mailto"] = email
                        if api_key:
                            params["api_key"] = api_key
                        r = req.get(f"https://api.openalex.org/works/doi:{doi}", params=params, timeout=10)
                        if r.status_code == 200:
                            work = r.json()
                            refs = work.get("referenced_works", [])
                            if refs:
                                # 取引用文献的前5个
                                ref_ids = ",".join([rid.split("/")[-1] for rid in refs[:5]])
                                ref_params = {**params, "filter": f"openalex:{ref_ids}", "per_page": 5}
                                r_refs = req.get("https://api.openalex.org/works", params=ref_params, timeout=10)
                                if r_refs.status_code == 200:
                                    for w in r_refs.json().get("results", []):
                                        oa_doi = (w.get("doi", "") or "").replace("https://doi.org/", "")
                                        if oa_doi and oa_doi.lower() not in recent_dois:
                                            if not any(r.doi == oa_doi for r in recommended_papers):
                                                p = Paper(source="openalex")
                                                p.title = re.sub(r'<[^>]+>', '', w.get("title", "") or "")
                                                p.doi = oa_doi
                                                p.year = w.get("publication_year", 0)
                                                p.citation_count = w.get("cited_by_count", 0)
                                                loc = w.get("primary_location") or {}
                                                src = loc.get("source") or {}
                                                p.journal = src.get("display_name", "") or ""
                                                # 补全学术字段
                                                biblio = w.get("biblio") or {}
                                                p.volume = str(biblio.get("volume", "") or "")
                                                p.issue = str(biblio.get("issue", "") or "")
                                                fp = str(biblio.get("first_page", "") or "")
                                                lp = str(biblio.get("last_page", "") or "")
                                                if fp:
                                                    p.pages = fp if not lp or fp == lp else f"{fp}-{lp}"
                                                issn_raw = src.get("issn", "") or ""
                                                p.issn = issn_raw[0] if isinstance(issn_raw, list) and issn_raw else str(issn_raw)
                                                # 摘要（OpenAlex 反转索引格式）
                                                abstract_inv = w.get("abstract_inverted_index")
                                                if abstract_inv:
                                                    try:
                                                        positions = []
                                                        for word, pos_list in abstract_inv.items():
                                                            for pos in pos_list:
                                                                positions.append((pos, word))
                                                        positions.sort()
                                                        p.abstract = " ".join(w for _, w in positions)
                                                    except Exception:
                                                        pass
                                                for author in w.get("authorships", []):
                                                    name = author.get("author", {}).get("display_name", "")
                                                    if name:
                                                        p.authors.append(name)
                                                for kw in w.get("keywords", []):
                                                    if isinstance(kw, dict):
                                                        kw = kw.get("display_name", "")
                                                    if isinstance(kw, str) and kw:
                                                        p.keywords.append(kw)
                                                recommended_papers.append(p)
                    except Exception:
                        continue
        except Exception:
            pass

    # 标记策略3贡献（仅在策略3实际添加了论文时）
    if len(recommended_papers) > s3_count_before:
        recommendation_types.add("citation")

    # 英文模式下过滤掉中文标题的论文
    if lang == "en":
        recommended_papers = [p for p in recommended_papers if p.title and not has_chinese(p.title)]

    # 限制推荐数量
    recommended_papers = recommended_papers[:15]

    # 确定推荐类型标签
    if recommendation_types == {"citation"}:
        rec_type = "citation"
    elif "citation" in recommendation_types:
        rec_type = "mixed"
    elif "journal" in recommendation_types:
        rec_type = "journal"
    else:
        rec_type = "keyword"

    # 转换为前端格式
    results = [_escape_paper(p) for p in recommended_papers]

    return jsonify({
        "papers": results,
        "keywords": top_keywords,
        "journals": top_journals,
        "total": len(results),
        "recommendation_type": rec_type,
    })


@history_bp.route("/api/reading-history", methods=["GET"])
def get_reading_history():
    """获取阅读历史统计"""
    state = _state()
    path = _get_user_data_path("reading_history.json")
    with state.history_lock:
        if not os.path.exists(path):
            return jsonify({"total": 0, "keywords": [], "journals": []})

        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            return jsonify({"total": 0, "keywords": [], "journals": []})

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
