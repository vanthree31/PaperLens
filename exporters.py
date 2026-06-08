"""导出模块 - RIS / BibTeX / CSV"""

import csv
import io
import re
import hashlib


def export_ris(papers: list) -> str:
    """导出 RIS 格式（EndNote 直接导入）"""
    lines = []
    for p in papers:
        lines.append("TY  - JOUR")
        if p.title:
            lines.append(f"TI  - {p.title}")
        for author in p.authors:
            lines.append(f"AU  - {author}")
        if p.year:
            lines.append(f"PY  - {p.year}")
        if p.journal:
            lines.append(f"JO  - {p.journal}")
            lines.append(f"JA  - {p.journal}")
        if p.doi:
            lines.append(f"DO  - {p.doi}")
        if p.pmid:
            lines.append(f"AN  - PMID:{p.pmid}")
        if p.abstract:
            # RIS 摘要长度限制
            abs_text = p.abstract[:2000]
            lines.append(f"AB  - {abs_text}")
        for kw in p.keywords:
            lines.append(f"KW  - {kw}")
        if p.oa_url:
            lines.append(f"UR  - {p.oa_url}")
        elif p.doi:
            lines.append(f"UR  - https://doi.org/{p.doi}")
        lines.append("ER  - ")
        lines.append("")

    return "\n".join(lines)


def export_bibtex(papers: list) -> str:
    """导出 BibTeX 格式"""
    lines = []
    for i, p in enumerate(papers, 1):
        key = _make_bibtex_key(p, i)
        lines.append(f"@article{{{key},")
        if p.title:
            lines.append(f"  title = {{{p.title}}},")
        if p.authors:
            lines.append(f"  author = {{{' and '.join(p.authors)}}},")
        if p.journal:
            lines.append(f"  journal = {{{p.journal}}},")
        if p.year:
            lines.append(f"  year = {{{p.year}}},")
        if p.doi:
            lines.append(f"  doi = {{{p.doi}}},")
        if p.pmid:
            lines.append(f"  pmid = {{{p.pmid}}},")
        if p.abstract:
            abs_text = p.abstract.replace("{", "\\{").replace("}", "\\}")
            lines.append(f"  abstract = {{{abs_text[:1000]}}},")
        if p.keywords:
            lines.append(f"  keywords = {{{', '.join(p.keywords)}}},")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def export_csv(papers: list) -> str:
    """导出 CSV 格式"""
    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    writer.writerow([
        "Title", "Authors", "Journal", "Year", "DOI",
        "PMID", "Citations", "OA_URL", "Keywords", "Abstract"
    ])

    for p in papers:
        writer.writerow([
            p.title,
            "; ".join(p.authors),
            p.journal,
            p.year,
            p.doi,
            p.pmid,
            p.citation_count,
            p.oa_url,
            "; ".join(p.keywords),
            p.abstract[:500] if p.abstract else "",
        ])

    return output.getvalue()


def _make_bibtex_key(paper, index: int) -> str:
    """生成 BibTeX 引用键"""
    # 第一作者姓氏
    first_author = ""
    if paper.authors:
        first_author = paper.authors[0].split(",")[0].strip()
        first_author = re.sub(r"[^a-zA-Z]", "", first_author)

    year = str(paper.year) if paper.year else "xxxx"
    author_part = first_author[:8] if first_author else "unknown"

    return f"{author_part}{year}_{index}"
