# Changelog

All notable changes to PaperLens will be documented in this file.

## [1.1.0] - 2026-06-08

### Added
- **Local Paper Collections**: star papers to save, custom collection groups, collections sidebar panel
- **Related Work Discovery**: find related papers through shared citation patterns (purple nodes in graph)
- **Novelty Detection**: AI analysis mode that identifies research gaps, unexplored areas, and promising directions
- Fullscreen toggle for citation graph with zoom state preservation
- Reset zoom button in citation graph legend
- Zoom level percentage display in graph legend
- Click overlay background to close citation graph
- Markdown bold (`**text**`) rendering in AI analysis results

### Fixed
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
