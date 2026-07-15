"""引用格式化模块 - 5 种学术引用格式

支持格式：APA 7th / MLA 9th / GB/T 7714-2015 / Chicago 17th / Vancouver
"""

import html


def format_citation(paper, style: str) -> str:
    """
    将单篇论文格式化为指定引用格式。

    Args:
        paper: Paper dataclass 或 dict 对象
        style: 'apa' | 'mla' | 'gb7714' | 'chicago' | 'vancouver'

    Returns:
        格式化后的引用字符串（纯文本，HTML 实体已转义）
    """
    style = style.lower().strip()
    formatters = {
        "apa": _format_apa,
        "mla": _format_mla,
        "gb7714": _format_gb7714,
        "chicago": _format_chicago,
        "vancouver": _format_vancouver,
    }
    fmt_func = formatters.get(style)
    if not fmt_func:
        return ""
    return fmt_func(paper)


def format_citations_batch(papers: list, style: str) -> str:
    """
    批量格式化多篇论文，每篇之间空行分隔。

    Args:
        papers: Paper 对象列表
        style: 引用格式

    Returns:
        多篇引用的拼接字符串
    """
    parts = []
    for p in papers:
        text = format_citation(p, style)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


# ============ 字段获取辅助 ============

def _get(paper, field, default=""):
    """安全获取字段值，兼容 Paper dataclass 和 dict"""
    if isinstance(paper, dict):
        return paper.get(field, default) or default
    return getattr(paper, field, default) or default


def _get_year(paper):
    y = _get(paper, "year", 0)
    try:
        return int(y)
    except (ValueError, TypeError):
        return 0


def _plain_escape(text: str) -> str:
    """HTML 实体转义"""
    if not text:
        return ""
    return html.escape(str(text))


# ============ 作者名格式化 ============

def _parse_author(name: str):
    """解析作者名为 (姓, 名) 元组。
    支持格式：'姓, 名' 或 '名 姓' 或 '姓 名'
    """
    name = (name or "").strip()
    if not name:
        return None, None
    if "," in name:
        parts = name.split(",", 1)
        surname = parts[0].strip()
        given = parts[1].strip()
    else:
        parts = name.split()
        if len(parts) >= 2:
            surname = parts[-1]
            given = " ".join(parts[:-1])
        elif len(parts) == 1:
            surname = parts[0]
            given = ""
        else:
            surname = name
            given = ""
    return surname, given


def _initials(given: str) -> str:
    """名缩写：取首字母加大写点"""
    given = (given or "").strip()
    if not given:
        return ""
    # 处理连字符名：Jean-Pierre -> J.-P.
    if "-" in given:
        parts = given.split("-")
        return "-".join(p[0].upper() + "." for p in parts if p)
    # 处理中间名：John Paul -> J. P.
    parts = given.split()
    if len(parts) > 1:
        return " ".join(p[0].upper() + "." for p in parts)
    # 单名
    return given[0].upper() + "." if given else ""


def _full_name(given: str) -> str:
    """名全称"""
    return (given or "").strip()


# ============ APA 7th ============

def _format_apa(paper) -> str:
    authors = _get(paper, "authors", [])
    year = _get_year(paper)
    title = _plain_escape(_get(paper, "title"))
    journal = _plain_escape(_get(paper, "journal"))
    volume = _get(paper, "volume")
    issue = _get(paper, "issue")
    pages = _get(paper, "pages")
    doi = _get(paper, "doi")

    author_str = _format_authors_apa(authors)
    year_str = f"({year})" if year else "([n.d.])"

    parts = [f"{author_str} {year_str}."]
    parts.append(f" {title}.")
    if journal:
        parts.append(f" {journal}")
        if volume:
            parts.append(f", {volume}")
        if issue:
            parts.append(f"({issue})")
        if pages:
            parts.append(f", {pages}")
        parts.append(".")
    if doi:
        parts.append(f" https://doi.org/{doi}")

    return "".join(parts)


def _format_authors_apa(authors: list) -> str:
    """APA: Zhang, L., & Wang, H. (三人以上: Zhang, L., Li, M., & Wang, H.)"""
    if not authors:
        return "[Anonymous]"
    parsed = []
    for a in authors[:20]:  # 限制 20 人
        s, g = _parse_author(a)
        if s:
            if g:
                parsed.append(f"{s}, {_initials(g)}")
            else:
                parsed.append(s)
    if not parsed:
        return "[Anonymous]"
    if len(parsed) == 1:
        return parsed[0]
    if len(parsed) == 2:
        return f"{parsed[0]} & {parsed[1]}"
    return ", ".join(parsed[:-1]) + f", & {parsed[-1]}"


# ============ MLA 9th ============

def _format_mla(paper) -> str:
    authors = _get(paper, "authors", [])
    year = _get_year(paper)
    title = _plain_escape(_get(paper, "title"))
    journal = _plain_escape(_get(paper, "journal"))
    volume = _get(paper, "volume")
    issue = _get(paper, "issue")
    pages = _get(paper, "pages")
    doi = _get(paper, "doi")

    author_str = _format_authors_mla(authors)
    parts = [f"{author_str}. "]
    parts.append(f'"{title}." ')
    if journal:
        parts.append(f"{journal}")
        if volume:
            parts.append(f", vol. {volume}")
        if issue:
            parts.append(f", no. {issue}")
        if year:
            parts.append(f", {year}")
        if pages:
            parts.append(f", pp. {pages}")
        parts.append(". ")
    elif year:
        parts.append(f"{year}. ")
    if doi:
        parts.append(f"DOI: {doi}.")
    return "".join(parts).strip()


def _format_authors_mla(authors: list) -> str:
    """MLA: Zhang, Li, and Hui Wang (两人: Zhang, Li, and Hui Wang)"""
    if not authors:
        return "[Anonymous]"
    parsed = []
    for a in authors[:20]:
        s, g = _parse_author(a)
        if s:
            full = f"{s}, {_full_name(g)}" if g else s
            parsed.append(full)
    if not parsed:
        return "[Anonymous]"
    if len(parsed) == 1:
        return parsed[0]
    if len(parsed) == 2:
        return f"{parsed[0]}, and {parsed[1]}"
    if len(parsed) == 3:
        return f"{parsed[0]}, {parsed[1]}, and {parsed[2]}"
    return f"{parsed[0]}, et al."


# ============ GB/T 7714-2015 ============

def _format_gb7714(paper) -> str:
    authors = _get(paper, "authors", [])
    year = _get_year(paper)
    title = _plain_escape(_get(paper, "title"))
    journal = _plain_escape(_get(paper, "journal"))
    volume = _get(paper, "volume")
    issue = _get(paper, "issue")
    pages = _get(paper, "pages")
    doi = _get(paper, "doi")

    author_str = _format_authors_gb7714(authors)
    parts = [f"{author_str} "]
    parts.append(f"{title}")
    if journal:
        parts.append(f"[J]")
        year_str = f", {year}" if year else ""
        vol_str = f", {volume}" if volume else ""
        issue_str = f"({issue})" if issue else ""
        page_str = f": {pages}" if pages else ""
        parts.append(f". {journal}{year_str}{vol_str}{issue_str}{page_str}")
    parts.append(".")
    if doi:
        parts.append(f" DOI: {doi}.")
    return "".join(parts)


def _format_authors_gb7714(authors: list) -> str:
    """GB/T 7714: ZHANG L, WANG H (三人以上加 et al)"""
    if not authors:
        return "[Anonymous]"
    parsed = []
    for a in authors[:20]:
        s, g = _parse_author(a)
        if s:
            # 姓全大写，名缩写无点
            surname = s.upper()
            if g:
                init = _initials(g).replace(".", "")
                parsed.append(f"{surname} {init}")
            else:
                parsed.append(surname)
    if not parsed:
        return "[Anonymous]"
    if len(parsed) <= 3:
        return ", ".join(parsed)
    return ", ".join(parsed[:3]) + ", et al"


# ============ Chicago 17th (Author-Date) ============

def _format_chicago(paper) -> str:
    authors = _get(paper, "authors", [])
    year = _get_year(paper)
    title = _plain_escape(_get(paper, "title"))
    journal = _plain_escape(_get(paper, "journal"))
    volume = _get(paper, "volume")
    issue = _get(paper, "issue")
    pages = _get(paper, "pages")
    doi = _get(paper, "doi")

    author_str = _format_authors_chicago(authors)
    year_str = str(year) if year else "n.d."

    parts = [f"{author_str}. {year_str}. "]
    parts.append(f'"{title}." ')
    if journal:
        parts.append(f"{journal}")
        if volume:
            parts.append(f" {volume}")
        if issue:
            parts.append(f" ({issue})")
        if pages:
            parts.append(f": {pages}")
        parts.append(". ")
    if doi:
        parts.append(f"https://doi.org/{doi}.")
    return "".join(parts).strip()


def _format_authors_chicago(authors: list) -> str:
    """Chicago: Zhang, Li, and Hui Wang"""
    # Chicago 作者格式与 MLA 类似
    return _format_authors_mla(authors)


# ============ Vancouver ============

def _format_vancouver(paper) -> str:
    authors = _get(paper, "authors", [])
    year = _get_year(paper)
    title = _plain_escape(_get(paper, "title"))
    journal = _plain_escape(_get(paper, "journal"))
    volume = _get(paper, "volume")
    issue = _get(paper, "issue")
    pages = _get(paper, "pages")
    doi = _get(paper, "doi")

    author_str = _format_authors_vancouver(authors)
    parts = [f"{author_str} "]
    parts.append(f"{title}. ")
    if journal:
        parts.append(f"{journal}. ")
    if year:
        parts.append(f"{year}")
        vol_issue = ""
        if volume:
            vol_issue = f";{volume}"
        if issue:
            vol_issue += f"({issue})"
        if pages:
            vol_issue += f":{pages}"
        parts.append(vol_issue)
        parts.append(". ")
    if doi:
        parts.append(f"doi:{doi}.")
    return "".join(parts).strip()


def _format_authors_vancouver(authors: list) -> str:
    """Vancouver: Zhang L, Wang H (六人以上加 et al)"""
    if not authors:
        return "[Anonymous]"
    parsed = []
    for a in authors[:20]:
        s, g = _parse_author(a)
        if s:
            if g:
                parsed.append(f"{s} {_initials(g)}")
            else:
                parsed.append(s)
    if not parsed:
        return "[Anonymous]"
    if len(parsed) <= 6:
        return ", ".join(parsed)
    return ", ".join(parsed[:6]) + ", et al"
