"""Utility functions for PaperLens"""

import os
import re
import ipaddress
from urllib.parse import urlparse
from core.config import _get_app_data_dir


def _get_user_data_path(filename: str) -> str:
    """获取用户数据文件路径"""
    # 防止路径穿越：只允许纯文件名
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        raise ValueError(f"Invalid filename: {filename}")
    return os.path.join(_get_app_data_dir(), safe_name)


def _escape_paper(paper) -> dict:
    def esc(s):
        if s is None:
            return ""
        return str(s)
    def esc_list(lst):
        if not lst:
            return []
        return [esc(a) for a in lst]
    return {
        "title": esc(paper.title), "authors": esc_list(paper.authors),
        "journal": esc(paper.journal), "year": paper.year,
        "doi": esc(paper.doi), "pmid": esc(paper.pmid),
        "abstract": esc(paper.abstract), "citation_count": paper.citation_count,
        "oa_url": esc(paper.oa_url), "keywords": esc_list(paper.keywords),
        "source": esc(paper.source),
        "volume": esc(paper.volume), "issue": esc(paper.issue),
        "pages": esc(paper.pages), "issn": esc(paper.issn),
        # Phase 5a: 学术元数据
        "orcid": esc(paper.orcid),
        "article_type": esc(paper.article_type),
        "conference": esc(paper.conference),
        "funding": esc_list(paper.funding),
        "sources": esc_list(paper.sources),
        # Phase 5a: 阅读管理
        "reading_status": esc(paper.reading_status),
        "tags": esc_list(paper.tags),
        "notes": esc(paper.notes),
        # Phase 5b: 版本关系
        "related_versions": esc_list(paper.related_versions),
        # 专利标识
        "doc_type": esc(paper.doc_type),
        # 元数据完整性评分
        "completeness_score": paper.completeness_score if hasattr(paper, 'completeness_score') else 0,
    }


def _sanitize_for_prompt(text: str) -> str:
    """清理文本用于 prompt 构建，移除可能影响 LLM 解析的特殊字符"""
    if not text:
        return ""
    # 移除控制字符，保留换行和制表符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 将多个连续换行合并为两个
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _build_paper_prompt(papers, mode, lang="zh"):
    """构建不同模式的分析 prompt

    Args:
        papers: 论文列表
        mode: 分析模式 (summary/detail/compare)
        lang: 语言 (zh/en)
    """
    paper_info = []
    for i, p in enumerate(papers, 1):
        title = _sanitize_for_prompt(p.title)
        abstract = _sanitize_for_prompt(p.abstract) if p.abstract else ('No abstract' if lang == "en" else '无摘要')
        authors = ', '.join(p.authors[:10])
        keywords = ', '.join(p.keywords) if p.keywords else ('None' if lang == "en" else '无')
        journal = _sanitize_for_prompt(p.journal)
        doi = _sanitize_for_prompt(p.doi)
        pmid = _sanitize_for_prompt(p.pmid)
        if lang == "en":
            info = f"""[Paper {i}]
Title: {title}
Authors: {authors}
Journal: {journal} ({p.year})
DOI: {doi}  PMID: {pmid}  Citations: {p.citation_count}
Abstract: {abstract}
Keywords: {keywords}"""
        else:
            info = f"""【论文 {i}】
标题: {title}
作者: {authors}
期刊: {journal} ({p.year})
DOI: {doi}  PMID: {pmid}  被引: {p.citation_count}
摘要: {abstract}
关键词: {keywords}"""
        paper_info.append(info)
    papers_text = "\n\n".join(paper_info)

    # 防止多篇论文 prompt 超过模型上下文窗口（约8000 token ≈ 32000字符英文/12000字符中文）
    MAX_PROMPT_CHARS = 28000 if lang == "en" else 10000
    if len(papers_text) > MAX_PROMPT_CHARS:
        # 截断每篇论文的摘要以缩减总长度
        per_paper_limit = max(500, MAX_PROMPT_CHARS // len(papers) - 600)
        for i, p in enumerate(papers):
            if p.abstract and len(p.abstract) > per_paper_limit:
                p.abstract = p.abstract[:per_paper_limit] + "..."
                # 重建对应论文的信息
                title = _sanitize_for_prompt(p.title)
                abstract = _sanitize_for_prompt(p.abstract)
                authors = ', '.join(p.authors[:10])
                keywords = ', '.join(p.keywords) if p.keywords else ('None' if lang == "en" else '无')
                journal = _sanitize_for_prompt(p.journal)
                doi = _sanitize_for_prompt(p.doi)
                pmid = _sanitize_for_prompt(p.pmid)
                if lang == "en":
                    paper_info[i] = f"""[Paper {i+1}]
Title: {title}
Authors: {authors}
Journal: {journal} ({p.year})
DOI: {doi}  PMID: {pmid}  Citations: {p.citation_count}
Abstract: {abstract}
Keywords: {keywords}"""
                else:
                    paper_info[i] = f"""【论文 {i+1}】
标题: {title}
作者: {authors}
期刊: {journal} ({p.year})
DOI: {doi}  PMID: {pmid}  被引: {p.citation_count}
摘要: {abstract}
关键词: {keywords}"""
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


def _check_url_safety(target_url, allow_loopback=False):
    """SSRF 防护：检查 URL 是否安全（非内网），包括 DNS 解析后的 IP 检查"""
    try:
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return False, "invalid_url_scheme"
        hostname = parsed.hostname or ""
        # 1. 直接检查裸 IP
        try:
            ip = ipaddress.ip_address(hostname)
            if allow_loopback and ip.is_loopback:
                return True, ""
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                return False, "blocked_internal_url"
        except ValueError:
            # 2. DNS 域名：解析后检查所有 IP
            import socket
            try:
                addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for family, _, _, _, sockaddr in addrinfos:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if allow_loopback and ip.is_loopback:
                        continue
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                        return False, "blocked_internal_url"
            except (socket.gaierror, OSError):
                pass  # DNS 解析失败，让 requests 处理
        return True, ""
    except Exception:
        return False, "invalid_url"
