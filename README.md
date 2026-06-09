<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">中文</a>
</p>

<p align="center">
  <h1 align="center">🔬 PaperLens</h1>
  <p align="center"><b>AI-Powered Research Assistant</b> for Academic Paper Discovery, Analysis, and Citation Network Exploration</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/powered%20by-PubMed%20%2B%20OpenAlex-orange" alt="Data Sources">
    <img src="https://img.shields.io/badge/AI-RAG%20Architecture-purple" alt="AI RAG">
  </p>
</p>

---

## What is PaperLens?

PaperLens is not just a paper search tool — it's an **AI-powered research assistant** that helps you discover, analyze, and understand academic literature through a unified intelligent interface.

```
Research Question → AI Query Understanding → Multi-Source Search → Citation Network → AI Analysis
```

**Core capabilities:**

- **AI Smart Search** — describe your research interest in natural language, AI builds the optimal query
- **Citation Network Explorer** — interactive graph showing how papers cite each other, click to expand relationships
- **AI Paper Analysis** — instant summaries, detailed analysis, multi-paper comparison
- **Novelty Detection** — AI identifies research gaps and unexplored directions in a field

## Why PaperLens?

Every researcher knows the pain:

- **Information overload** — millions of papers published yearly, impossible to scan manually
- **Keyword mismatch** — traditional search fails when you don't know the exact terms
- **Platform switching** — jumping between PubMed, Google Scholar, Web of Science, and Scopus
- **No context** — search results lack citation data, OA links, and quick analysis
- **Manual drudgery** — copying DOIs one by one into reference managers

PaperLens solves all of these with a single interface.

## Features

### Search & Discovery

| Feature | Description |
|---------|-------------|
| **AI Smart Search** | Describe what you're looking for in natural language (Chinese or English), AI builds the optimal PubMed query |
| **Multi Data Source** | PubMed + OpenAlex (+ Google Scholar / Bing Academic / CNKI / Wanfang / VIP experimental), automatic deduplication, citation counts, and OA links |
| **Batch DOI Import** | Paste a list of DOIs and look them up in one click |
| **Advanced Filtering** | Filter by journal, field tags, year range, publication type |
| **In-result Sorting** | Sort by citations, date, or title without re-searching |

### AI Analysis

| Feature | Description |
|---------|-------------|
| **AI Summary** | One-paragraph summary of each paper — what, how, why it matters |
| **AI Detail** | Deep analysis across 7 dimensions: contribution, motivation, methods, results, limitations, context, future directions |
| **AI Compare** | Systematic comparison of multiple papers: approaches, innovations, complementarity, research gaps |
| **Novelty Detection** | AI identifies under-explored areas, contradictions in the literature, and promising research directions |

### Citation Intelligence

| Feature | Description |
|---------|-------------|
| **Citation Graph** | Interactive D3.js force-directed graph — zoom, pan, drag nodes, click to expand citation relationships |
| **Citation Expansion** | Click any node in the graph to load its citing and referenced papers |
| **Keyword Network** | Co-occurrence network visualization of keywords across search results |
| **Author Network** | Collaboration network visualization of co-authorship patterns |

### Export & Integration

| Feature | Description |
|---------|-------------|
| **Multi-format Export** | RIS (EndNote), BibTeX (LaTeX), CSV, EndNote XML |
| **PDF Download** | Direct OA PDF download with link verification |
| **Search History** | Persistent history with smart suggestions |
| **Dual AI Models** | Configure separate models for search (fast) and analysis (high-quality) |
| **Zotero Sync** | Direct sync papers to Zotero with collection selection |
| **Reading Recommendations** | Personalized paper recommendations based on reading history |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PaperLens Frontend                       │
│         Single-file HTML/CSS/JS + D3.js Graph               │
├─────────────────────────────────────────────────────────────┤
│                      Flask API Server                        │
├──────────┬──────────┬───────────┬───────────┬───────────────┤
│  Search  │ Citation │   AI      │  Export   │   Config      │
│  Engine  │ Network  │ Assistant │  Module   │   Manager     │
├──────────┴──────────┴───────────┴───────────┴───────────────┤
│              PubMed API  ·  OpenAlex API                     │
├─────────────────────────────────────────────────────────────┤
│         LLM Provider (DeepSeek / OpenAI / Claude / Ollama)  │
└─────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask |
| Frontend | HTML/CSS/JS (single-file, D3.js for citation graph) |
| Data Sources | PubMed E-utilities API, OpenAlex API |
| AI | OpenAI / DeepSeek / Anthropic / Ollama compatible API |
| Packaging | PyInstaller |

## Installation

```bash
# Clone
git clone https://github.com/vanthree31/PaperLens.git
cd PaperLens

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

The app opens in a native window (PyWebView) or your default browser.

### Build standalone executable

```bash
build.bat
# Output: dist/PaperLens.exe (Windows, no Python needed)
```

## Usage

### AI Smart Search
Describe your research interest in natural language:

```
Find recent papers on light-sheet microscopy for live cell imaging
搜索关于定量相位成像的最新综述
```

The AI analyzes your intent, builds an optimal PubMed query, and executes it.

### Citation Network Exploration
Click the **Citation Graph** button on any paper → see its citation relationships in an interactive graph → click nodes to expand citations.

### AI Paper Analysis
Select papers → click **AI Summary** / **AI Detail** / **AI Compare** / **Novelty Detection** → get instant analysis.

### Batch DOI Import
Click 📋 → paste DOIs (one per line) → query all at once.

### Chrome Extension
Install the Chrome extension to quickly lookup and collect papers while browsing:

1. Visit `chrome://extensions/`, enable "Developer mode"
2. Click "Load unpacked", select the `chrome-extension` folder
3. Visit any academic paper page, the extension auto-detects DOIs
4. Click the extension icon to view paper details and collect with one click

See [chrome-extension/README.md](chrome-extension/README.md) for details.

## Configuration

Open **Settings (⚙)** in the app:

| Setting | Description |
|---------|-------------|
| PubMed Email | Optional, increases API rate limit |
| PubMed API Key | Optional, from NCBI |
| AI Search Model | Fast model for query parsing (e.g., deepseek-chat) |
| AI Analysis Model | High-quality model for paper analysis (e.g., deepseek-reasoner) |
| HTTP/HTTPS Proxy | For restricted networks |

Config is stored in `%APPDATA%/PaperLens/` (Windows).

## Project Structure

```
PaperLens/
├── main.py              # Entry point (Flask + PyWebView)
├── server.py            # Backend API routes
├── search_engine.py     # PubMed + OpenAlex search engine
├── ai_assistant.py      # AI module (dual model support)
├── exporters.py         # RIS / BibTeX / CSV export
├── config.yaml          # Default config template
├── requirements.txt     # Python dependencies
├── build.bat            # One-click exe build (Windows)
├── static/
│   └── index.html       # Frontend (single-file app)
├── chrome-extension/    # Chrome extension
│   ├── manifest.json    # Extension config
│   ├── popup.html/js    # Popup window
│   ├── content.js       # DOI detection
│   ├── background.js    # Background service
│   └── icons/           # Extension icons
├── README.md
├── README.zh-CN.md
├── LICENSE
└── CONTRIBUTING.md
```

## Roadmap

### Implemented
- [x] AI Smart Search (natural language → PubMed query)
- [x] Multi data source aggregation (PubMed + OpenAlex + Google Scholar / CNKI / Wanfang / VIP)
- [x] AI Paper Analysis (summary / detail / compare / novelty)
- [x] Citation Network Graph (interactive D3.js visualization)
- [x] Floating Citation Graph (draggable windows with full AI toolbar)
- [x] Novelty Detection (AI identifies research gaps)
- [x] Batch DOI Import
- [x] Multi-format Export (RIS / BibTeX / CSV / EndNote XML)
- [x] Dual AI model configuration
- [x] Streaming output for AI analysis
- [x] User preference persistence (year range, sort, filters)
- [x] Search history with smart suggestions
- [x] Citation graph fullscreen with zoom state preservation
- [x] Graph zoom controls (reset, percentage display)
- [x] Export path configuration with direct save to disk
- [x] Data directory management
- [x] Settings reset to defaults
- [x] Local paper collections with custom groups
- [x] Chrome extension for DOI quick-lookup and collection
- [x] Collection management (create, delete with confirmation)
- [x] Keyword co-occurrence network visualization
- [x] Author collaboration network visualization

### Planned
- [x] Paper recommendation based on reading history
- [ ] RAG integration for literature review writing (complex, deferred)
- [x] Zotero direct sync
- [ ] Mendeley direct sync
- [ ] Collaborative paper collections

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## License

[MIT](LICENSE)

---

<p align="center">
  <b>PaperLens</b> — AI-Powered Research Assistant<br>
  See through the noise. Find what matters. Discover what's next.<br>
  Built for researchers, by researchers.
</p>
