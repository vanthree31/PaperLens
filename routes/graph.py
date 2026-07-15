"""Citation graph and network routes for PaperLens"""

import re
import time
from itertools import combinations
from collections import Counter
from flask import Blueprint, request, jsonify, current_app

graph_bp = Blueprint('graph', __name__)

# 引用图谱缓存（内存，24小时过期）
CITATION_CACHE_TTL = 24 * 3600  # 24小时


def _state():
    return current_app.config["APP_STATE"]


@graph_bp.route("/api/citation-graph", methods=["POST"])
def citation_graph():
    """获取论文引用关系图谱数据"""
    state = _state()
    data = request.json or {}
    doi = data.get("doi", "").strip()
    if not doi:
        return jsonify({"error": "no_doi"}), 400

    # 检查缓存
    now = time.time()
    doi_lower = doi.lower()
    with state.citation_lock:
        if doi_lower in state.citation_cache:
            cached = state.citation_cache[doi_lower]
            if now - cached["timestamp"] < CITATION_CACHE_TTL:
                return jsonify(cached["data"])

    try:
        import requests as req
        # 通过 OpenAlex 获取论文引用关系
        with state.cache_lock:
            email = state.config.get("sources", {}).get("openalex", {}).get("email", "")
            api_key = state.config.get("sources", {}).get("openalex", {}).get("api_key", "")
        params = {}
        if email:
            params["mailto"] = email
        if api_key:
            params["api_key"] = api_key

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
        cited_by_params = {**params, "filter": f"cites:{work_id}", "per_page": 30, "sort": "cited_by_count:desc"}
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
            ref_ids = ",".join([r.split("/")[-1] for r in refs[:30]])
            ref_params = {**params, "filter": f"openalex:{ref_ids}", "per_page": 30}
            r_refs = req.get("https://api.openalex.org/works", params=ref_params, timeout=15)
            if r_refs.status_code == 200:
                for w in r_refs.json().get("results", []):
                    referenced_papers.append({
                        "doi": (w.get("doi", "") or "").replace("https://doi.org/", ""),
                        "title": re.sub(r'<[^>]+>', '', w.get("title", "") or "").strip(),
                        "year": w.get("publication_year", 0),
                        "citations": w.get("cited_by_count", 0),
                    })

        result = {
            "paper": {"doi": doi, "title": title, "year": year, "citations": cited_count},
            "citing": citing_papers,
            "referenced": referenced_papers,
        }

        # 保存到缓存
        with state.citation_lock:
            state.citation_cache[doi_lower] = {"data": result, "timestamp": now}
            # 清理过期缓存
            if len(state.citation_cache) > 200:
                expired = [k for k, v in state.citation_cache.items() if now - v["timestamp"] > CITATION_CACHE_TTL]
                for k in expired:
                    del state.citation_cache[k]

        return jsonify(result)
    except Exception as e:
        print(f"[ERROR] Citation fetch failed: {e}")
        return jsonify({"error": "citation_fetch_failed"}), 500


@graph_bp.route("/api/related-papers", methods=["POST"])
def related_papers():
    """通过共同引用关系发现相关论文"""
    state = _state()
    data = request.json or {}
    doi = data.get("doi", "").strip()
    if not doi:
        return jsonify({"error": "no_doi"}), 400

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
        print(f"[ERROR] Related papers failed: {e}")
        return jsonify({"error": "related_papers_failed"}), 500


@graph_bp.route("/api/keyword-network", methods=["POST"])
def keyword_network():
    """关键词共现网络"""
    state = _state()
    with state.cache_lock:
        papers = list(state.cached_papers["papers"])
    if not papers:
        return jsonify({"error": "no_papers_data"}), 400

    keyword_count = Counter()
    cooccurrence = Counter()

    for p in papers:
        kws = [kw.strip().lower() for kw in (p.get("keywords", []) if isinstance(p, dict) else getattr(p, 'keywords', [])) if kw.strip()]
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


@graph_bp.route("/api/author-network", methods=["POST"])
def author_network():
    """作者合作网络"""
    state = _state()
    with state.cache_lock:
        papers = list(state.cached_papers["papers"])
    if not papers:
        return jsonify({"error": "no_papers_data"}), 400

    author_count = Counter()
    cooccurrence = Counter()

    for p in papers:
        authors = [a.strip() for a in (p.get("authors", []) if isinstance(p, dict) else getattr(p, 'authors', [])) if a.strip()]
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
