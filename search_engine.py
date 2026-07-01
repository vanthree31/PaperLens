"""检索引擎 - PubMed + OpenAlex 聚合检索（增强版）

支持 PubMed 字段标签语法：
  keyword[ti]   - 标题搜索
  keyword[tiab] - 标题+摘要搜索
  keyword[au]   - 作者搜索
  keyword[ta]   - 期刊名搜索
  keyword[mh]   - MeSH 主题词
  keyword[tw]   - 自由词（Title/Abstract/Keywords）

布尔运算：AND / OR / NOT
年份过滤：2020:2025[pdat]

示例：
  super-resolution microscopy[ti]
  Nature Methods[ta] AND single-molecule[tiab]
  (expansion microscopy[ti] OR light-sheet[ti]) AND 2023:2025[pdat]
"""

import re
import time
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from dataclasses import dataclass, field
from typing import List
import requests
from access_proxy import EZproxyRewriter


@dataclass
class Paper:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    year: int = 0
    doi: str = ""
    pmid: str = ""
    abstract: str = ""
    citation_count: int = 0
    oa_url: str = ""
    keywords: List[str] = field(default_factory=list)
    source: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    issn: str = ""


# 常用期刊缩写映射（用于智能查询构建）
JOURNAL_ALIASES = {
    "nature": "Nature",
    "science": "Science",
    "cell": "Cell",
    "nature methods": "Nat Methods",
    "nat methods": "Nat Methods",
    "nature photonics": "Nat Photonics",
    "nat photonics": "Nat Photonics",
    "nature cell biology": "Nat Cell Biol",
    "nat cell biol": "Nat Cell Biol",
    "nature neuroscience": "Nat Neurosci",
    "nat neurosci": "Nat Neurosci",
    "nature biotechnology": "Nat Biotechnol",
    "nat biotechnol": "Nat Biotechnol",
    "nature communications": "Nat Commun",
    "nat commun": "Nat Commun",
    "nature chemistry": "Nat Chem",
    "nat chem": "Nat Chem",
    "nature physics": "Nat Phys",
    "nat phys": "Nat Phys",
    "nature materials": "Nat Mater",
    "nat mater": "Nat Mater",
    "nature medicine": "Nat Med",
    "nat med": "Nat Med",
    "nature biomedical engineering": "Nat Biomed Eng",
    "cell reports": "Cell Rep",
    "cell rep": "Cell Rep",
    "cell stem cell": "Cell Stem Cell",
    "cell metabolism": "Cell Metab",
    "cell met": "Cell Metab",
    "molecular cell": "Mol Cell",
    "mol cell": "Mol Cell",
    "cancer cell": "Cancer Cell",
    "neuron": "Neuron",
    "immunity": "Immunity",
    "science advances": "Sci Adv",
    "sci adv": "Sci Adv",
    "acs nano": "ACS Nano",
    "light:science": "Light Sci Appl",
    "light science": "Light Sci Appl",
    "optica": "Optica",
    "optics express": "Opt Express",
    "opt express": "Opt Express",
    "biomedical optics": "J Biomed Opt",
    "j biomed opt": "J Biomed Opt",
    "journal of biomedical optics": "J Biomed Opt",
}


def build_pubmed_query(keywords: str, journal: str = "", field: str = "",
                       year_from: int = 0, year_to: int = 0,
                       mesh_term: str = "", pub_type: str = "") -> str:
    """智能构建 PubMed 检索式

    Args:
        keywords: 用户输入的关键词（可含字段标签）
        journal: 期刊过滤（支持缩写或全名）
        field: 默认字段标签（ti/tiab/au/tw），当用户未指定时使用
        year_from: 起始年份
        year_to: 截止年份
        mesh_term: MeSH 主题词
        pub_type: 文献类型（review/clinical trial 等）
    """
    parts = []

    # 处理关键词
    kw = keywords.strip()
    if kw:
        # 如果用户已经写了字段标签（如 xxx[ti]），直接使用
        if re.search(r'\[\w+\]', kw):
            parts.append(f"({kw})")
        elif field:
            # 用户指定了默认字段
            parts.append(f"({kw}[{field}])")
        else:
            # 智能判断：如果有引号或布尔运算符，当作高级查询
            if any(op in kw.upper() for op in [' AND ', ' OR ', ' NOT ']) or '"' in kw:
                parts.append(f"({kw})")
            else:
                # 默认在标题+摘要中搜索
                parts.append(f"({kw}[tiab])")

    # 期刊过滤
    if journal:
        journal = journal.strip()
        # 检查是否是已知缩写
        canonical = JOURNAL_ALIASES.get(journal.lower(), journal)
        parts.append(f"{canonical}[ta]")

    # MeSH 主题词
    if mesh_term:
        parts.append(f"{mesh_term}[mh]")

    # 文献类型
    if pub_type:
        parts.append(f"{pub_type}[pt]")

    # 年份范围（0 表示不限制）
    if year_from and year_to:
        parts.append(f"{year_from}:{year_to}[pdat]")
    elif year_from:
        parts.append(f"{year_from}:{datetime.now().year}[pdat]")
    elif year_to:
        parts.append(f"1900:{year_to}[pdat]")

    return " AND ".join(parts) if parts else keywords


class PubMedSearch:
    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, email="", api_key="", proxy=None):
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "LitSearch/1.0"
        if proxy:
            self.session.proxies = proxy

    def search(self, query: str, year_from=2020, year_to=0,
               sort="relevance", max_results=50,
               journal="", field="", mesh_term="", pub_type="") -> tuple:
        """返回 (PMID 列表, 精确 DOI 或 None)

        Args:
            query: 检索词（可含 PubMed 字段标签）
            journal: 期刊过滤
            field: 默认字段标签
            mesh_term: MeSH 主题词
            pub_type: 文献类型
        """
        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        # 检测是否是 DOI 查询
        exact_doi = None
        doi_match = re.match(r'^(10\.\d{4,}/\S+)$', query.strip())
        if doi_match:
            # 用 DOI[aid] 精确查询，后续需要过滤精确匹配
            term = f'{query.strip()}[aid]'
            exact_doi = query.strip().lower()
        else:
            # 构建检索式
            term = build_pubmed_query(
            keywords=query,
            journal=journal,
            field=field,
            year_from=year_from,
            year_to=year_to,
            mesh_term=mesh_term,
            pub_type=pub_type,
        )

        if not term:
            return [], exact_doi

        # 映射排序参数
        sort_map = {
            "relevance": "relevance",
            "date": "pub+date",
            "citations": "relevance",  # PubMed 无引用排序，回退到相关度
        }

        params = {
            "db": "pubmed",
            "term": term,
            "retmax": max_results,
            "sort": sort_map.get(sort, "relevance"),
            "retmode": "json",
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            # 带重试的请求（应对 PubMed 限流）
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/esearch.fcgi", params=params, timeout=20)
                if r.status_code == 429:
                    wait = min(2 ** attempt, 5)
                    print(f"PubMed rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
            return data.get("esearchresult", {}).get("idlist", []), exact_doi
        except Exception as e:
            print(f"PubMed search error: {e}")
            return [], exact_doi

    def fetch_details(self, pmids: list[str]) -> list:
        """批量获取文献详情"""
        if not pmids:
            return []

        papers = []
        for i in range(0, len(pmids), 100):
            batch = pmids[i:i+100]
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            }
            if self.email:
                params["email"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key

            try:
                # 带重试的请求
                r = None
                for attempt in range(3):
                    r = self.session.get(f"{self.BASE}/efetch.fcgi", params=params, timeout=30)
                    if r.status_code == 429:
                        wait = min(2 ** attempt, 5)
                        print(f"PubMed rate limited (fetch), waiting {wait}s")
                        time.sleep(wait)
                        continue
                    break
                r.raise_for_status()
                papers.extend(self._parse_xml(r.text))
            except Exception as e:
                print(f"PubMed fetch error: {e}")

            if i + 100 < len(pmids):
                time.sleep(0.5)

        return papers

    def _parse_xml(self, xml_text: str) -> list:
        papers = []
        try:
            # 使用安全的 XML 解析器，禁用外部实体
            try:
                parser = ET.XMLParser(resolve_entities=False)
            except TypeError:
                # 某些 Python 版本不支持 resolve_entities 参数
                parser = ET.XMLParser()
            root = ET.fromstring(xml_text, parser=parser)
        except ET.ParseError:
            return papers

        for article in root.findall(".//PubmedArticle"):
            p = Paper(source="pubmed")

            pmid_el = article.find(".//PMID")
            if pmid_el is not None:
                p.pmid = pmid_el.text or ""

            title_el = article.find(".//ArticleTitle")
            if title_el is not None:
                p.title = self._get_text(title_el)

            for author in article.findall(".//Author"):
                last = author.find("LastName")
                first = author.find("ForeName")
                if last is not None and last.text:
                    name = last.text
                    if first is not None and first.text:
                        name += f", {first.text}"
                    p.authors.append(name)

            journal_el = article.find(".//Journal/Title")
            if journal_el is not None:
                p.journal = journal_el.text or ""

            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                try:
                    p.year = int(year_el.text)
                except ValueError:
                    pass

            for aid in article.findall(".//ArticleId"):
                if aid.get("IdType") == "doi":
                    p.doi = aid.text or ""

            # 提取卷号、期号、页码
            volume_el = article.find(".//JournalIssue/Volume")
            if volume_el is not None and volume_el.text:
                p.volume = volume_el.text.strip()
            issue_el = article.find(".//JournalIssue/Issue")
            if issue_el is not None and issue_el.text:
                p.issue = issue_el.text.strip()
            # 页码：尝试 Pagination/StartPage-EndPage 或 MedlinePgn
            pagination_el = article.find(".//Pagination")
            if pagination_el is not None:
                start_page = pagination_el.find("StartPage")
                end_page = pagination_el.find("EndPage")
                if start_page is not None and start_page.text:
                    p.pages = start_page.text.strip()
                    if end_page is not None and end_page.text:
                        p.pages += f"-{end_page.text.strip()}"
            if not p.pages:
                medline_pgn = article.find(".//MedlinePgn")
                if medline_pgn is not None and medline_pgn.text:
                    p.pages = medline_pgn.text.strip()
            # ISSN
            issn_el = article.find(".//ISSN")
            if issn_el is not None and issn_el.text:
                p.issn = issn_el.text.strip()

            abstract_el = article.find(".//Abstract")
            if abstract_el is not None:
                parts = []
                for text_el in abstract_el.findall("AbstractText"):
                    label = text_el.get("Label", "")
                    text = self._get_text(text_el)
                    if label:
                        parts.append(f"{label}: {text}")
                    else:
                        parts.append(text)
                p.abstract = " ".join(parts)

            for kw in article.findall(".//Keyword"):
                if kw.text:
                    p.keywords.append(kw.text)

            papers.append(p)

        return papers

    def _get_text(self, el) -> str:
        return "".join(el.itertext()).strip()


class OpenAlexSearch:
    BASE = "https://api.openalex.org"

    def __init__(self, email="", proxy=None):
        self.email = email
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "LitSearch/1.0"
        self._last_keywords = set()
        if proxy:
            self.session.proxies = proxy

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=50, journal="") -> list:
        """OpenAlex 检索"""
        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        # 检测 DOI 查询，使用专用端点
        doi_match = re.match(r'^(10\.\d{4,}/\S+)$', query.strip())
        if doi_match:
            return self._search_by_doi(query.strip())

        # 清理 PubMed 字段标签，OpenAlex 不识别
        clean_query = re.sub(r'\[(?:ti|tiab|au|ta|tw|mh|pt|pdat)\]', '', query, flags=re.IGNORECASE)
        # 清理布尔运算符中的多余空格
        clean_query = re.sub(r'\s+', ' ', clean_query).strip()
        # 去掉年份过滤（OpenAlex 用 filter 参数处理）
        clean_query = re.sub(r'\d{4}:\d{4}\[pdat\]', '', clean_query).strip()
        # 去掉末尾的 AND/OR
        clean_query = re.sub(r'\s+(AND|OR|NOT)\s*$', '', clean_query, flags=re.IGNORECASE).strip()

        if not clean_query:
            return []

        # 提取核心关键词（用于结果相关性检查）
        self._last_keywords = set()
        for word in re.split(r'\s+(?:AND|OR|NOT)\s+', clean_query, flags=re.IGNORECASE):
            word = word.strip('()"\' ')
            if len(word) > 2 and word.lower() not in ('and', 'or', 'not', 'the', 'for', 'with'):
                self._last_keywords.add(word.lower())

        # 构建过滤条件
        filter_parts = []
        if year_from and year_to:
            filter_parts.append(f"publication_year:{year_from}-{year_to}")
        elif year_from:
            filter_parts.append(f"publication_year:{year_from}-{datetime.now().year}")
        elif year_to:
            filter_parts.append(f"publication_year:1800-{year_to}")
        if journal:
            filter_parts.append(f"primary_location.source.display_name:{journal}")

        params = {
            "search": clean_query,
            "filter": ",".join(filter_parts) if filter_parts else "",
            "per_page": min(max_results * 2, 200),  # 多取一些，后续过滤
            "sort": "relevance_score:desc",
        }
        if self.email:
            params["mailto"] = self.email

        try:
            # 带重试的请求（应对 OpenAlex 限流 429）
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/works", params=params, timeout=15)
                if r.status_code == 429:
                    # 限流，等待后重试
                    wait = min(2 ** attempt * 2, 10)  # 2s, 4s, 8s
                    print(f"OpenAlex rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()
            results = self._parse_results(data.get("results", []))

            # 基本相关性过滤：标题或摘要包含搜索关键词
            keywords = getattr(self, '_last_keywords', set())
            if keywords and len(keywords) >= 2:
                # 只有多个关键词时才进行过滤，避免短关键词误杀
                filtered = []
                for p in results:
                    title_lower = p.title.lower()
                    abstract_lower = (p.abstract or "").lower()
                    # 标题包含任意关键词，或摘要包含多个关键词
                    title_match = any(kw in title_lower for kw in keywords)
                    abstract_match = sum(1 for kw in keywords if kw in abstract_lower) >= 2
                    if title_match or abstract_match:
                        filtered.append(p)
                # 如果过滤后结果太少，回退到原始结果
                if len(filtered) >= 3:
                    return filtered[:max_results]
            return results[:max_results]
        except Exception as e:
            print(f"OpenAlex search error: {e}")
            return []

    def enrich_with_citations(self, papers: list) -> list:
        """用 OpenAlex 补充引用次数和 OA 链接"""
        papers_with_doi = [p for p in papers if p.doi]
        if not papers_with_doi:
            return papers

        # 分批查询（每批最多 25 个，避免 URL 过长）
        for i in range(0, len(papers_with_doi), 25):
            batch = papers_with_doi[i:i+25]
            # OpenAlex 格式: doi:doi1|doi2|doi3（doi: 只出现一次）
            doi_values = "|".join([p.doi for p in batch])
            doi_filter = f"doi:{doi_values}"
            params = {
                "filter": doi_filter,
                "per_page": 50,
            }
            if self.email:
                params["mailto"] = self.email

            try:
                # 带重试的请求（应对 OpenAlex 限流 429）
                r = None
                for attempt in range(3):
                    r = self.session.get(f"{self.BASE}/works", params=params, timeout=15)
                    if r.status_code == 429:
                        wait = min(2 ** attempt * 2, 10)
                        print(f"OpenAlex rate limited (enrich), waiting {wait}s")
                        time.sleep(wait)
                        continue
                    break
                r.raise_for_status()
                data = r.json()

                # 构建 DOI → OpenAlex 结果的映射
                doi_map = {}
                for w in data.get("results", []):
                    oa_doi = (w.get("doi", "") or "").replace("https://doi.org/", "").lower()
                    if oa_doi:
                        doi_map[oa_doi] = w

                # 精确匹配补充信息：仅在 OpenAlex 有有效数据时更新
                for p in batch:
                    doi_key = p.doi.lower()
                    if doi_key in doi_map:
                        w = doi_map[doi_key]
                        oa_citations = w.get("cited_by_count", 0)
                        if oa_citations > 0:
                            p.citation_count = oa_citations
                        if not p.oa_url:
                            oa = w.get("open_access", {})
                            p.oa_url = oa.get("oa_url", "") or ""
            except Exception as e:
                print(f"OpenAlex enrich error: {e}")

            if i + 25 < len(papers_with_doi):
                time.sleep(1)  # 批次间延迟，避免限流

        return papers

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """清理文本：去除 HTML 标签"""
        if not text:
            return ""
        # 去掉 HTML 标签（OpenAlex 返回的标题是纯文本，标签是残留的 markup）
        clean = re.sub(r'<[^>]+>', '', text)
        return clean.strip()

    def _parse_results(self, results) -> list:
        papers = []
        for w in results:
            p = Paper(source="openalex")
            p.title = self._sanitize_text(w.get("title", "") or "")
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            p.journal = src.get("display_name", "") or ""
            p.year = w.get("publication_year", 0) or 0
            p.doi = (w.get("doi", "") or "").replace("https://doi.org/", "")
            p.citation_count = w.get("cited_by_count", 0)

            # 提取卷号、期号、页码
            biblio = w.get("biblio") or {}
            p.volume = str(biblio.get("volume", "") or "")
            p.issue = str(biblio.get("issue", "") or "")
            first_page = str(biblio.get("first_page", "") or "")
            last_page = str(biblio.get("last_page", "") or "")
            if first_page:
                p.pages = first_page if not last_page or first_page == last_page else f"{first_page}-{last_page}"
            # ISSN
            p.issn = str(src.get("issn", "") or "")

            # OpenAlex 摘要是反转索引格式，需要重建
            abstract_inv = w.get("abstract_inverted_index")
            if abstract_inv:
                p.abstract = self._reconstruct_abstract(abstract_inv)

            for author in w.get("authorships", []):
                name = author.get("author", {}).get("display_name", "")
                if name:
                    p.authors.append(name)

            oa = w.get("open_access", {})
            p.oa_url = oa.get("oa_url", "") or ""

            # 关键词
            for kw in w.get("keywords", []):
                k = kw.get("display_name", "") if isinstance(kw, dict) else str(kw)
                if k:
                    p.keywords.append(k)

            papers.append(p)
        return papers

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        """从 OpenAlex 反转索引重建摘要文本"""
        if not inverted_index:
            return ""
        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            return " ".join(w for _, w in word_positions)
        except Exception:
            return ""

    def _search_by_doi(self, doi: str) -> list:
        """通过 DOI 精确查询 OpenAlex"""
        try:
            params = {"mailto": self.email} if self.email else {}
            r = self.session.get(f"{self.BASE}/works/doi:{doi}", params=params, timeout=10)
            if r.status_code == 200:
                w = r.json()
                p = Paper(source="openalex")
                p.title = self._sanitize_text(w.get("title", "") or "")
                loc = w.get("primary_location") or {}
                src = loc.get("source") or {}
                p.journal = src.get("display_name", "") or ""
                p.year = w.get("publication_year", 0) or 0
                p.doi = (w.get("doi", "") or "").replace("https://doi.org/", "")
                p.citation_count = w.get("cited_by_count", 0)
                # 提取卷号、期号、页码
                biblio = w.get("biblio") or {}
                p.volume = str(biblio.get("volume", "") or "")
                p.issue = str(biblio.get("issue", "") or "")
                first_page = str(biblio.get("first_page", "") or "")
                last_page = str(biblio.get("last_page", "") or "")
                if first_page:
                    p.pages = first_page if not last_page or first_page == last_page else f"{first_page}-{last_page}"
                p.issn = str(src.get("issn", "") or "")
                abstract_inv = w.get("abstract_inverted_index")
                if abstract_inv:
                    p.abstract = self._reconstruct_abstract(abstract_inv)
                for author in w.get("authorships", []):
                    name = author.get("author", {}).get("display_name", "")
                    if name:
                        p.authors.append(name)
                oa = w.get("open_access", {})
                p.oa_url = oa.get("oa_url", "") or ""
                for kw in w.get("keywords", []):
                    if isinstance(kw, dict):
                        kw = kw.get("display_name", "")
                    if isinstance(kw, str) and kw:
                        p.keywords.append(kw)
                return [p]
        except Exception as e:
            print(f"OpenAlex DOI search error: {e}")
        return []


class GoogleScholarSearch:
    """Google Scholar 搜索（实验性，依赖 scholarly 库）"""

    def __init__(self, proxy=None):
        self.proxy = proxy
        self._available = None

    def _check_available(self):
        if self._available is None:
            try:
                import scholarly
                self._available = True
            except ImportError:
                self._available = False
                print("Google Scholar: scholarly 库未安装，请运行 pip install scholarly")
        return self._available

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        if not self._check_available():
            return []

        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        try:
            from scholarly import scholarly as sch
            sch.set_timeout(30)
            # 设置代理（scholarly 支持免费代理）
            if self.proxy:
                proxy_url = self.proxy.get("https") or self.proxy.get("http")
                if proxy_url:
                    try:
                        sch.use_proxy(proxies={"http": proxy_url, "https": proxy_url})
                    except Exception:
                        pass  # scholarly 版本可能不支持 use_proxy
            results = []
            search_query = sch.search_pubs(query, year_low=year_from, year_high=year_to)
            for i, result in enumerate(search_query):
                if i >= max_results:
                    break
                p = Paper(source="google_scholar")
                bib = result.get("bib", {})
                p.title = bib.get("title", "")
                p.authors = bib.get("author", []) if isinstance(bib.get("author"), list) else [bib.get("author", "")]
                p.journal = bib.get("venue", "")
                p.year = int(bib.get("pub_year", 0)) if bib.get("pub_year") else 0
                p.abstract = bib.get("abstract", "")
                p.doi = result.get("doi", "") or ""
                # Google Scholar 引用数
                p.citation_count = result.get("num_citations", 0) or 0
                p.oa_url = result.get("eprint_url", "") or ""
                results.append(p)
            return results
        except Exception as e:
            print(f"Google Scholar search error: {e}")
            return []


class PlaywrightBrowser:
    """Playwright 浏览器管理器（用于需要 JavaScript 渲染的网站）"""

    _instance = None
    _browser = None
    _playwright = None
    _proxy = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, proxy=None):
        # 代理变化时，关闭旧浏览器，用新代理重建
        if cls._instance is not None and proxy != cls._proxy:
            with cls._lock:
                if cls._browser:
                    try:
                        cls._browser.close()
                    except Exception:
                        pass
                    cls._browser = None
                cls._proxy = proxy
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(proxy)
        return cls._instance

    def __init__(self, proxy=None):
        self._browser = None
        self._playwright = None
        PlaywrightBrowser._proxy = proxy

    def get_browser(self):
        if self._browser is None or not self._browser.is_connected():
            with self._lock:
                if self._browser is None or not self._browser.is_connected():
                    self._init_browser()
        return self._browser

    def _init_browser(self):
        try:
            from playwright.sync_api import sync_playwright
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            launch_args = {
                "headless": True,
                "args": ['--disable-blink-features=AutomationControlled'],
            }
            # 代理：Playwright launch 接受 server.proxy 格式
            proxy = PlaywrightBrowser._proxy
            if proxy:
                # 优先用 https，其次 http
                proxy_url = proxy.get("https") or proxy.get("http")
                if proxy_url:
                    launch_args["proxy"] = {"server": proxy_url}
                    print(f"Playwright browser using proxy: {proxy_url}")
            self._browser = self._playwright.chromium.launch(**launch_args)
            print("Playwright browser initialized")
        except Exception as e:
            print(f"Playwright init error: {e}")
            self._browser = None

    def new_page(self):
        browser = self.get_browser()
        if browser is None:
            return None
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = context.new_page()
            return page
        except Exception as e:
            print(f"Playwright new page error: {e}")
            return None

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


class CNKISearch:
    """中国知网搜索（实验性，网页抓取）

    注意：CNKI 有严格的反爬机制，包括：
    - JavaScript 验证
    - 浏览器指纹检测
    - IP 限流

    即使使用 Playwright 也可能被检测。建议：
    1. 在机构网络环境下使用
    2. 或使用 PubMed + OpenAlex 替代
    """

    BASE = "https://kns.cnki.net/kns8s/brief/grid"
    MANUAL_SEARCH_URL = "https://kns.cnki.net/kns8s/defaultresult/index"

    def __init__(self, proxy=None, access_proxy=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if proxy:
            self.session.proxies = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        """通过 EZproxy 重写 URL"""
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("CNKI: beautifulsoup4 未安装，请运行 pip install beautifulsoup4")
            return []

        try:
            # CNKI 搜索接口
            search_url = self._url("https://kns.cnki.net/kns8s/brief/grid")
            params = {
                "queryid": "1",
                "txt_1_sel": "SU",  # 主题
                "txt_1_value1": query,
                "txt_1_relation": "#DIFFUSE",
                "txt_1_special1": "=",
                "au_1_sel": "AU",
                "publishdate_from": str(year_from),
                "publishdate_to": str(year_to),
                "sorttype": "0",
                "pageidx": "0",
            }
            r = self.session.get(search_url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            # 检查是否返回验证页面（反爬机制）
            if "/verify/" in r.text or "验证" in r.text[:500]:
                print(f"CNKI: 反爬验证，请手动访问 {self.MANUAL_SEARCH_URL}?kw={query}")
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            rows = soup.select("table.result-table-list tbody tr")

            for row in rows[:max_results]:
                try:
                    p = Paper(source="cnki")
                    # 标题
                    title_el = row.select_one("td.name a")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                    # 作者
                    author_el = row.select_one("td.author")
                    if author_el:
                        authors_text = author_el.get_text(strip=True)
                        p.authors = [a.strip() for a in authors_text.split(";") if a.strip()]
                    # 期刊
                    source_el = row.select_one("td.source")
                    if source_el:
                        p.journal = source_el.get_text(strip=True)
                    # 年份
                    date_el = row.select_one("td.date")
                    if date_el:
                        try:
                            p.year = int(date_el.get_text(strip=True)[:4])
                        except ValueError:
                            pass
                    # 被引
                    quote_el = row.select_one("td.quote")
                    if quote_el:
                        try:
                            p.citation_count = int(quote_el.get_text(strip=True))
                        except ValueError:
                            pass
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"CNKI search error: {e}")
            return []


class WanfangSearch:
    """万方数据搜索（实验性，网页抓取，支持 Cookie 登录）"""

    BASE = "https://s.wanfangdata.com.cn/paper"

    def __init__(self, proxy=None, cookie="", access_proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.session.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        self.session.headers["Accept-Language"] = "zh-CN,zh;q=0.9"
        if cookie:
            self.session.headers["Cookie"] = cookie
        if proxy:
            self.session.proxies = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("万方: beautifulsoup4 未安装，请运行 pip install beautifulsoup4")
            return []

        try:
            params = {
                "q": query,
                "StyleID": "x",
                "Sort": "Correlation",
                "DateType": "Between",
                "PublishDateFrom": str(year_from),
                "PublishDateTo": str(year_to),
            }
            r = self.session.get(self._url(self.BASE), params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            items = soup.select("div.normal-list")

            for item in items[:max_results]:
                try:
                    p = Paper(source="wanfang")
                    # 标题
                    title_el = item.select_one("a.title")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                    # 作者
                    author_el = item.select_one("div.author")
                    if author_el:
                        authors_text = author_el.get_text(strip=True)
                        p.authors = [a.strip() for a in authors_text.replace(";", ",").split(",") if a.strip()]
                    # 期刊
                    source_el = item.select_one("div.source")
                    if source_el:
                        p.journal = source_el.get_text(strip=True)
                    # 年份
                    date_el = item.select_one("div.year")
                    if date_el:
                        try:
                            p.year = int(date_el.get_text(strip=True)[:4])
                        except ValueError:
                            pass
                    # DOI
                    doi_el = item.select_one("a.doi")
                    if doi_el:
                        p.doi = doi_el.get_text(strip=True)
                    # 被引
                    cite_el = item.select_one("div.cited")
                    if cite_el:
                        try:
                            p.citation_count = int(re.sub(r'[^\d]', '', cite_el.get_text()))
                        except ValueError:
                            pass
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"万方 search error: {e}")
            return []


class VIPSearch:
    """维普搜索（实验性，网页抓取）"""

    BASE = "https://www.cqvip.com/search/search.aspx"

    def __init__(self, proxy=None, access_proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        if proxy:
            self.session.proxies = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("维普: beautifulsoup4 未安装，请运行 pip install beautifulsoup4")
            return []

        try:
            params = {
                "k": query,
                "s": "0",  # 相关度排序
                "p": "0",
                "y": f"{year_from}-{year_to}",
            }
            r = self.session.get(self._url(self.BASE), params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"

            soup = BeautifulSoup(r.text, "html.parser")
            papers = []
            items = soup.select("div.result-list li, div.search-result-item")

            for item in items[:max_results]:
                try:
                    p = Paper(source="vip")
                    # 标题
                    title_el = item.select_one("h3 a, a.title, .result-title a")
                    if title_el:
                        p.title = title_el.get_text(strip=True)
                    # 作者
                    author_el = item.select_one(".author, .result-author")
                    if author_el:
                        authors_text = author_el.get_text(strip=True)
                        p.authors = [a.strip() for a in authors_text.replace(";", ",").split(",") if a.strip()]
                    # 期刊
                    source_el = item.select_one(".source, .result-source")
                    if source_el:
                        p.journal = source_el.get_text(strip=True)
                    # 年份
                    date_el = item.select_one(".date, .result-date")
                    if date_el:
                        try:
                            p.year = int(re.search(r'\d{4}', date_el.get_text()).group())
                        except (ValueError, AttributeError):
                            pass
                    # DOI
                    doi_el = item.select_one("a[href*='doi.org']")
                    if doi_el:
                        href = doi_el.get("href", "")
                        doi_match = re.search(r'10\.\d{4,}/\S+', href)
                        if doi_match:
                            p.doi = doi_match.group()
                    if p.title:
                        papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"维普 search error: {e}")
            return []


class BingScholarSearch:
    """Bing 学术搜索（中国区 cn.bing.com，需要 Playwright 渲染）"""

    BASE = "https://cn.bing.com/academic"

    def __init__(self, proxy=None, access_proxy=None):
        self.proxy = proxy
        self.access_proxy = access_proxy

    def _url(self, url):
        return self.access_proxy.rewrite(url) if self.access_proxy else url

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        """使用 Playwright 搜索 Bing Academic（中国区）"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            print("Bing Academic: beautifulsoup4 未安装")
            return []

        if not year_to:
            year_to = datetime.now().year

        page = None
        try:
            pb = PlaywrightBrowser.get_instance(proxy=self.proxy)
            page = pb.new_page()
            if page is None:
                print("Bing Academic: Playwright 不可用")
                return []

            # 构建搜索 URL（添加年份过滤）
            url = self._url(f"{self.BASE}?q={query}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)  # 等待 JavaScript 渲染

            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            papers = []

            # Bing 学术结果选择器（cn.bing.com/academic）
            items = soup.select("li.aca_algo, li[class*='algo']")

            for item in items[:max_results]:
                try:
                    p = Paper(source="bing_academic")

                    # 标题（处理 HTML 标签导致的缺少空格问题）
                    title_el = item.select_one("h2 a")
                    if title_el:
                        p.title = " ".join(title_el.get_text(separator=" ", strip=True).split())

                    # 作者（在 div.caption_author 中）
                    author_el = item.select_one(".caption_author")
                    if author_el:
                        author_links = author_el.select("a")
                        p.authors = [a.get_text(strip=True) for a in author_links if a.get_text(strip=True)]

                    # 期刊和年份（在 div.caption_venue 中）
                    venue_el = item.select_one(".caption_venue")
                    if venue_el:
                        venue_text = venue_el.get_text(strip=True)
                        # 提取年份
                        year_match = re.search(r'\b(20\d{2})\b', venue_text)
                        if year_match:
                            p.year = int(year_match.group(1))
                        # 提取期刊名（在 a 标签中）
                        journal_el = venue_el.select_one("a")
                        if journal_el:
                            p.journal = journal_el.get_text(strip=True)

                    # 摘要（在 div.caption_abstract 中）
                    abstract_el = item.select_one(".caption_abstract p")
                    if abstract_el:
                        p.abstract = abstract_el.get_text(strip=True)

                    # 引用数（在 span.caption_cite_count 中）
                    cite_el = item.select_one(".caption_cite_count")
                    if cite_el:
                        cite_text = cite_el.get_text(strip=True)
                        cite_match = re.search(r'\d+', cite_text)
                        if cite_match:
                            p.citation_count = int(cite_match.group())

                    if p.title and len(p.title) > 5:
                        papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"Bing Academic search error: {e}")
            return []
        finally:
            if page:
                try:
                    page.context.close()
                except Exception:
                    pass


class SemanticScholarSearch:
    """Semantic Scholar 搜索（免费 API，收录部分中文论文）"""

    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key="", proxy=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "LitSearch/1.0"
        if api_key:
            self.session.headers["x-api-key"] = api_key
        if proxy:
            self.session.proxies = proxy

    def search(self, query: str, year_from=2020, year_to=0,
               max_results=20) -> list:
        if not year_to:
            year_to = datetime.now().year

        try:
            params = {
                "query": query,
                "limit": min(max_results, 100),
                "fields": "title,authors,year,abstract,citationCount,externalIds,journal,openAccessPdf",
                "year": f"{year_from}-{year_to}",
            }

            # 带重试的请求（应对限流）
            r = None
            for attempt in range(3):
                r = self.session.get(f"{self.BASE}/paper/search", params=params, timeout=15)
                if r.status_code == 429:
                    wait = min(2 ** attempt * 2, 10)
                    print(f"Semantic Scholar rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            data = r.json()

            papers = []
            for item in data.get("data", []):
                try:
                    p = Paper(source="semantic_scholar")
                    p.title = item.get("title", "") or ""
                    if not p.title:
                        continue

                    # 作者
                    for author in item.get("authors", []):
                        name = author.get("name", "")
                        if name:
                            p.authors.append(name)

                    p.year = item.get("year", 0) or 0
                    p.abstract = item.get("abstract", "") or ""
                    p.citation_count = item.get("citationCount", 0) or 0

                    # 外部 ID
                    ext_ids = item.get("externalIds", {})
                    p.doi = ext_ids.get("DOI", "") or ""
                    p.pmid = ext_ids.get("PubMed", "") or ""

                    # 期刊
                    journal = item.get("journal", {})
                    if journal:
                        p.journal = journal.get("name", "") or ""

                    # OA 链接
                    oa = item.get("openAccessPdf", {})
                    if oa:
                        p.oa_url = oa.get("url", "") or ""

                    papers.append(p)
                except Exception:
                    continue

            return papers
        except Exception as e:
            print(f"Semantic Scholar search error: {e}")
            return []


class ScraperAPIProxy:
    """ScraperAPI 代理（付费服务，绕过反爬机制）"""

    BASE = "http://api.scraperapi.com"

    def __init__(self, api_key):
        self.api_key = api_key

    def get(self, url, params=None, timeout=30, **kwargs):
        """通过 ScraperAPI 代理请求"""
        proxy_params = {
            "api_key": self.api_key,
            "url": url,
            "render": "true",  # 启用 JavaScript 渲染
        }
        if params:
            # 将原始参数编码到 URL 中
            from urllib.parse import urlencode
            proxy_params["url"] = f"{url}?{urlencode(params)}"

        return requests.get(self.BASE, params=proxy_params, timeout=timeout)


class SearchEngine:
    """聚合检索引擎"""

    def __init__(self, config: dict):
        proxy_cfg = config.get("proxy", {})
        proxy = {}
        if proxy_cfg.get("http"):
            proxy["http"] = proxy_cfg["http"]
        if proxy_cfg.get("https"):
            proxy["https"] = proxy_cfg["https"]
        proxy = proxy if proxy else None

        # EZproxy 配置
        ap_cfg = config.get("access_proxy", {})
        self.access_proxy = None
        if ap_cfg.get("mode") == "ezproxy" and ap_cfg.get("ezproxy_host"):
            self.access_proxy = EZproxyRewriter(ap_cfg["ezproxy_host"])

        # ScraperAPI 配置
        scraperapi_key = config.get("scraperapi_key", "")
        self.scraperapi = ScraperAPIProxy(scraperapi_key) if scraperapi_key else None

        sources_cfg = config.get("sources", {})
        pubmed_cfg = sources_cfg.get("pubmed", {})
        openalex_cfg = sources_cfg.get("openalex", {})
        gs_cfg = sources_cfg.get("google_scholar", {})
        cnki_cfg = sources_cfg.get("cnki", {})
        wanfang_cfg = sources_cfg.get("wanfang", {})
        vip_cfg = sources_cfg.get("vip", {})
        bing_cfg = sources_cfg.get("bing_academic", {})
        s2_cfg = sources_cfg.get("semantic_scholar", {})

        self.pubmed = PubMedSearch(
            email=pubmed_cfg.get("email", ""),
            api_key=pubmed_cfg.get("api_key", ""),
            proxy=proxy
        ) if pubmed_cfg.get("enabled", True) else None

        self.openalex = OpenAlexSearch(
            email=openalex_cfg.get("email", ""),
            proxy=proxy
        ) if openalex_cfg.get("enabled", True) else None

        self.google_scholar = GoogleScholarSearch(
            proxy=proxy
        ) if gs_cfg.get("enabled", False) else None

        self.cnki = CNKISearch(
            proxy=proxy,
            access_proxy=self.access_proxy
        ) if cnki_cfg.get("enabled", False) else None

        self.wanfang = WanfangSearch(
            proxy=proxy,
            cookie=wanfang_cfg.get("cookie", ""),
            access_proxy=self.access_proxy
        ) if wanfang_cfg.get("enabled", False) else None

        self.vip = VIPSearch(
            proxy=proxy,
            access_proxy=self.access_proxy
        ) if vip_cfg.get("enabled", False) else None

        self.bing_academic = BingScholarSearch(
            proxy=proxy,
            access_proxy=self.access_proxy
        ) if bing_cfg.get("enabled", False) else None

        self.semantic_scholar = SemanticScholarSearch(
            api_key=s2_cfg.get("api_key", ""),
            proxy=proxy
        ) if s2_cfg.get("enabled", True) else None

    def search(self, query: str, year_from=2020, year_to=0,
               sort="relevance", max_results=50,
               use_pubmed=True, use_openalex=True,
               use_google_scholar=False, use_cnki=False,
               use_wanfang=False, use_vip=False,
               use_bing_academic=False, use_semantic_scholar=True,
               journal="", field="", mesh_term="", pub_type="") -> tuple:
        """聚合检索

        Args:
            query: 检索词（可含 PubMed 字段标签）
            journal: 期刊过滤
            field: 默认字段标签（ti/tiab/au/tw）
            mesh_term: MeSH 主题词
            pub_type: 文献类型（review/clinical trial 等）
            use_google_scholar: 启用 Google Scholar（实验性）
            use_cnki: 启用中国知网（实验性）
            use_wanfang: 启用万方（实验性）
            use_vip: 启用维普（实验性）
            use_bing_academic: 启用 Bing 学术（实验性）

        Returns:
            tuple: (papers, errors) — errors 为各数据源错误信息列表
        """
        # 动态获取当前年份
        if not year_to:
            year_to = datetime.now().year

        all_papers = []
        errors = []

        # PubMed 检索
        if use_pubmed and self.pubmed:
            try:
                pmids, exact_doi = self.pubmed.search(
                    query, year_from, year_to, sort, max_results,
                    journal=journal, field=field,
                    mesh_term=mesh_term, pub_type=pub_type,
                )
                if pmids:
                    papers = self.pubmed.fetch_details(pmids)
                    # DOI 精确搜索时，只保留 DOI 完全匹配的结果
                    if exact_doi:
                        papers = [p for p in papers if p.doi and p.doi.lower() == exact_doi]
                    all_papers.extend(papers)
            except Exception as e:
                errors.append(f"PubMed: {e}")

        # OpenAlex 检索
        if use_openalex and self.openalex:
            try:
                oa_papers = self.openalex.search(
                    query, year_from, year_to, max_results, journal=journal
                )
                all_papers.extend(oa_papers)
            except Exception as e:
                errors.append(f"OpenAlex: {e}")

        # Google Scholar 检索（实验性）
        if use_google_scholar and self.google_scholar:
            try:
                gs_papers = self.google_scholar.search(
                    query, year_from, year_to, max_results=min(max_results, 20)
                )
                all_papers.extend(gs_papers)
            except Exception as e:
                errors.append(f"Google Scholar: {e}")

        # CNKI 检索（实验性）
        if use_cnki and self.cnki:
            try:
                cnki_papers = self.cnki.search(
                    query, year_from, year_to, max_results=min(max_results, 20)
                )
                all_papers.extend(cnki_papers)
            except Exception as e:
                errors.append(f"CNKI: {e}")

        # 万方检索（实验性）
        if use_wanfang and self.wanfang:
            try:
                wf_papers = self.wanfang.search(
                    query, year_from, year_to, max_results=min(max_results, 20)
                )
                all_papers.extend(wf_papers)
            except Exception as e:
                errors.append(f"万方: {e}")

        # 维普检索（实验性）
        if use_vip and self.vip:
            try:
                vip_papers = self.vip.search(
                    query, year_from, year_to, max_results=min(max_results, 20)
                )
                all_papers.extend(vip_papers)
            except Exception as e:
                errors.append(f"维普: {e}")

        # Bing 学术检索（实验性）
        if use_bing_academic and self.bing_academic:
            try:
                bing_papers = self.bing_academic.search(
                    query, year_from, year_to, max_results=min(max_results, 20)
                )
                all_papers.extend(bing_papers)
            except Exception as e:
                errors.append(f"Bing Academic: {e}")

        # Semantic Scholar 检索
        if use_semantic_scholar and self.semantic_scholar:
            try:
                s2_papers = self.semantic_scholar.search(
                    query, year_from, year_to, max_results=min(max_results, 50)
                )
                all_papers.extend(s2_papers)
            except Exception as e:
                errors.append(f"Semantic Scholar: {e}")

        # 去重
        seen_dois = set()
        unique = []
        for p in all_papers:
            key = p.doi.lower() if p.doi else (f"pmid:{p.pmid}" if p.pmid else f"title:{(p.title or '').lower()[:80]}")
            if key not in seen_dois:
                seen_dois.add(key)
                unique.append(p)

        # 年份过滤：确保结果在指定范围内
        # 注意：年份为 0 表示年份未知，保留这些论文（中文数据库常见）
        if year_from or year_to:
            filtered = []
            for p in unique:
                # 年份未知的论文保留
                if not p.year:
                    filtered.append(p)
                    continue
                if year_from and p.year < year_from:
                    continue
                if year_to and p.year > year_to:
                    continue
                filtered.append(p)
            unique = filtered

        # 补充引用次数
        if self.openalex:
            unique = self.openalex.enrich_with_citations(unique)

        # 排序
        if sort == "date":
            unique.sort(key=lambda p: p.year, reverse=True)
        elif sort == "citations":
            unique.sort(key=lambda p: p.citation_count, reverse=True)

        return unique, errors

    def search_by_doi(self, doi: str):
        """通过 DOI 精确查询"""
        if self.pubmed:
            pmids, _ = self.pubmed.search(doi, max_results=1)
            if pmids:
                papers = self.pubmed.fetch_details(pmids)
                if papers:
                    return papers[0]
        if self.openalex:
            papers = self.openalex.search(doi, max_results=1)
            if papers:
                return papers[0]
        return None

    def close(self):
        """关闭所有搜索源的 Session"""
        for source in [self.pubmed, self.openalex, self.google_scholar,
                       self.cnki, self.wanfang, self.vip, self.bing_academic,
                       self.semantic_scholar]:
            if source and hasattr(source, 'session'):
                try:
                    source.session.close()
                except Exception:
                    pass
        # 关闭 Playwright 浏览器
        try:
            PlaywrightBrowser.get_instance().close()
        except Exception:
            pass
