<p align="center">
  <a href="README.zh-CN.md">中文</a> | <b>English</b>
</p>

<p align="center">
  <h1 align="center">PaperLens</h1>
  <p align="center"><b>Your AI Research Copilot</b></p>
  <p align="center"><i>Stop searching papers. Start understanding research.</i></p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.9+-blue.svg?logo=python&logoColor=white" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/license-custom-green.svg" alt="PaperLens Community License">
    <img src="https://img.shields.io/badge/data%20sources-43-orange" alt="43 Data Sources">
    <img src="https://img.shields.io/badge/AI-local%20%7C%20cloud-purple" alt="AI Models">
    <img src="https://img.shields.io/badge/universities-300%2B-blue" alt="300+ Universities via CARSI">
    <img src="https://img.shields.io/github/stars/vanthree31/PaperLens?style=social&logo=github" alt="GitHub Stars">
  </p>
</p>

<p align="center">
  <a href="https://vanthree31.github.io/PaperLens/promo.html">
    <img src="https://img.shields.io/badge/🌐_Promo_Site-English-blue?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Promo Site (English)">
  </a>
  <a href="https://vanthree31.github.io/PaperLens/promo-zh.html">
    <img src="https://img.shields.io/badge/🌐_推广页面-中文-red?style=for-the-badge&logo=googlechrome&logoColor=white" alt="推广页面 (中文)">
  </a>
</p>

<!-- TODO: Hero demo GIF — show the full workflow in 8-10s: type a research question → results appear → open a paper → AI analysis panel → citation graph. File: assets/demo.gif -->

---

## What is PaperLens?

PaperLens is an **AI research copilot** that turns the messy, fragmented process of academic literature work into a single, coherent workflow. It's like **Cursor, but for research papers**.

Most researchers spend their days bouncing between Google Scholar, arXiv, PDF readers, and half a dozen browser tabs. PaperLens replaces all of that with one tool:

```
Find → Filter → Read → Understand → Save → Cite
```

- **43 academic databases** searched in parallel, including PubMed, Scopus, ScienceDirect, arXiv, CNKI, and more
- **300+ Chinese universities** accessible via CARSI — no VPN needed for ScienceDirect, Scopus, JSTOR from anywhere
- **100% local-first** — all data stays on your machine. Runs fully offline with Ollama. No account required.

---

## Demo

| Search & Discover | Paper List | AI Deep Analysis |
|:---:|:---:|:---:|
| ![Search](assets/screenshot-search.png) | ![Papers](assets/screenshot-papers.png) | ![Analysis](assets/screenshot-analysis.png) |

| Multi-Paper Compare | Citation Graph |
|:---:|:---:|
| ![Compare](assets/screenshot-compare.png) | ![Graph](assets/screenshot-graph.png) |

---

## Why PaperLens?

### The researcher's daily workflow (before PaperLens)

Google Scholar → arXiv → open PDF → not what I need → keep searching → open more tabs → 20 tabs later, still no clarity.

### With PaperLens

Describe your research question in natural language. PaperLens searches **43 databases at once**, ranks results by relevance, and lets you:

- **Read a paper in 2 minutes instead of 30** — AI extracts what matters: method, innovation, strengths, weaknesses, future directions
- **Find the right paper in seconds, not hours** — AI understands your research intent, not just keyword matching
- **Compare papers side-by-side** — spot contradictions, identify research gaps, find complementary approaches
- **Discover connections** — interactive citation graph reveals how papers relate, who cites whom, and emerging research clusters

| Pain Point | PaperLens Solution |
|---|---|
| VPN needed for off-campus access to ScienceDirect / Scopus | **CARSI authentication** — 300+ universities, zero config |
| Don't know how to write Boolean queries | **Natural language** — type your question in Chinese or English, AI builds the query |
| Switching between PubMed, Scopus, Google Scholar, CNKI... | **43 sources, one search** — unified, deduplicated results |
| Reading 50 papers for a literature review | **AI Deep Analysis** — 7-dimension breakdown + multi-paper comparison |
| Hard to find cross-disciplinary connections | **Interactive citation graph** (D3.js) — click to expand, drag to explore |
| Data privacy concerns with cloud tools | **100% local** — works fully offline with Ollama, no data leaves your machine |

---

## The Research Workflow

PaperLens isn't just a search tool. It's a complete pipeline:

### 1. Find
Describe your research interest in natural language. PaperLens AI constructs the optimal query and searches **43 academic databases** in parallel — PubMed, OpenAlex, CrossRef, arXiv, Semantic Scholar, ScienceDirect, Scopus, JSTOR, CNKI, Wanfang, VIP, Google Scholar, and more. Results are deduplicated, enriched, and ranked in seconds.

### 2. Filter
Narrow down results by journal, year, field tags, publication type, or metadata completeness. Every paper gets a **metadata score (0-100%)** so you know what's well-documented and what's missing data.

### 3. Read
Select any paper. AI extracts the essence:

```
Summary  →  Deep Analysis  →  Method  →  Innovation  →  Strength  →  Weakness  →  Future Work  →  Related Papers
```

This isn't a one-sentence summary. It's a **7-dimension structured breakdown** — like having a senior colleague walk you through the paper.

### 4. Understand
Compare multiple papers side-by-side. AI identifies:
- Where approaches agree and diverge
- Research gaps no one has addressed
- Contradictions between findings
- Promising directions for future work

### 5. Save & Cite
Export in any format: **RIS, BibTeX, CSV, EndNote XML**. Generate citations in **APA 7th, MLA 9th, GB/T 7714, Chicago 17th, Vancouver**. Track reading status (unread / reading / read). Sync tags bidirectionally with Zotero. Download OA PDFs with one click.

---

## Core Features

### AI Search
- **43 data sources** searched in parallel — see the full list in [ROADMAP.md](ROADMAP.md)
- **Natural language** — Chinese or English, AI understands your intent
- **Batch DOI import** — paste a list of DOIs, enrich all at once
- **Smart filtering** — journal, year, field tags, publication type, metadata completeness
- **Progressive rendering** — results appear per-source as they arrive, no waiting

### AI Deep Analysis
- **Summary** — one-paragraph overview: what, how, why it matters
- **Deep Analysis** — 7 dimensions: contribution, motivation, methods, results, limitations, context, future work
- **Multi-Paper Compare** — systematic comparison across approaches, innovations, and research gaps
- **Novelty Detection** — identifies under-explored areas, contradictions, and promising directions

### CARSI Institutional Access
Connect to **300+ Chinese universities** via CARSI. Access ScienceDirect, Scopus, JSTOR, and institutional databases **without VPN, from anywhere in the world**.

| Source | Status | Auth |
|---|---|---|
| ScienceDirect | ✅ | CARSI |
| Scopus | ✅ | CARSI |
| JSTOR | ✅ | CARSI |
| CNKI | ✅ | CARSI + captcha |

### Interactive Citation Graph
- **D3.js force-directed graph** — zoom, pan, drag, click to expand
- **Keyword co-occurrence network** — discover thematic clusters
- **Author collaboration network** — see co-authorship patterns
- Click any paper node to load its citing and referenced papers on-the-fly

### Export & Integration
- **Multi-format export** — RIS, BibTeX, CSV, EndNote XML
- **Citation formatting** — APA 7th, MLA 9th, GB/T 7714, Chicago 17th, Vancouver
- **Zotero integration** — SQLite direct read + MCP plugin + bi-directional tag sync + PDF full-text extraction
- **Tag system** — custom tags, color picker, Zotero sync
- **Reading status** — unread / reading / read tracking
- **Batch operations** — multi-select, one-click export
- **Smart export** — auto-organized sub-folders: PDF / RIS / BibTeX / CSV / Citations

---

## PaperLens vs The World

> Why not just use Google Scholar? Or ChatGPT? Or Perplexity?

| | PaperLens | Google Scholar | ChatGPT / Perplexity | Zotero | Connected Papers |
|---|:---:|:---:|:---:|:---:|:---:|
| **Complete research workflow** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **AI Deep Analysis (7-dim)** | ✅ | ❌ | Surface-level | ❌ | ❌ |
| **Multi-paper comparison** | ✅ | ❌ | Manual copy-paste | ❌ | ❌ |
| **43 sources, one search** | ✅ | 1 source | 0 sources (no real-time) | ❌ | 1 source |
| **Citation graph** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Offline / local-first** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **CARSI 300+ universities** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Citation formatting** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **Reference management** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **Chinese + English** | ✅ | Limited | ✅ | ✅ | ❌ |
| **Free for personal use** | ✅ | ❌ | ❌ | ✅ | ❌ |

---

## Quick Start

### 30-Second Setup

```bash
git clone https://github.com/vanthree31/PaperLens.git
cd PaperLens
pip install -r requirements.txt
python main.py
```

The app opens in a native window (PyWebView) or your default browser.

### Standalone Executable (No Python Required)

Download from [GitHub Releases](https://github.com/vanthree31/PaperLens/releases), or build:

```bash
build.bat          # Windows → dist/PaperLens.exe
```

### Configure AI (Optional)

Open **Settings** in the app:

| Setting | Recommended |
|---|---|
| AI Search | `qwen3.5:9b` via Ollama (fast, local) |
| AI Analysis | `qwen3:14b` via Ollama (quality, local) |
| Or cloud API | DeepSeek / OpenAI / Anthropic |

All AI processing runs **fully offline with Ollama** — no API key, no data leaves your machine.

### CARSI Setup (Chinese University Members)

1. Open Settings → select your university from the CARSI list
2. Log in with campus credentials
3. ScienceDirect, Scopus, JSTOR are now accessible from anywhere

---

## Platform Support

| Platform | Status |
|---|---|
| Windows 10/11 | Full support, standalone .exe |
| macOS | `python main.py` |
| Linux | `python main.py` |

**Requirements:** Python 3.9+, modern browser (Chrome/Edge recommended)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | ES Modules (7 JS + 9 CSS), D3.js |
| AI | Ollama (offline) / DeepSeek / OpenAI / Anthropic |
| Auth | CARSI / EZproxy |
| Packaging | PyInstaller |
| Extension | Chrome Manifest V3 |

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Contributing

Bug reports, feature ideas, and code contributions are all welcome.

**Good first issues:** [`good-first-issue`](https://github.com/vanthree31/PaperLens/labels/good-first-issue)

1. Fork the repo → 2. Create a branch → 3. Commit → 4. Open a PR

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## Community & Support

<details>
<summary>Feedback & Discussion (QQ Group)</summary>

| QR Code | Group ID |
|:---:|:---:|
| <img src="assets/feedback-qr.jpg" width="180" alt="QQ Group QR"> | **632743351** |

</details>

If PaperLens helps your research, consider [supporting the project](SUPPORT.md). ☕

---

## License

**Free for personal, academic, and research use.**

Commercial use (including SaaS, paid services, or integrating into a for-profit product) requires prior written authorization. See [LICENSE](LICENSE) for details.

📧 For commercial licensing or partnership: vanthree31@gmail.com

---

<p align="center">
  <b>PaperLens</b> — Your AI Research Copilot<br>
  <sub>Find. Read. Understand. Discover.</sub><br><br>
  <a href="https://github.com/vanthree31/PaperLens">
    <img src="https://img.shields.io/github/stars/vanthree31/PaperLens?style=for-the-badge&logo=github" alt="Star on GitHub">
  </a>
</p>
