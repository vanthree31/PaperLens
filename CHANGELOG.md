# Changelog

All notable changes to PaperLens will be documented in this file.

## [Unreleased]

### Added
- **CrossRef metadata cache** (`core/work_cache.py`): the post-search DOI enrichment queried CrossRef once per incomplete paper (~150 per search, ~2s each) and repeated the same lookups across searches. Now cached per DOI (30-day TTL, thread-safe, persisted to `~/.paperlens/crossref_work_cache.json`, capped at 20k entries). Pure speed: cached payloads are byte-identical to live responses (verified 11/11 DOIs field-by-field against live CrossRef).
- **Citation graph redesign (three-column lineage)**: new `CitationGraphV2` — referenced / current / citing three-column lineage layout (from the reviewed prototype), Top 10/20/all, flat / by-year / cluster arrangements (year bubbles expand on click), anchored physics drag, equal-ratio zoom, "+N more · expand all". The AI toolbar (summary / detail / novelty / export) is preserved. Floating mini-graphs keep the legacy renderer.
- **Keyword co-occurrence / author collaboration graph redesign**: new `NetworkGraphV2` renderer — three deterministic layouts (circular / concentric / cluster), anchored physics (drag snaps back to its anchor), equal-ratio wheel zoom, community detection (weighted label propagation) for coloring, dashed edges for cross-cluster links, hover neighbor highlight with click-to-pin, and a segmented toolbar (data / arrange / count / fit). Replaces the temporary rendering path where these two networks were drawn by the citation graph class.
- `/api/keyword-network` and `/api/author-network` now return the top 120 nodes by frequency (was: ad-hoc ≥2 filter / top 20-30), so the frontend Top-N control can switch without re-requesting.

### Changed
- **Faster search, no quality trade-off**: DOI enrichment concurrency 10 → 20 (CrossRef's public pool allows 50 req/s; this stays at ~13), connection-pooled `requests.Session` instead of bare `requests.get` (eliminates ~150 TCP/TLS handshakes per search), 429 backoff retry, and a `mailto:` User-Agent when any source has an email configured (polite pool, no rate limit). Measured on "deep learning microscopy" / 6 sources: **26.1s cold → 19.7s warm → ~15.5s with a fully warm cache** (was 30.8–40.2s). Nothing was removed — the enrichment fills title/authors/journal/abstract, which drive dedup, IF sorting and relatedness filtering, so cutting it would trade away result quality.

### Fixed
- **PubMed results carried other papers' DOIs (P0, silent data corruption)**: the XML parser used `article.findall(".//ArticleId")` and took the last `IdType="doi"` match — but `ReferenceList/Reference/ArticleIdList` uses the same element name, so the recursive search swept in every **reference's** IDs and the last reference's DOI overwrote the article's own. Measured 25–40% of PubMed results: e.g. PMID 35594500 ("Lipid-Nanoparticle-Based Delivery of CRISPR/Cas9") was tagged with `10.3390/vaccines9010065` (an mRNA vaccine paper). Impact: original-link/PDF buttons, exported RIS/BibTeX, citation graphs and DOI-based dedup all pointed at the wrong paper. Now scoped to `./PubmedData/ArticleIdList` (the article's own IDs) with an `ELocationID` fallback. After the fix: 0/10 mismatches (was 3/3), and title duplicates dropped from 8 groups to 0 — duplicates were a downstream symptom of DOIs being corrupted, which defeated dedup.
- **Missing `import os`** in `search_engine.py` — `SearchEngine.__init__` crashed with `NameError` (introduced with the online journal-metrics fallback).
- **Author search returning irrelevant results** ("搜某作者的论文全是无关结果") — three-layer fix:
  1. *Query understanding*: added the most common patterns that were silently unrecognized — "张伟的论文" (no verb), bare Chinese names ("周金华"), "papers by X" (full surname was truncated to given name), "Zhang Wei's papers", honorifics (王五**教授**的论文), "写的"; blacklist switched to substring matching; lookbehind prevents mid-word splits ("深度学习" sawed into "度学习" evading the blacklist).
  2. *Dispatch*: `/api/search` (keyword mode) never ran author detection at all — only the AI-search path did — and `engine.search`'s source dispatcher dropped the `author` parameter entirely, so the author name was sent to sources as a full-text keyword. Keyword mode now runs the same detection; the dispatcher routes the author name as the query subject (OpenAlex native author-ID lookup with `raw_author_name.search` fallback for Chinese names — 27k hits; PubMed `[au]` for Latin names; CNKI/Wanfang get the original Chinese name).
  3. *Result gate*: au results whose author list has zero name match are demoted to the end (not dropped). The relatedness filter already exempted au mode — it was the "22 filtered → 0 cached" killer when field arrived wrong.
- **Author + topic combined queries** ("张伟发表的CRISPR研究"): the extracted author was never applied to topic-search results, and `deduplicate_papers` reshuffled the ranked order into a "DOI group + title group" concatenation, silently destroying any upstream ordering. Now: author detection feeds a merged sort (author-hit first, then BM25 relevance), dedup preserves upstream order, and pypinyin-based variants let Chinese names match Latin signatures ("张伟" ↔ "Wei Zhang"/"Zhang W", 复姓 "欧阳文清" ↔ "Wenqing Ouyang"; full-name vs initials disambiguation keeps 张伟兴/张伟华 out of 张伟's results). `pypinyin` added to the project venv.
- **AI translation fallback never worked**: translator called `chat(prompt, max_tokens=100)` but `AIAssistant.chat` has no `max_tokens` parameter — TypeError on every call, silently degrading to dictionary-only translation.
- Citation graph reopening after viewing a network graph kept `legendCenterRow` hidden (row visibility was set but never restored).
- **OpenAIRE data source** (46th): EU open-access aggregation, 1M+ research products via Graph API `/graph/v1/researchProducts`. Complements CORE/DOAJ with European institutional repositories and theses.
- **Two-layer impact factor**: built-in official JCR value first, OpenAlex `2yr_mean_citedness` estimate as fallback (free, no key, tens of thousands of journals). Estimated values are marked with `*` in the UI and carry `impact_factor_src=openalex`.
- **`保留未收录` (keep unknown) toggle** for impact-factor filter — previously papers without an IF were silently dropped, making the filter behave as a 102-journal whitelist.
- **中科院分区「未收录」option** — the CAS table contains 102 entries (1区 92 / 2区 9 / 3区 1 / **4区 0**), so selecting 4区 always returned 0 results. Added an explicit `__unknown__` bucket plus a coverage hint icon.

### Fixed
- **12 dead source switches** — UI checkboxes existed and badges (CARSI/OA) were shown, but the flags were never sent in the search request. Refactored to a single source of truth `SOURCE_SWITCHES` in `search.js`, shared by both the normal and AI search paths.
- **Filter cache key collision** — the cache stores filtered+sorted results, but the key omitted journal/field/mesh_term/pub_type/IF/CAS/OA/affiliation/author/sort/max_results. Changing any of these returned stale results. Extracted `_compute_filter_seed()` as the shared single source.
- **Title-only relevance check** — relevance scoring only looked at the title (and had a DOI-substring bypass), so papers matching only in the abstract were treated as irrelevant. Now matches title OR abstract (title-only when the query field is explicitly `ti`).
- **Author field override** — a residual topic word (e.g. `张伟发表的CRISPR研究`) was force-passed as `field=au`, turning `CRISPR` into an author name. Now `field=au` is only forced when no residual topic word remains.
- **OpenAlex ISSN lookup** — `filter=issn:` requires the hyphenated form (`2156-7085`); the normalized form (`21567085`) returned 0 results, silently disabling the whole IF fallback layer.
- **OpenAIRE DOI selection** — an item can carry several `doi` PIDs (publisher DOI first, then the `10.48550/arXiv...` preprint DOI). The old loop let the last one win, breaking dedup, citation lookup and DOI links. Preprint DOIs are now deprioritized.
- **OpenAIRE junk entries** — EU project documents with no DOI/journal/authors leaked into results; added a quality floor (must have DOI, or journal+year, or authors+year).

### Changed
- Data-source count unified across README / README.zh-CN / ROADMAP: **46 retrieval entries = 29 independent upstream indexes + 17 CrossRef publisher slices** (37 enabled by default). Previously README said 43 and ROADMAP said 45.

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
