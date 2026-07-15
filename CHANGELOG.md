# Changelog

All notable changes to PaperLens will be documented in this file.

## [1.3.0] - 2026-07-06

### Added
- **13 New Data Sources**: DBLP (CS conferences), bioRxiv/medRxiv (preprints), AGRIS (agriculture), ACS Publications, Optica, IOP Publishing, AIP Publishing, RSC Publishing, Europe PMC, Springer Nature, Wiley, IEEE, Project MUSE — total now 26+ sources
- **Liquid Glass Effect**: iOS-style frosted glass UI with CSS backdrop-filter across all major components
- **AI Result Count**: moved to panel header for better visibility
- **Default Search Range**: 10 years default for better initial results

### Fixed
- **Search Stability (34 bugs)**: comprehensive audit fixing pub_type parameter, author search (OR queries, PubMed format conversion, OpenAlex filters), year filtering, journal extraction fallback
- **AI Search**: stream output marker display, truncated JSON output, result count selector error
- **History Dropdown**: height calculation, overlap with AI panel, click behavior (fills search box only, no auto-search)
- **CNKI Search**: browser instance reuse to avoid repeated captcha verification
- **OpenAlex**: journal URL length limit
- **Zotero**: status check now directly calls backend test API
- **Liquid Glass**: removed broken SVG filter causing purple tint and content blur

### Changed
- ROADMAP updated to v2.1 with search stability and UI optimization focus
- README simplified — removed implementation details from roadmap section

## [1.2.3] - 2026-06-09

### Added
- **OpenAlex API Key support** — OpenAlex now requires API key (free but mandatory). Without key: $0.10/day budget; with free key: $1/day (10x more). Added API key input field in settings panel with test button.
- **Semantic Scholar API Key support** — Added config entry and frontend UI for Semantic Scholar API key. Without key: 100 req/5min; with key: 1 req/sec.

### Changed
- Updated OpenAlex search, citation enrichment, and DOI lookup to include API key in all requests
- Updated server.py to pass API key for all direct OpenAlex API calls (citation graph, related papers, recommendations)
- Added `semantic_scholar` section to config.yaml with `enabled` and `api_key` fields

## [1.2.2] - 2026-06-09

### Fixed
- **i18n: Backend error messages now use error codes** — all API error responses use language-independent error codes (e.g., `no_query`, `paper_not_found`), frontend translates them via `te()` function
- **i18n: AI assistant error messages** — AI error responses now use `AI_ERROR:` prefix with error codes, frontend translates them via `teAI()` function
- **i18n: Default collection group name** — fixed Temporal Dead Zone bug where `collectionsData` referenced `LANGS` before initialization; default group now uses `t('defaultGroup')` when rendering
- **i18n: PDF download error detection** — error checks now use error codes instead of matching translated text strings

### Changed
- Added 20+ error code translations to both Chinese and English LANGS dictionaries
- Added `te()` helper function for translating backend error codes
- Added `teAI()` helper function for translating AI error responses

## [1.2.1] - 2026-06-09

### Added
- **New Data Sources**: Google Scholar (experimental), CNKI, Wanfang, VIP — all with β badge
- **Keyword Co-occurrence Network**: visualize keyword relationships across search results
- **Author Collaboration Network**: visualize co-authorship patterns
- **EndNote XML Export**: additional export format for Mendeley/EndNote direct import
- Missing i18n keys: `noOALink`, `analyzingResearchGaps`, `noDOILoadGraph`, `querying`, `query`
- `applyLang()` now updates all citation graph panel buttons, hints, and legend text dynamically

### Fixed
- **i18n: English version had hardcoded Chinese strings** — fixed 15+ untranslated Chinese text in JS (error messages, status text, button labels)
- **i18n: Citation graph overlay buttons broken** — static HTML used `${t(...)}` template literals that don't evaluate in HTML context; replaced with static text + `applyLang()` dynamic updates
- **i18n: English prompt mixed Chinese** — "compare" mode AI prompt contained Chinese text in English context
- **i18n: English translation used Chinese punctuation** — `enterGroupName` used Chinese colon `：` instead of `:`

## [1.2.0] - 2026-06-09

### Added
- **Chrome Extension**: DOI quick-lookup and paper collection while browsing academic websites
  - Auto-detect DOIs on any webpage (meta tags + regex matching)
  - One-click paper lookup via PaperLens API
  - One-click collection to PaperLens
  - Real-time sync notification after collection
- **Collection Management**: delete collection groups with confirmation dialog
  - Default collection group cannot be deleted
  - Deleting a group removes all items in it
  - Double confirmation before deletion
- **i18n Improvements**: comprehensive translation for all UI elements
  - Citation graph buttons (fullscreen, close, AI analysis, export)
  - Collection panel (refresh, delete group, new group)
  - AI analysis panel (copy, fullscreen, status messages)
  - Graph hints and legend text

### Fixed
- Collection data now auto-refreshes when opening collection panel
- Periodic polling (every 30 seconds) for collection data sync
- Chrome extension notifies frontend after successful collection

### Changed
- Added `DELETE /api/collections/groups` endpoint for collection group deletion
- Frontend uses translation functions for all dynamic content

## [1.1.0] - 2026-06-08

### Added
- **Local Paper Collections**: star papers to save, custom collection groups, collections sidebar panel
- **Floating Citation Graph**: new graph opens as draggable floating window with full toolbar (AI summary/detail/novelty/export)
- **Novelty Detection**: AI analysis mode that identifies research gaps, unexplored areas, and promising directions
- Fullscreen toggle for citation graph with zoom state preservation
- Reset zoom button in citation graph legend
- Zoom level percentage display in graph legend
- Click overlay background to close citation graph
- Markdown bold (`**text**`) rendering in AI analysis results

### Removed
- **Related Work Discovery**: removed due to persistent layout issues (nodes clustering together)

### Fixed
- "Open in new graph" no longer closes the current citation graph
- Floating graph toolbar now shows automatically after loading
- Citation graph expand: nodes no longer cluster — deterministic fan-shaped placement outside existing ring
- Citation graph zoom now centers on mouse cursor position
- Paper names fully display as zoom level increases (dynamic label length)
- Main content area no longer hidden behind status bar (added bottom padding)
- Graph panel fullscreen toggle with smooth CSS transition
- D3 data join key functions prevent node/link misalignment on expand
- Zoom behavior cleanup on graph reopen prevents duplicate handlers

### Changed
- Project repositioned from "Search Platform" to "AI-Powered Research Assistant"
- README.md and README.zh-CN.md fully rewritten with architecture diagram
- AI analysis prompt for "novelty" mode with 5 dimensions (both Chinese and English)

## [1.0.2] - 2026-06-08

### Added
- Interactive citation graph with D3.js force-directed layout
- Zoom, pan, and drag support in citation graph
- Click nodes to expand citation relationships dynamically
- Toolbar in citation graph: AI analysis, export, download, original link
- AI analysis results displayed within citation graph panel
- `/api/paper-by-doi` endpoint for single paper lookup by DOI

### Fixed
- Search button stuck on "searching" after results loaded
- Language switch not updating search result labels
- Default `year_to` in config.yaml (2025 → 2026)

## [1.0.1] - 2026-06-08

### Fixed
- Fixed `create_window()` icon parameter error in pywebview
- Fixed `os.sys` reference error in server.py
- Fixed `_last_keywords` not initialized in OpenAlexSearch
- Fixed `max_tokens` set to 384000 (now 4096)
- Fixed hardcoded year 2026 (now dynamic)
- Removed dead code `get_icon_path()` in main.py
- Moved `import json` to top level in server.py

### Added
- Copy button for AI analysis results
- Retry button on network errors
- Reset settings to default button
- Better error messages for PDF download failures

## [1.0.0] - 2026-06-08

### Added
- PubMed + OpenAlex dual-source search with automatic deduplication
- AI-powered natural language search (Chinese and English)
- AI paper analysis: summary, detailed analysis, and multi-paper comparison
- Streaming output for AI analysis
- Dual AI model configuration (separate models for search and analysis)
- Batch DOI import
- RIS, BibTeX, and CSV export
- Advanced filtering: journal, field tags, year range, publication type
- In-result sorting by citations, date, and title
- Search history with server-side persistence
- User preference persistence (year range, sort, filters)
- Dynamic placeholder with rotating suggestions
- Clickable suggestion chips
- OA paper PDF link verification
- Settings panel with proxy configuration
- XSS protection throughout
- Escape key to close modals
- Cross-page checkbox persistence
- Auto-detection of current year for date range
- Standalone Windows executable via PyInstaller
