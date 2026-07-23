"""跨源 DOI 去重模块

搜索结果返回后、前端渲染前执行去重。
以 DOI 为主键合并同一论文的多源数据，无 DOI 的论文按标题归一化去重。
第二阶段：检测预印本↔正式版关系，保留高引用版本并标记关联版本。

关键约束：
- 使用 dataclasses.replace() 创建新对象，不修改原始 cached_papers 引用
- _normalize_title 使用显式 Unicode 范围处理中文去重
- 版本关系检测仅在 DOI/标题去重之后执行，避免干扰主去重逻辑
"""

import re
from dataclasses import replace
from difflib import SequenceMatcher


def deduplicate_papers(papers: list) -> list:
    """
    跨源 DOI 去重：以 DOI 为主键合并同一论文的多源数据。
    无 DOI 的论文按 title 归一化后去重。
    第二阶段：检测预印本/正式版关系，保留高引用版本并标记关联版本。

    Args:
        papers: Paper 对象列表

    Returns:
        去重后的 Paper 对象列表（新对象，不修改原列表元素）
    """
    if not papers:
        return []

    doi_map = {}  # doi_lower -> merged paper
    title_map = {}  # normalized_title -> merged paper (仅无 DOI 论文)

    for p in papers:
        doi_key = (p.doi or "").strip().lower()
        title_key = _normalize_title(p.title)

        if doi_key:
            if doi_key in doi_map:
                doi_map[doi_key] = _merge_paper(doi_map[doi_key], p)
            else:
                # 创建新对象，不修改原引用
                doi_map[doi_key] = replace(p)
        elif title_key:
            if title_key in title_map:
                title_map[title_key] = _merge_paper(title_map[title_key], p)
            else:
                title_map[title_key] = replace(p)
        else:
            # 无 DOI 无标题，保留原样（用唯一 key 避免碰撞）
            title_map[f"_no_id_{len(title_map)}"] = replace(p)

    # 合并去重：先 DOI 去重的结果，再标题去重的结果
    all_papers = list(doi_map.values()) + list(title_map.values())

    # 第二阶段：检测预印本↔正式版关系
    all_papers = _detect_version_relations(all_papers)

    return all_papers


def _detect_version_relations(papers: list) -> list:
    """
    检测预印本↔正式版版本关系。

    策略：遍历非预印本论文，对每篇查找所有匹配的预印本（标题相似度 >= 0.85）。
    匹配成功时保留引用更高的版本，抑制所有匹配预印本，并标记关联DOI。

    Returns:
        处理后的论文列表（预印本被抑制时从列表移除）
    """
    if len(papers) < 2:
        return papers

    suppressed = set()
    title_cache = {}  # paper id -> normalized title

    def _get_title_key(p):
        pid = id(p)
        if pid not in title_cache:
            title_cache[pid] = _normalize_title_for_version(p.title)
        return title_cache[pid]

    # 为每篇非预印本查找所有匹配的预印本
    for pub_paper in papers:
        if pub_paper.doi and _is_preprint_doi(pub_paper.doi):
            continue
        if id(pub_paper) in suppressed:
            continue

        pub_title = _get_title_key(pub_paper)
        if not pub_title:
            continue

        matches = _find_all_preprint_matches(pub_paper, papers, title_cache)
        if not matches:
            continue

        # 收集所有匹配预印本中引用最高的
        best_preprint = max(matches, key=lambda m: getattr(m, "citation_count", 0) or 0)

        # 保留引用更高的版本
        pub_cites = getattr(pub_paper, "citation_count", 0) or 0
        pre_cites = getattr(best_preprint, "citation_count", 0) or 0

        if pub_cites >= pre_cites:
            kept = pub_paper
        else:
            kept = best_preprint

        # 标记所有匹配预印本为关联版本，抑制非保留的
        kept_rel = list(kept.related_versions or [])
        for preprint in matches:
            if id(preprint) == id(kept):
                continue
            sup_doi = (preprint.doi or "").strip().lower()
            if sup_doi and sup_doi not in kept_rel:
                kept_rel.append(sup_doi)
            suppressed.add(id(preprint))

        # 如果正式版被抑制（预印本引用更高），也将正式版标记为关联版本
        if id(pub_paper) != id(kept):
            pub_doi = (pub_paper.doi or "").strip().lower()
            if pub_doi and pub_doi not in kept_rel:
                kept_rel.append(pub_doi)
            suppressed.add(id(pub_paper))

        kept.related_versions = kept_rel

    return [p for p in papers if id(p) not in suppressed]


def _is_preprint_doi(doi: str) -> bool:
    """检测 DOI 是否为预印本（arXiv 等）。

    常见 arXiv DOI 前缀：
    - 10.48550/arXiv.xxxx  (标准 arXiv DOI)
    - 10.1088/xxxx        (部分 IOP 期刊预印本)
    """
    if not doi:
        return False
    doi_lower = doi.strip().lower()
    return doi_lower.startswith("10.48550/arxiv.")


def _title_similarity(title1: str, title2: str) -> float:
    """计算两个标题的相似度（0-1）。

    对标题进行预印本后缀剥离后再比较，避免因 '(arXiv version)' 等常见后缀
    导致相似度偏低。
    """
    if not title1 or not title2:
        return 0.0
    norm1 = _normalize_title_for_version(title1)
    norm2 = _normalize_title_for_version(title2)
    if not norm1 or not norm2:
        return 0.0
    return SequenceMatcher(None, norm1, norm2).ratio()


def _find_all_preprint_matches(published, papers, title_cache):
    """为已发表论文查找所有预印本匹配。

    Args:
        published: 已发表论文
        papers: 全部论文列表
        title_cache: 标题缓存 {paper_id: normalized_title}

    Returns:
        匹配的预印本列表（可能为空）
    """
    pub_title = title_cache.get(id(published)) or _normalize_title_for_version(
        published.title
    )
    if not pub_title:
        return []

    matches = []
    for candidate in papers:
        if id(candidate) == id(published):
            continue
        if not candidate.doi or not _is_preprint_doi(candidate.doi):
            continue

        cand_title = title_cache.get(id(candidate)) or _normalize_title_for_version(
            candidate.title
        )
        if not cand_title:
            continue

        sim = SequenceMatcher(None, pub_title, cand_title).ratio()
        if sim >= 0.85:
            matches.append(candidate)

    return matches


def _merge_paper(existing, new):
    """
    合并两篇同一论文的数据（dataclass.replace 保证不修改原对象）。
    规则：取更完整的值（非空覆盖空），列表取并集，数值取最大。
    """
    # sources 标记
    existing_sources = list(set(existing.sources or []))
    new_sources = list(set(new.sources or []))
    if not existing_sources and existing.source:
        existing_sources = [existing.source]
    if not new_sources and new.source:
        new_sources = [new.source]

    # 取非空字符串（新值优先，因为更新的数据源可能有更准确的信息）
    merged = {}
    for fld in (
        "title",
        "journal",
        "doi",
        "pmid",
        "orcid",
        "article_type",
        "conference",
        "abstract",
    ):
        old_val = getattr(existing, fld, "")
        new_val = getattr(new, fld, "")
        if new_val and (not old_val or len(new_val) > len(old_val)):
            merged[fld] = new_val
        else:
            merged[fld] = old_val

    # 年份：取非零值
    merged["year"] = (
        new.year if (new.year and new.year != existing.year) else existing.year
    )

    # 引用数：取较大值
    merged["citation_count"] = max(
        getattr(existing, "citation_count", 0) or 0,
        getattr(new, "citation_count", 0) or 0,
    )

    # 其他字段：保留已有值
    for fld in ("volume", "issue", "pages", "issn", "oa_url"):
        merged[fld] = getattr(existing, fld, "") or getattr(new, fld, "")

    # 列表字段：取并集，保持顺序
    for fld in ("authors", "keywords", "funding", "related_versions"):
        old_list = list(getattr(existing, fld, []) or [])
        new_list = list(getattr(new, fld, []) or [])
        seen = set()
        merged_list = []
        for item in old_list + new_list:
            key = item.lower().strip() if isinstance(item, str) else str(item)
            if key not in seen:
                seen.add(key)
                merged_list.append(item)
        merged[fld] = merged_list

    # sources 取并集
    merged["sources"] = list(set(existing_sources + new_sources))

    # 构造新 Paper 对象
    from search_engine import Paper

    return Paper(**merged)


def _normalize_title(title: str) -> str:
    """
    标题归一化：小写、全角转半角、去标点、去多余空格。
    使用显式 Unicode 范围处理中文（Python 3 \\w 匹配中文但标点处理不一致）。
    """
    if not title:
        return ""
    t = title.strip()
    # 全角字符转半角（统一 CNKI/万方/维普的标点和字母数字差异）
    t = _fullwidth_to_halfwidth(t)
    t = t.lower().strip()
    # 保留字母、数字、中文（CJK Unified Ideographs）、韩文、日文假名
    # 移除所有标点和特殊字符
    t = re.sub(r"[^\w\s一-鿿぀-ゟ゠-ヿ가-힯]", "", t)
    # 合并多余空格
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fullwidth_to_halfwidth(text: str) -> str:
    """全角字符转半角：统一中文数据库中标点和字母数字的编码差异。
    Unicode 全角字符范围: FF01-FF5E 对应半角 21-7E，全角空格 3000 -> 半角空格 0020。
    """
    result = []
    for ch in text:
        cp = ord(ch)
        if cp == 0x3000:  # 全角空格
            result.append(" ")
        elif 0xFF01 <= cp <= 0xFF5E:  # 全角标点/字母/数字
            result.append(chr(cp - 0xFEE0))
        else:
            result.append(ch)
    return "".join(result)


def _normalize_title_for_version(title: str) -> str:
    """标题归一化（版本检测专用）：先移除预印本常见后缀，再做基础归一化。

    移除模式（在基础归一化之前执行，因为 _normalize_title 会先移除括号）：
    - (arXiv version), (arXiv), (preprint), (submitted)
    - (v1), (v2), ... (版本号后缀)
    - arXiv:xxxx 前缀
    """
    if not title:
        return ""
    # 先移除预印本常见后缀（括号还在）
    t = title
    t = re.sub(r"\s*\(arxiv\s*version\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(arxiv\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(preprint\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(submitted\)", "", t, flags=re.IGNORECASE)
    # 移除版本号后缀 (v1), (v2), (version 1) 等
    t = re.sub(r"\s*\(v\d+\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(version\s*\d+\)", "", t, flags=re.IGNORECASE)
    # 移除 arXiv: 前缀
    t = re.sub(r"^arxiv\s*:\s*\d+\.\d+", "", t, flags=re.IGNORECASE)
    # 再做基础归一化
    return _normalize_title(t)
