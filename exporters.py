"""导出模块 - RIS / BibTeX / CSV"""

import csv
import io
import re


def export_ris(papers: list) -> str:
    """导出 RIS 格式（EndNote 直接导入）"""
    if not papers:
        return ""
    lines = []
    for p in papers:
        try:
            lines.append("TY  - JOUR")
            if getattr(p, 'title', None):
                lines.append(f"TI  - {p.title}")
            for author in (getattr(p, 'authors', None) or []):
                lines.append(f"AU  - {author}")
            if getattr(p, 'year', None):
                lines.append(f"PY  - {p.year}")
                lines.append(f"DA  - {p.year}")
            if getattr(p, 'journal', None):
                lines.append(f"JO  - {p.journal}")
                lines.append(f"JA  - {p.journal}")
                lines.append(f"T2  - {p.journal}")
            # 尝试提取卷号、期号、页码（如果有）
            if getattr(p, 'volume', None):
                lines.append(f"VL  - {p.volume}")
            if getattr(p, 'issue', None):
                lines.append(f"IS  - {p.issue}")
            if getattr(p, 'pages', None):
                lines.append(f"SP  - {p.pages}")
            if getattr(p, 'issn', None):
                lines.append(f"SN  - {p.issn}")
            if getattr(p, 'doi', None):
                lines.append(f"DO  - {p.doi}")
            if getattr(p, 'pmid', None):
                lines.append(f"AN  - PMID:{p.pmid}")
            if getattr(p, 'abstract', None):
                abs_text = p.abstract[:2000]
                lines.append(f"AB  - {abs_text}")
            for kw in (getattr(p, 'keywords', None) or []):
                lines.append(f"KW  - {kw}")
            if getattr(p, 'oa_url', None):
                lines.append(f"UR  - {p.oa_url}")
            elif getattr(p, 'doi', None):
                lines.append(f"UR  - https://doi.org/{p.doi}")
            lines.append("ER  - ")
            lines.append("")
        except Exception as e:
            print(f"[WARN] Skipping paper in RIS export: {e}")
            continue

    return "\n".join(lines)


def _bibtex_escape(text: str) -> str:
    """BibTeX 特殊字符转义"""
    if not text:
        return ""
    # 先截断再转义，避免截断点在转义序列中间
    text = text[:2000]
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("%", "\\%")
    text = text.replace("#", "\\#")
    return text


def export_bibtex(papers: list) -> str:
    """导出 BibTeX 格式"""
    if not papers:
        return ""
    lines = []
    for i, p in enumerate(papers, 1):
        try:
            key = _make_bibtex_key(p, i)
            entry_type = _infer_entry_type(p)
            lines.append(f"@{entry_type}{{{key},")
            if getattr(p, 'title', None):
                lines.append(f"  title = {{{_bibtex_escape(p.title)}}},")
            if getattr(p, 'authors', None):
                lines.append(f"  author = {{{' and '.join(_bibtex_escape(a) for a in p.authors)}}},")
            if getattr(p, 'journal', None):
                lines.append(f"  journal = {{{_bibtex_escape(p.journal)}}},")
            if getattr(p, 'year', None):
                lines.append(f"  year = {{{p.year}}},")
            # 补充学术字段
            if getattr(p, 'volume', None):
                lines.append(f"  volume = {{{p.volume}}},")
            if getattr(p, 'issue', None):
                lines.append(f"  number = {{{p.issue}}},")
            if getattr(p, 'pages', None):
                lines.append(f"  pages = {{{p.pages}}},")
            if getattr(p, 'issn', None):
                lines.append(f"  issn = {{{p.issn}}},")
            if getattr(p, 'doi', None):
                lines.append(f"  doi = {{{p.doi}}},")
            if getattr(p, 'pmid', None):
                lines.append(f"  pmid = {{{p.pmid}}},")
            if getattr(p, 'abstract', None):
                lines.append(f"  abstract = {{{_bibtex_escape(p.abstract)}}},")
            if getattr(p, 'keywords', None):
                lines.append(f"  keywords = {{{', '.join(_bibtex_escape(kw) for kw in p.keywords)}}},")
            if getattr(p, 'oa_url', None):
                lines.append(f"  url = {{{p.oa_url}}},")
            elif getattr(p, 'doi', None):
                lines.append(f"  url = {{https://doi.org/{p.doi}}},")
            lines.append("}")
            lines.append("")
        except Exception as e:
            print(f"[WARN] Skipping paper in BibTeX export: {e}")
            continue

    return "\n".join(lines)


def _infer_entry_type(paper) -> str:
    """根据论文字段推断 BibTeX 条目类型"""
    if getattr(paper, 'journal', None):
        return "article"
    if hasattr(paper, 'booktitle') and paper.booktitle:
        return "inproceedings"
    return "misc"


def export_csv(papers: list) -> str:
    """导出 CSV 格式"""
    if not papers:
        return ""
    output = io.StringIO()
    writer = csv.writer(output)

    # 表头（包含学术字段）
    writer.writerow([
        "Title", "Authors", "Journal", "Year", "Volume", "Issue", "Pages",
        "DOI", "PMID", "ISSN", "Citations", "OA_URL", "Keywords", "Abstract"
    ])

    for p in papers:
        try:
            writer.writerow([
                getattr(p, 'title', ''),
                "; ".join(getattr(p, 'authors', None) or []),
                getattr(p, 'journal', ''),
                getattr(p, 'year', ''),
                getattr(p, 'volume', ''),
                getattr(p, 'issue', ''),
                getattr(p, 'pages', ''),
                getattr(p, 'doi', ''),
                getattr(p, 'pmid', ''),
                getattr(p, 'issn', ''),
                getattr(p, 'citation_count', 0),
                getattr(p, 'oa_url', ''),
                "; ".join(getattr(p, 'keywords', None) or []),
                (getattr(p, 'abstract', '') or '')[:2000],
            ])
        except Exception as e:
            print(f"[WARN] Skipping paper in CSV export: {e}")
            continue

    return output.getvalue()


def _make_bibtex_key(paper, index: int) -> str:
    """生成 BibTeX 引用键"""
    # 第一作者姓氏
    first_author = ""
    authors = getattr(paper, 'authors', None) or []
    if authors:
        name = authors[0]
        if "," in name:
            # "Smith, John" -> "Smith"
            first_author = name.split(",")[0].strip()
        else:
            # "John Smith" -> "Smith"
            parts = name.strip().split()
            first_author = parts[-1] if parts else ""
        # 只保留 ASCII 字母
        first_author = re.sub(r"[^a-zA-Z]", "", first_author)

    year = str(getattr(paper, 'year', '') or "xxxx")
    author_part = first_author[:8] if first_author else "unknown"

    return f"{author_part}{year}_{index}"


def export_endnote_xml(papers: list) -> str:
    """导出 EndNote XML 格式（Mendeley / EndNote 直接导入）"""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<xml><records>')

    for p in papers:
        lines.append('<record>')
        lines.append('<ref-type name="Journal Article">17</ref-type>')
        lines.append('<contributors>')
        if p.authors:
            lines.append('<authors>')
            for author in p.authors:
                # EndNote XML 格式：姓, 名
                if "," in author:
                    parts = author.split(",", 1)
                    lines.append(f'<author><style face="normal" font="default" size="100">{_xml_escape(parts[0].strip())}, {_xml_escape(parts[1].strip())}</style></author>')
                else:
                    lines.append(f'<author><style face="normal" font="default" size="100">{_xml_escape(author)}</style></author>')
            lines.append('</authors>')
        lines.append('</contributors>')
        if p.title:
            lines.append(f'<titles><title><style face="normal" font="default" size="100">{_xml_escape(p.title)}</style></title></titles>')
        if p.journal:
            lines.append(f'<periodical><full-title><style face="normal" font="default" size="100">{_xml_escape(p.journal)}</style></full-title></periodical>')
        if p.year:
            lines.append(f'<dates><year><style face="normal" font="default" size="100">{p.year}</style></year></dates>')
        # 补充学术字段
        if getattr(p, 'volume', None):
            lines.append(f'<volume><style face="normal" font="default" size="100">{_xml_escape(p.volume)}</style></volume>')
        if getattr(p, 'issue', None):
            lines.append(f'<number><style face="normal" font="default" size="100">{_xml_escape(p.issue)}</style></number>')
        if getattr(p, 'pages', None):
            lines.append(f'<pages><style face="normal" font="default" size="100">{_xml_escape(p.pages)}</style></pages>')
        if getattr(p, 'issn', None):
            lines.append(f'<isbn-issn><style face="normal" font="default" size="100">{_xml_escape(p.issn)}</style></isbn-issn>')
        if p.doi:
            lines.append(f'<electronic-resource-num><style face="normal" font="default" size="100">{_xml_escape(p.doi)}</style></electronic-resource-num>')
        if p.abstract:
            abs_text = _xml_escape(p.abstract[:2000])
            lines.append(f'<abstract><style face="normal" font="default" size="100">{abs_text}</style></abstract>')
        if p.keywords:
            lines.append('<keywords>')
            for kw in p.keywords:
                lines.append(f'<keyword><style face="normal" font="default" size="100">{_xml_escape(kw)}</style></keyword>')
            lines.append('</keywords>')
        if p.pmid:
            lines.append(f'<accession-num><style face="normal" font="default" size="100">{_xml_escape(p.pmid)}</style></accession-num>')
        url = p.oa_url or (f"https://doi.org/{p.doi}" if p.doi else "")
        if url:
            lines.append(f'<urls><related-urls><url><style face="normal" font="default" size="100">{_xml_escape(url)}</style></url></related-urls></urls>')
        lines.append('</record>')

    lines.append('</records></xml>')
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    """XML 特殊字符转义"""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))
