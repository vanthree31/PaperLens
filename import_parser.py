"""通用文献文件导入解析器 — 支持 EndNote XML / RIS / BibTeX / CSV / PubMed XML / JSON"""

import re
import json
import xml.etree.ElementTree as ET
from typing import List


def detect_format(content: str) -> str:
    """根据内容自动检测文献文件格式"""
    stripped = content.strip()
    if stripped.startswith("<?xml") or stripped.startswith("<xml"):
        # XML — 进一步区分 EndNote XML vs PubMed XML vs MODS
        if (
            "<PubmedArticle" in stripped[:500]
            or "<MedlineCitation" in stripped[:500]
            or "<PubMedArticle" in stripped[:500]
        ):
            return "pubmed_xml"
        if "<record>" in stripped[:500] or "<records>" in stripped[:500]:
            return "endnote_xml"
        if "<mods" in stripped[:500] or "<MODS" in stripped[:500]:
            return "pubmed_xml"  # MODS 结构类似 PubMed
        return "endnote_xml"
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if (
        stripped.startswith("@")
        or stripped.startswith("%")
        or stripped.startswith("  ")
    ):
        return "bibtex"
    # RIS: starts with TY  -  after optional BOM
    if "TY  - " in stripped[:500] or "TY   - " in stripped[:500]:
        return "ris"
    # CSV: header row with comma-separated field names
    first_line = stripped.split("\n")[0]
    if "," in first_line or "\t" in first_line:
        csv_headers = [
            h.strip().lower().strip('"')
            for h in (
                first_line.split(",") if "," in first_line else first_line.split("\t")
            )
        ]
        if any(
            h in csv_headers for h in ("title", "authors", "doi", "year", "journal")
        ):
            return "csv"
    return "unknown"


def parse_file(content: str) -> List[dict]:
    """自动检测格式并解析，返回 Paper dict 列表"""
    fmt = detect_format(content)
    if fmt == "endnote_xml":
        return _parse_endnote_xml(content)
    elif fmt == "pubmed_xml":
        return _parse_pubmed_xml(content)
    elif fmt == "ris":
        return _parse_ris(content)
    elif fmt == "bibtex":
        return _parse_bibtex(content)
    elif fmt == "csv":
        return _parse_csv(content)
    elif fmt == "json":
        return _parse_json(content)
    elif fmt == "unknown":
        # 最后尝试：提取 DOI（支持纯文本 DOI 列表）
        dois = re.findall(r"10\.\d{4,}/[^\s\"\'<>]+", content)
        if dois:
            return [{"doi": d.strip(), "title": ""} for d in dois[:200]]
    return []


# ============ EndNote XML ============


def _parse_endnote_xml(content: str) -> List[dict]:
    """解析 EndNote XML 导出文件"""
    papers = []
    try:
        root = ET.fromstring(content)
        for rec in root.iter("record"):
            p = {}
            # ref-type
            rt = rec.find("ref-type")
            if rt is not None:
                p["article_type"] = rt.get("name", "")
            # title
            title_el = rec.find(".//title/style")
            if title_el is not None and title_el.text:
                p["title"] = title_el.text.strip()
            # secondary-title (conference/journal)
            st_el = rec.find(".//secondary-title/style")
            if st_el is not None and st_el.text:
                journal = st_el.text.strip()
                if journal:
                    p["journal"] = journal
            # authors
            authors = []
            for auth in rec.iter("author"):
                style = auth.find("style")
                if style is not None and style.text:
                    authors.append(style.text.strip())
            if authors:
                p["authors"] = authors
            # date/year
            date_el = rec.find(".//dates/year/style")
            if date_el is not None and date_el.text:
                try:
                    p["year"] = int(date_el.text.strip())
                except ValueError:
                    pass
            # DOI
            for eid in rec.iter("electronic-resource-num"):
                style = eid.find("style")
                if style is not None and style.text:
                    text = style.text.strip()
                    if text.startswith("doi:") or text.startswith("DOI:"):
                        p["doi"] = text.split(":", 1)[1].strip()
                    elif "/" in text and "." in text:  # heuristic DOI
                        p["doi"] = text
            # abstract
            abs_el = rec.find(".//abstract/style")
            if abs_el is not None and abs_el.text:
                p["abstract"] = abs_el.text.strip()[:5000]
            # volume/issue/pages
            for prop in [("volume", "volume"), ("number", "issue"), ("pages", "pages")]:
                el = rec.find(f".//{prop[0]}/style")
                if el is not None and el.text:
                    p[prop[1]] = el.text.strip()
            # url
            for url_el in rec.iter("urls"):
                for web_url in url_el.iter("web-urls"):
                    style = web_url.find("style")
                    if style is not None and style.text:
                        p["url"] = style.text.strip()
            if p.get("title"):
                papers.append(p)
    except ET.ParseError:
        pass
    return papers


# ============ RIS ============


def _parse_ris(content: str) -> List[dict]:
    """解析 RIS 格式文件"""
    papers = []
    current = {}
    for line in content.split("\n"):
        line = line.rstrip("\r")
        if len(line) < 6:
            continue
        tag = line[:2].strip()
        # RIS lines are "TY  - value" or "TY   - value"
        if line[2:4] not in ("  ", " -", "   ", "  -"):
            # maybe new format without spaces
            if line[2] != " ":
                tag = line[:2]
                value = line[3:].strip() if len(line) > 3 else ""
            else:
                continue
        else:
            value = line[6:].strip()
        if tag == "TY":
            if current and current.get("title"):
                papers.append(current)
            current = {}
        elif tag == "ER":
            if current and current.get("title"):
                papers.append(current)
            current = {}
            continue
        elif tag == "TI" or tag == "T1":
            current["title"] = value
        elif tag == "AU" or tag == "A1":
            current.setdefault("authors", []).append(value)
        elif tag == "AB" or tag == "N2":
            current["abstract"] = (current.get("abstract", "") + " " + value).strip()[
                :5000
            ]
        elif tag == "DO" or tag == "M3":
            current["doi"] = value
        elif tag == "PY" or tag == "Y1":
            try:
                current["year"] = int(value[:4])
            except ValueError:
                pass
        elif tag == "JO" or tag == "JF" or tag == "T2":
            current["journal"] = value
        elif tag == "VL":
            current["volume"] = value
        elif tag == "IS" or tag == "CP":
            current["issue"] = value
        elif tag == "SP":
            current["pages"] = value
        elif tag == "UR" or tag == "L1" or tag == "LK":
            if not current.get("url"):
                current["url"] = value
        elif tag == "KW":
            current.setdefault("keywords", []).append(value)
        elif tag == "SN":
            current.setdefault("issn", value)
    if current and current.get("title"):
        papers.append(current)
    return papers


# ============ BibTeX ============


def _parse_bibtex(content: str) -> List[dict]:
    """解析 BibTeX 格式文件"""
    papers = []
    content = re.sub(r"%.*$", "", content, flags=re.MULTILINE)  # remove comments
    entries = (
        re.findall(r"@\w+\s*\{[^@]*\}", content, re.DOTALL)
        if re.search(r"@\w+\s*\{", content)
        else [content]
    )
    for entry_text in entries:
        p = {}
        # type
        type_m = re.match(r"@(\w+)\s*\{", entry_text)
        if type_m and type_m.group(1).lower() == "article":
            p["article_type"] = "Journal Article"
        # cite key
        key_m = re.match(r"@\w+\s*\{([^,]+),", entry_text)
        # fields
        for fname, key in [
            ("title", "title"),
            ("author", "authors"),
            ("abstract", "abstract"),
            ("doi", "doi"),
            ("journal", "journal"),
            ("year", "year"),
            ("volume", "volume"),
            ("number", "issue"),
            ("pages", "pages"),
            ("url", "url"),
            ("keywords", "keywords"),
        ]:
            pat = rf'{fname}\s*=\s*[{{"]([^}}"]*?)[}}"]\s*[,}}]'
            m = re.search(pat, entry_text, re.IGNORECASE | re.DOTALL)
            if m:
                val = m.group(1).strip()
                if key == "authors":
                    p[key] = [a.strip() for a in val.replace("\n", " ").split(" and ")]
                elif key == "year":
                    try:
                        p[key] = int(val[:4])
                    except ValueError:
                        pass
                elif key == "keywords":
                    p[key] = [k.strip() for k in val.split(",")]
                else:
                    # unescape BibTeX special chars
                    val = (
                        val.replace("\\{", "{").replace("\\}", "}").replace("\\_", "_")
                    )
                    val = val.replace("{\\textendash}", "–").replace(
                        "{\\textemdash}", "—"
                    )
                    p[key] = val
        if p.get("title"):
            papers.append(p)
    return papers


# ============ CSV ============


def _parse_csv(content: str) -> List[dict]:
    """解析 CSV/TSV 格式（PaperLens 导出格式或通用学术 CSV）"""
    import csv
    import io

    papers = []
    # 自动检测分隔符
    first_line = content.strip().split("\n")[0]
    delimiter = "\t" if "\t" in first_line else ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    for row in reader:
        # 标准化列名（大小写不敏感）
        row_lower = {k.strip().lower().strip('"'): v for k, v in row.items() if k}
        p = {}
        for col in row_lower:
            val = row_lower[col].strip().strip('"')
            if not val or val in ("N/A", "n/a", "-", ""):
                continue
            if col in ("title",):
                p["title"] = val
            elif col in ("authors", "author"):
                p["authors"] = [
                    a.strip() for a in val.replace(";", ",").split(",") if a.strip()
                ]
            elif col in ("doi",):
                p["doi"] = val
            elif col in ("year", "publication_year", "date"):
                try:
                    p["year"] = int(val[:4])
                except ValueError:
                    pass
            elif col in ("journal", "journal_name", "source", "publicationtitle"):
                p["journal"] = val
            elif col in ("abstract", "abstractnote"):
                p["abstract"] = val[:5000]
            elif col in ("volume",):
                p["volume"] = val
            elif col in ("issue", "number"):
                p["issue"] = val
            elif col in ("pages",):
                p["pages"] = val
            elif col in ("url", "link", "oa_url", "pdf_url"):
                if not p.get("url"):
                    p["url"] = val
            elif col in ("keywords", "tags"):
                p["keywords"] = [
                    k.strip() for k in val.replace(";", ",").split(",") if k.strip()
                ]
            elif col in ("issn",):
                p["issn"] = val
            elif col in ("article_type", "itemtype", "type"):
                p["article_type"] = val
        if p.get("title"):
            papers.append(p)
    return papers


# ============ PubMed XML ============


def _parse_pubmed_xml(content: str) -> List[dict]:
    """解析 PubMed XML / MEDLINE / MODS 格式"""
    papers = []
    try:
        root = ET.fromstring(content)
        articles = (
            root.findall(".//PubmedArticle")
            or root.findall(".//PubMedArticle")
            or [root]
        )
        for article in articles:
            p = {}
            cit = article.find(".//MedlineCitation") or article
            art = cit.find(".//Article") or cit
            # 标题
            title_el = art.find(".//ArticleTitle")
            if title_el is not None and title_el.text:
                p["title"] = title_el.text.strip()
            # 摘要
            abs_el = art.find(".//Abstract/AbstractText")
            if abs_el is not None and abs_el.text:
                p["abstract"] = abs_el.text.strip()[:5000]
                for ab in art.findall(".//AbstractText"):
                    if ab.text and ab is not abs_el:
                        p["abstract"] += " " + ab.text.strip()
            # 作者
            author_list = art.find(".//AuthorList")
            if author_list is not None:
                p["authors"] = []
                for auth in author_list.findall("Author"):
                    ln = (auth.findtext("LastName") or "").strip()
                    fn = (auth.findtext("ForeName") or "").strip()
                    if ln:
                        p["authors"].append(f"{fn} {ln}".strip())
            # DOI
            for eid in art.findall(".//ELocationID"):
                if eid.get("EIdType", "").lower() == "doi" and eid.text:
                    p["doi"] = eid.text.strip()
            if not p.get("doi"):
                for aid in art.findall(".//ArticleId"):
                    if aid.get("IdType", "").lower() == "doi" and aid.text:
                        p["doi"] = aid.text.strip()
            # 期刊
            journal_el = art.find(".//Journal/Title")
            if journal_el is not None and journal_el.text:
                p["journal"] = journal_el.text.strip()
            # 年份
            date_el = art.find(".//Journal/JournalIssue/PubDate/Year")
            if date_el is not None and date_el.text:
                try:
                    p["year"] = int(date_el.text.strip())
                except ValueError:
                    pass
            # 卷/期/页
            vol_el = art.find(".//Journal/JournalIssue/Volume")
            if vol_el is not None and vol_el.text:
                p["volume"] = vol_el.text.strip()
            iss_el = art.find(".//Journal/JournalIssue/Issue")
            if iss_el is not None and iss_el.text:
                p["issue"] = iss_el.text.strip()
            pg_el = art.find(".//Pagination/MedlinePgn")
            if pg_el is not None and pg_el.text:
                p["pages"] = pg_el.text.strip()

            if p.get("title"):
                papers.append(p)
    except ET.ParseError:
        pass
    return papers


# ============ JSON ============


def _parse_json(content: str) -> List[dict]:
    """解析 JSON 格式（CrossRef / OpenAlex / Zotero / PaperLens 导出）"""
    papers = []
    try:
        data = json.loads(content)
        items = data if isinstance(data, list) else [data]
        for item in items:
            p = {}
            # CrossRef API
            if "DOI" in item or (
                "title" in item and isinstance(item.get("title"), list)
            ):
                titles = item.get("title", [])
                p["title"] = (
                    titles[0]
                    if isinstance(titles, list) and titles
                    else str(item.get("title", ""))
                )
                p["doi"] = item.get("DOI", "")
                p["abstract"] = (item.get("abstract", "") or "")[:5000]
                containers = item.get("container-title", [])
                p["journal"] = containers[0] if containers else ""
                authors = item.get("author", [])
                p["authors"] = [
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in authors
                ]
                dp = item.get("published-print") or item.get("created") or {}
                dates = dp.get("date-parts", [[0]])[0]
                if dates[0]:
                    p["year"] = dates[0]
                p["volume"] = str(item.get("volume") or "")
                p["issue"] = str(item.get("issue") or "")
                p["pages"] = str(item.get("page") or "")
            # OpenAlex
            elif "display_name" in item:
                p["title"] = item.get("display_name") or ""
                p["doi"] = (item.get("doi", "") or "").replace("https://doi.org/", "")
                ab = item.get("abstract_inverted_index") or {}
                if isinstance(ab, dict) and ab:
                    words = sorted(ab.items(), key=lambda x: x[1][0] if x[1] else 0)
                    p["abstract"] = " ".join(w[0] for w in words)[:5000]
            # Generic / Zotero / PaperLens export
            elif "title" in item:
                p["title"] = item.get("title", "")
                p["doi"] = item.get("doi", "") or item.get("DOI", "")
                p["year"] = item.get("year", 0)
                p["journal"] = item.get("journal", "") or item.get(
                    "publicationTitle", ""
                )
                p["authors"] = item.get("authors", []) or item.get("creators", [])
                p["abstract"] = (
                    item.get("abstract", "") or item.get("abstractNote", "")
                )[:5000]
                p["volume"] = str(item.get("volume", "") or "")
                p["issue"] = str(item.get("issue", "") or "")
                p["pages"] = str(item.get("pages", "") or "")

            if p.get("title"):
                papers.append(p)
    except (json.JSONDecodeError, TypeError):
        pass
    return papers
