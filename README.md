<p align="center">
  <h1 align="center">🔬 PaperLens</h1>
  <p align="center">An intelligent academic paper discovery platform that helps researchers see through the noise.</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/powered%20by-PubMed%20%2B%20OpenAlex-orange" alt="Data Sources">
  </p>
</p>

---

## Why PaperLens?

Every researcher knows the pain:

- **Information overload** — millions of papers published yearly, impossible to scan manually
- **Keyword mismatch** — traditional search fails when you don't know the exact terms
- **Platform switching** — jumping between PubMed, Google Scholar, Web of Science, and Scopus
- **No context** — search results lack citation data, OA links, and quick analysis
- **Manual drudgery** — copying DOIs one by one into reference managers

**PaperLens** solves these problems with a single, intelligent interface that combines multi-source search, AI-powered query understanding, and instant paper analysis.

## Features

| Feature | Description |
|---------|-------------|
| **AI Smart Search** | Describe what you're looking for in natural language (Chinese or English), and the AI builds the optimal PubMed query for you |
| **Dual Data Source** | PubMed + OpenAlex, automatic deduplication, citation counts, and OA links |
| **AI Paper Analysis** | Select papers and get instant summaries, detailed analysis, or multi-paper comparisons |
| **Batch DOI Import** | Paste a list of DOIs and look them up in one click |
| **Advanced Filtering** | Filter by journal, field tags, year range, publication type |
| **In-result Sorting** | Sort by citations, date, or title without re-searching |
| **Multi-format Export** | RIS (EndNote), BibTeX (LaTeX), CSV |
| **Search History** | Persistent history with smart suggestions |
| **Dual AI Models** | Configure separate models for search (fast) and analysis (high-quality) |

## Screenshots

> Coming soon — PRs welcome for screenshots!

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask |
| Frontend | HTML/CSS/JS (single-file, zero dependencies) |
| Data Sources | PubMed E-utilities API, OpenAlex API |
| AI | OpenAI / DeepSeek / Anthropic / Ollama compatible API |
| Packaging | PyInstaller |

## Installation

```bash
# Clone
git clone https://github.com/yourusername/PaperLens.git
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

### Basic Search
Type English keywords → get PubMed + OpenAlex results with citation data.

```
super-resolution microscopy[ti]
```

### AI Smart Search
Describe your research interest in natural language:

```
Find recent papers on light-sheet microscopy for live cell imaging
搜索关于定量相位成像的最新综述
```

The AI analyzes your intent, builds an optimal PubMed query, and executes it.

### Paper Analysis
Select papers → click **AI Summary** / **AI Detail** / **AI Compare** → get instant analysis.

### Batch DOI Import
Click 📋 → paste DOIs (one per line) → query all at once.

## Configuration

Open **Settings (⚙)** in the app:

| Setting | Description |
|---------|-------------|
| PubMed Email | Optional, increases API rate limit |
| PubMed API Key | Optional, from NCBI |
| AI Search Model | Fast model for query parsing (e.g., deepseek-chat) |
| AI Analysis Model | High-quality model for paper analysis (e.g., deepseek-reasoner) |
| HTTP/HTTPS Proxy | For restricted networks |

Config is stored in `%APPDATA%/PaperLens/` (Windows) or `~/.config/paperlens/` (Linux/Mac).

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
├── README.md
├── README.zh-CN.md
├── LICENSE
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## Roadmap

- [ ] PDF download for OA papers (integrated, not browser redirect)
- [ ] Citation graph visualization
- [ ] Paper recommendation based on reading history
- [ ] RAG integration for literature review assistance
- [ ] Zotero / Mendeley direct sync
- [ ] Multi-language UI
- [ ] Collaborative paper collections
- [ ] Chrome extension for DOI quick-lookup

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## License

[MIT](LICENSE)

---

<p align="center">
  <b>PaperLens</b> — See through the noise. Find what matters.<br>
  Built for researchers, by researchers.
</p>
