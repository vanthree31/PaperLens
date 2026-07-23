// ========== 搜索模块 ==========
// 只导入不可变值，可变状态通过 window.PaperLens 访问
import { API, pageSize, escapeHtml, debugLog } from './state.js';
import { t, te, teAI, safeSetDisabled, currentLang } from './i18n.js';

// 通过 getter 函数访问可变状态（确保始终读取最新值）
function getAllPapers() { return window.PaperLens.allPapers; }
function setAllPapers(v) { window.PaperLens.allPapers = v; }
function getCurrentPage() { return window.PaperLens.currentPage; }
function setCurrentPage(v) { window.PaperLens.currentPage = v; }
function getCheckedSet() { return window.PaperLens.checkedSet; }
function getCurrentSort() { return window.PaperLens.currentSort; }
function setCurrentSort(v) { window.PaperLens.currentSort = v; }
function getSortReversed() { return window.PaperLens._sortReversed; }
function setSortReversed(v) { window.PaperLens._sortReversed = v; }
function getLastAIQuery() { return window.PaperLens.lastAIQuery; }
function setLastAIQuery(v) { window.PaperLens.lastAIQuery = v; }
function getSearchMode() { return window.PaperLens._searchMode; }
function setSearchModeVal(v) { window.PaperLens._searchMode = v; }
function getSelectedJournals() { return window.PaperLens.selectedJournals; }
function getHistoryCache() { return window.PaperLens._historyCache; }

// 搜索相关状态
let _searchAbort = null;
let _aiSearchAbort = null;
let _suggestIdx = -1;

// 构建搜索请求体（统一数据源字段）
function buildSearchBody(overrides = {}) {
  const now = new Date().getFullYear();
  const yf = parseInt(document.getElementById("yearFrom").value);
  const yt = parseInt(document.getElementById("yearTo").value);
  return {
    year_from: isNaN(yf) ? now - 10 : yf,
    year_to: isNaN(yt) ? now : yt,
    sort: document.getElementById("sortBy").value,
    max_results: parseInt(document.getElementById("maxResults").value) || 50,
    use_pubmed: document.getElementById("usePubmed").checked,
    use_openalex: document.getElementById("useOpenalex").checked,
    use_semantic_scholar: document.getElementById("useSemanticScholar")?.checked || false,
    use_crossref: document.getElementById("useCrossref")?.checked ?? true,
    use_arxiv: document.getElementById("useArxiv")?.checked ?? true,
    use_sciencedirect: document.getElementById("useSciencedirect")?.checked ?? true,
    use_scopus: document.getElementById("useScopus")?.checked ?? true,
    use_jstor: document.getElementById("useJstor")?.checked ?? true,
    use_google_scholar: document.getElementById("useGoogleScholar")?.checked || false,
    use_bing_academic: document.getElementById("useBingAcademic")?.checked || false,
    use_cnki: document.getElementById("useCNKI")?.checked || false,
    use_wanfang: document.getElementById("useWanfang")?.checked || false,
    use_vip: document.getElementById("useVIP")?.checked || false,
    use_dblp: document.getElementById("useDblp")?.checked ?? true,
    use_biorxiv: document.getElementById("useBiorxiv")?.checked ?? true,
    use_agris: document.getElementById("useAgris")?.checked ?? true,
    use_acs: document.getElementById("useAcs")?.checked ?? true,
    use_optica: document.getElementById("useOptica")?.checked ?? true,
    use_iop: document.getElementById("useIop")?.checked ?? true,
    use_aip: document.getElementById("useAip")?.checked ?? true,
    use_rsc: document.getElementById("useRsc")?.checked ?? true,
    use_europepmc: document.getElementById("useEuropepmc")?.checked ?? true,
    use_springer: document.getElementById("useSpringer")?.checked ?? true,
    use_wiley: document.getElementById("useWiley")?.checked ?? true,
    use_ieee: document.getElementById("useIeee")?.checked ?? true,
    use_muse: document.getElementById("useMuse")?.checked ?? true,
    // [新增] CORE 和 Lens.org 数据源
    use_core: document.getElementById("useCore")?.checked ?? true,
    use_lens: document.getElementById("useLens")?.checked ?? true,
    use_lens_patents: document.getElementById("useLensPatents")?.checked ?? false,
    use_zotero_mcp: document.getElementById("useZoteroMcp")?.checked ?? false,
    use_zenodo: document.getElementById("useZenodo")?.checked ?? true,
    use_datacite: document.getElementById("useDatacite")?.checked ?? true,
    smart_routing: document.getElementById("smartRouting")?.checked ?? false,
    oa_only: document.getElementById("oaOnly")?.checked ?? false,
    affiliation: document.getElementById("filterAffiliation")?.value?.trim() || "",
    journal: getJournalFilter(),
    field: document.getElementById("filterField").value,
    pub_type: document.getElementById("filterPubType").value,
    force_refresh: window._forceRefresh || false,
    ...overrides,
  };
}

// 默认搜索建议
const DEFAULT_SUGGESTIONS = [
  "quantitative phase imaging review",
  "super-resolution microscopy 2024",
  "light-sheet microscopy live cell",
  "expansion microscopy",
  "单细胞测序最新进展",
  "AI in medical imaging",
  "CRISPR gene editing",
  "spatial transcriptomics",
  "deep learning microscopy",
  "organoid imaging",
  "fluorescent probe development",
  "adaptive optics microscopy",
];

// 获取 placeholder 文本
function getPlaceholderText() {
  const prefix = t("trySearch") + " ";
  // 优先用搜索历史
  const hist = getHistoryCache();
  if (hist.length > 0) {
    const item = hist[Math.floor(Math.random() * Math.min(hist.length, 10))];
    return `${prefix}${item.q}`;
  }
  // 没有历史则用默认建议
  const tip = DEFAULT_SUGGESTIONS[Math.floor(Math.random() * DEFAULT_SUGGESTIONS.length)];
  return `${prefix}${tip}`;
}

// 初始化搜索建议
function initSuggestions() {
  const bar = document.getElementById("suggestionBar");
  if (!bar) return;

  // 清除旧标签（保留"试试："文字）
  while (bar.children.length > 1) bar.removeChild(bar.lastChild);

  // 从历史和默认建议中各取一些混合
  const chips = [];
  const histChips = getHistoryCache().slice(0, 5).map(h => ({ text: h.q, fromHistory: true }));
  const defChips = [...DEFAULT_SUGGESTIONS]
    .sort(() => Math.random() - 0.5)
    .slice(0, 5)
    .map(t => ({ text: t, fromHistory: false }));

  // 交替混合
  const maxLen = Math.max(histChips.length, defChips.length);
  for (let i = 0; i < maxLen; i++) {
    if (histChips[i]) chips.push(histChips[i]);
    if (defChips[i]) chips.push(defChips[i]);
  }

  chips.slice(0, 8).forEach(item => {
    const chip = document.createElement("span");
    chip.className = "suggest-chip";
    chip.textContent = item.text;
    chip.title = item.text;
    chip.tabIndex = 0;
    chip.setAttribute("role", "button");
    const activate = () => {
      const input = document.getElementById("searchInput");
      if (input.value.trim() && input.value.trim() !== item.text) {
        window.showToast(t("searchSuggestionApplied"));
      }
      input.value = item.text;
      input.focus();
    };
    chip.onclick = activate;
    chip.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); } };
    bar.appendChild(chip);
  });

  // 动态 placeholder 轮播
  startPlaceholderRotation();
}

// placeholder 轮播
let _placeholderInterval = null;
function startPlaceholderRotation() {
  const input = document.getElementById("searchInput");
  if (!input) return;

  // 立即设置一次
  if (!input.value) input.placeholder = getPlaceholderText();

  // 每 5 秒轮换
  clearInterval(_placeholderInterval);
  _placeholderInterval = setInterval(() => {
    if (!input.value && document.activeElement !== input) {
      input.placeholder = getPlaceholderText();
    }
  }, 5000);
}

// 保存偏好（防抖）
let _prefTimer = null;
function savePreferences() {
  clearTimeout(_prefTimer);
  _prefTimer = setTimeout(async () => {
    // 收集数据源状态
    const sources = {};
    document.querySelectorAll('[id^="use"]').forEach(el => {
      if (el.id.startsWith('use') && el.type === 'checkbox') {
        sources[el.id] = el.checked;
      }
    });

    const prefs = {
      yearFrom: document.getElementById("yearFrom").value,
      yearTo: document.getElementById("yearTo").value,
      sortBy: document.getElementById("sortBy").value,
      maxResults: document.getElementById("maxResults").value,
      filterJournal: JSON.stringify(getSelectedJournals()),
      filterField: document.getElementById("filterField").value,
      filterPubType: document.getElementById("filterPubType").value,
      oaOnly: document.getElementById("oaOnly")?.checked ?? false,
      filterAffiliation: document.getElementById("filterAffiliation")?.value || "",
      lang: currentLang,
      dataSources: sources,
    };
    try {
      await fetch(`${API}/api/preferences`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(prefs),
      });
    } catch { /* 忽略 */ }
  }, 1000);
}

// 期刊多选标签
const JOURNAL_TAG_MAX_VISIBLE = 5;

function handleJournalKeydown(e) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    const input = e.target;
    const value = input.value.trim().replace(/,/g, '');
    const sj = getSelectedJournals();
    if (value && !sj.includes(value)) {
      sj.push(value);
      renderJournalTags();
    }
    input.value = '';
    // 隐藏模糊搜索下拉框
    const dropdown = document.getElementById('journalFuzzyDropdown');
    if (dropdown) dropdown.style.display = 'none';
  }
}

function renderJournalTags() {
  const container = document.getElementById('journalTags');
  if (!container) return;
  const input = document.getElementById('filterJournal');
  container.querySelectorAll('.journal-tag, .journal-tag-overflow').forEach(el => el.remove());
  const sj = getSelectedJournals();
  const visibleCount = Math.min(sj.length, JOURNAL_TAG_MAX_VISIBLE);
  for (let i = 0; i < visibleCount; i++) {
    const tag = document.createElement('span');
    tag.className = 'journal-tag';
    tag.innerHTML = `${escapeHtml(sj[i])} <span class="remove" onclick="removeJournal(${i})">×</span>`;
    container.insertBefore(tag, input);
  }
  // 超出部分显示 "+N" 按钮
  if (sj.length > JOURNAL_TAG_MAX_VISIBLE) {
    const overflow = sj.length - JOURNAL_TAG_MAX_VISIBLE;
    const btn = document.createElement('span');
    btn.className = 'journal-tag-overflow';
    btn.textContent = `+${overflow}`;
    btn.title = sj.slice(JOURNAL_TAG_MAX_VISIBLE).join(', ');
    btn.onclick = () => {
      // 展开显示全部标签
      container.querySelectorAll('.journal-tag-overflow').forEach(el => el.remove());
      sj.forEach((j, i) => {
        const tag = document.createElement('span');
        tag.className = 'journal-tag';
        tag.innerHTML = `${escapeHtml(j)} <span class="remove" onclick="removeJournal(${i})">×</span>`;
        container.insertBefore(tag, input);
      });
    };
    container.insertBefore(btn, input);
  }
  // 滚动到顶部
  const wrap = document.getElementById('journalTagsWrap');
  if (wrap) wrap.scrollTop = 0;
}

function removeJournal(index) {
  getSelectedJournals().splice(index, 1);
  renderJournalTags();
  savePreferences();
}

function getJournalFilter() {
  const sj = getSelectedJournals();
  return sj.length > 0 ? sj.join(',') : '';
}

// ========== 期刊分组筛选 ==========

const JOURNAL_GROUPS = {
  biomed: [
    "Nature Medicine", "Nature Biotechnology", "Nature Genetics", "Nature Reviews Drug Discovery",
    "Nature Reviews Molecular Cell Biology", "Nature Immunology", "Nature Neuroscience",
    "Cell", "Cell Stem Cell", "Cell Reports", "Molecular Cell",
    "The Lancet", "The New England Journal of Medicine", "JAMA",
    "BMJ", "The Lancet Oncology", "The Lancet Neurology",
    "Journal of Clinical Oncology", "Blood", "Circulation",
    "Nature Structural and Molecular Biology", "Nature Chemical Biology",
  ],
  cs: [
    "ACM Computing Surveys", "IEEE Transactions on Pattern Analysis and Machine Intelligence",
    "IEEE Transactions on Neural Networks and Learning Systems",
    "International Journal of Computer Vision", "Neural Computation",
    "Machine Learning", "Journal of Machine Learning Research",
    "IEEE Transactions on Information Theory", "ACM Transactions on Graphics",
    "IEEE Transactions on Visualization and Computer Graphics",
    "Artificial Intelligence", "Journal of Artificial Intelligence Research",
    "Knowledge-Based Systems", "Expert Systems with Applications",
    "Neurocomputing", "Pattern Recognition",
  ],
  materials: [
    "Advanced Materials", "Advanced Functional Materials", "Advanced Energy Materials",
    "ACS Nano", "Nano Letters", "Nature Materials", "Nature Nanotechnology",
    "Chemistry of Materials", "Journal of the American Chemical Society",
    "Angewandte Chemie", "Chemical Reviews", "Chemical Society Reviews",
    "Materials Today", "Progress in Materials Science",
    "Carbon", "Small", "Nanoscale",
  ],
  optics: [
    "Optica", "Optics Letters", "Optics Express", "Applied Optics",
    "Journal of Lightwave Technology", "IEEE Photonics Technology Letters",
    "Nature Photonics", "Laser & Photonics Reviews",
    "Journal of the Optical Society of America A",
    "Journal of the Optical Society of America B", "Photonics Research",
  ],
  nature: [
    "Nature", "Nature Biotechnology", "Nature Genetics", "Nature Medicine",
    "Nature Nanotechnology", "Nature Photonics", "Nature Materials",
    "Nature Reviews Drug Discovery", "Nature Reviews Molecular Cell Biology",
    "Nature Immunology", "Nature Neuroscience", "Nature Chemical Biology",
    "Nature Structural and Molecular Biology", "Nature Methods",
    "Nature Communications", "Nature Physics", "Nature Chemistry",
    "Nature Energy", "Nature Catalysis", "Nature Reviews Chemistry",
    "Nature Reviews Physics", "Nature Electronics", "Nature Sustainability",
    "Nature Aging", "Nature Cell Biology", "Nature Chemical Engineering",
    "Nature Computational Science", "Nature Reviews Bioengineering",
    "Nature Reviews Electrical Engineering", "Nature Reviews Microbiology",
    "Nature Reviews Gastroenterology & Hepatology",
    "Nature Reviews Cardiology", "Nature Reviews Nephrology",
    "Nature Reviews Endocrinology", "Nature Mental Health",
    "Nature Biomedical Engineering",
  ],
  cell: [
    "Cell", "Cell Stem Cell", "Cell Reports", "Cell Systems", "Cell Genomics",
    "Cell Chemical Biology", "Cell Host & Microbe", "Cell Metabolism",
    "Cell Death & Differentiation", "Cell Death & Disease",
    "Molecular Cell", "Immunity", "Neuron", "Cancer Cell",
    "Current Biology", "Structure", "Stem Cell Reports",
    "Cell Reports Medicine", "Cell Reports Methods", "iScience",
  ],
  science: [
    "Science", "Science Advances", "Science Robotics",
    "Science Immunology", "Science Translational Medicine",
    "Science Signaling",
  ],
  energy: [
    "Joule", "JACS Au", "Nature Energy", "Energy & Environmental Science",
    "Advanced Energy Materials", "Nano Energy", "Applied Energy",
    "Energy Storage Materials", "ACS Energy Letters",
    "Chemical Engineering Journal", "Nature Reviews Clean Technology",
  ],
};

// 批量添加期刊（去重）
function addJournalsBatch(journals) {
  const sj = getSelectedJournals();
  let added = 0;
  for (const j of journals) {
    if (!sj.includes(j)) {
      sj.push(j);
      added++;
    }
  }
  if (added > 0) {
    renderJournalTags();
    renderJournalGroupUI();
    savePreferences();
  }
  return added;
}

// 添加整个期刊分组
function addJournalGroup(groupName) {
  const journals = JOURNAL_GROUPS[groupName];
  if (!journals) return;
  addJournalsBatch(journals);
}

// 清空所有期刊
function clearAllJournals() {
  getSelectedJournals().length = 0;
  renderJournalTags();
  renderJournalGroupUI();
  savePreferences();
}

// 更新已选期刊数量显示
function updateJournalCount() {
  const countEl = document.getElementById('journalCount');
  if (!countEl) return;
  const count = getSelectedJournals().length;
  countEl.textContent = count > 0 ? `${count}` : '';
  countEl.style.display = count > 0 ? 'inline-flex' : 'none';
}

// 渲染期刊分组按钮 UI
function renderJournalGroupUI() {
  const container = document.getElementById('journalGroupButtons');
  if (!container) return;
  const count = getSelectedJournals().length;

  const countHtml = `<span class="journal-count-badge" id="journalCount" style="display:${count > 0 ? 'inline-flex' : 'none'}">${count}</span>`;

  let btnsHtml = '';
  for (const name of Object.keys(JOURNAL_GROUPS)) {
    const gCount = (JOURNAL_GROUPS[name] || []).length;
    btnsHtml += `<button class="journal-group-btn" onclick="addJournalGroup('${name}')" title="${name} (${gCount} journals)">${name} (${gCount})</button>`;
  }

  const clearHtml = count > 0
    ? `<button class="journal-clear-btn" onclick="clearAllJournals()" title="${t("journalClearAll")}">${t("journalClearAll")}</button>`
    : '';

  container.innerHTML = `${countHtml}<span style="font-size:12px;color:var(--text-secondary);margin-right:2px">${t("journalGroups")}</span>${btnsHtml}${clearHtml}`;
  updateJournalCount();
}

// 模糊搜索：输入时显示匹配的期刊下拉
function setupJournalFuzzySearch() {
  const input = document.getElementById('filterJournal');
  if (!input) return;

  const dl = document.getElementById('journalGroupList');
  if (dl) dl.remove();

  let dropdown = document.getElementById('journalFuzzyDropdown');
  if (!dropdown) {
    dropdown = document.createElement('div');
    dropdown.id = 'journalFuzzyDropdown';
    dropdown.className = 'journal-fuzzy-dropdown';
    // 将 dropdown 放到 wrapper 上，避免被 overflow 裁剪
    const wrap = document.getElementById('journalTagsWrap');
    if (wrap) {
      wrap.style.position = 'relative';
      wrap.appendChild(dropdown);
    }
  }

  const allJournals = [];
  for (const journals of Object.values(JOURNAL_GROUPS)) {
    for (const j of journals) {
      if (!allJournals.includes(j)) allJournals.push(j);
    }
  }

  let debounceTimer = null;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const val = input.value.trim().toLowerCase();
      if (!val) { dropdown.style.display = 'none'; return; }

      const sj = getSelectedJournals();
      const matches = allJournals.filter(j =>
        j.toLowerCase().includes(val) && !sj.includes(j)
      ).slice(0, 10);

      if (!matches.length) { dropdown.style.display = 'none'; return; }

      dropdown.innerHTML = '';
      for (const j of matches) {
        const div = document.createElement('div');
        div.className = 'journal-fuzzy-item';
        div.textContent = j;
        div.addEventListener('mousedown', (e) => {
          e.preventDefault();
          addJournalsBatch([j]);
          input.value = '';
          dropdown.style.display = 'none';
        });
        dropdown.appendChild(div);
      }
      dropdown.style.display = 'block';
    }, 150);
  });

  input.addEventListener('blur', () => {
    setTimeout(() => { dropdown.style.display = 'none'; }, 150);
  });

  input.addEventListener('focus', () => {
    if (input.value.trim()) {
      input.dispatchEvent(new Event('input'));
    }
  });
}

// Tab 补全 + 搜索建议下拉
function handleSearchKeydown(e) {
  const input = document.getElementById("searchInput");
  const dd = document.getElementById("suggestDropdown");

  if (e.key === "Enter") {
    dd.classList.remove("show");
    doSmartSearch();
    return;
  }

  if (e.key === "Tab") {
    e.preventDefault();
    const val = input.value.trim();
    if (!val) {
      // 空输入 → 切换搜索模式
      toggleSearchMode();
      return;
    }
    return;
  }

  if (dd.classList.contains("show")) {
    const items = dd.querySelectorAll(".history-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      _suggestIdx = Math.min(_suggestIdx + 1, items.length - 1);
      updateSuggestHighlight(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      _suggestIdx = Math.max(_suggestIdx - 1, 0);
      updateSuggestHighlight(items);
    } else if (e.key === "Escape") {
      dd.classList.remove("show");
    }
  }
}

function getAllSuggestions() {
  const hist = getHistoryCache().map(h => h.q);
  return [...new Set([...hist, ...DEFAULT_SUGGESTIONS])];
}

function showSuggestDropdown(val) {
  // 已移除：智能建议下拉框不再使用
}

function updateSuggestHighlight(items) {
  items.forEach((el, i) => el.style.background = i === _suggestIdx ? "var(--bg)" : "");
  if (items[_suggestIdx]) {
    document.getElementById("searchInput").value = items[_suggestIdx].querySelector(".hq").textContent;
  }
}

// ========== 智能搜索建议 ==========

/**
 * 分析查询并生成智能搜索建议
 * @param {string} query - 用户输入的查询
 * @returns {Array<{type: string, message: string, action?: string, actionLabel?: string}>}
 */
function generateSearchSuggestions(query) {
  if (!query || !query.trim()) return [];
  const q = query.trim();
  const suggestions = [];

  // 1. 检测 DOI 格式
  const doiPattern = /^10\.\d{4,}\//;
  if (doiPattern.test(q)) {
    suggestions.push({
      type: 'doi',
      message: t('suggestDOIMsg'),
      action: `window.open('https://doi.org/${encodeURIComponent(q)}', '_blank')`,
      actionLabel: t('openOriginal'),
    });
  }

  // 2. 检测中文查询
  const chineseChars = q.match(/[一-鿿]/g);
  const chineseRatio = chineseChars ? chineseChars.length / q.length : 0;
  if (chineseRatio > 0.3) {
    suggestions.push({
      type: 'chinese',
      message: t('suggestChineseMsg'),
      actionLabel: t('switchToEnglish'),
    });
  }

  // 3. 检测过长查询（建议简化）
  const wordCount = q.split(/\s+/).length;
  if (wordCount > 6) {
    const simplified = q.split(/\s+/).slice(0, 3).join(' ');
    suggestions.push({
      type: 'simplify',
      message: t('suggestSimplifyMsg'),
      action: `document.getElementById('searchInput').value=${JSON.stringify(simplified)}; window.doSmartSearch();`,
      actionLabel: `${t('trySimplified')} "${escapeHtml(simplified)}"`,
    });
  }

  // 4. 检测作者名模式
  // 支持格式：
  // - 英文名：John Smith, J. Smith, J Smith, John Michael Smith
  // - 中文名：周金华, 张伟
  // - 混合：Jinhua Zhou, Zhou Jinhua
  const isAuthorName = (input) => {
    const trimmed = input.trim();

    // 中文名检测：2-4个汉字，无空格
    if (/^[一-鿿]{2,4}$/.test(trimmed)) {
      return true;
    }

    // 英文名检测
    const parts = trimmed.split(/\s+/);

    // 至少 2 个词，最多 4 个词
    if (parts.length < 2 || parts.length > 4) {
      return false;
    }

    // 每个词应该是：
    // - 首字母大写的单词（如 John, Smith）
    // - 缩写（如 J., J）
    // - 小写的姓氏前缀（如 van, von, de, der）
    const namePattern = /^[A-Z][a-z]+$|^[A-Z]\.?$|^[a-z]{1,3}$/;
    const validParts = parts.filter(p => namePattern.test(p));

    // 至少 70% 的部分应该匹配名称模式
    if (validParts.length >= parts.length * 0.7) {
      // 排除明显的非作者名（如常见短语）
      const nonAuthorWords = ['the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'was', 'were', 'been', 'have', 'has', 'had', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'shall'];
      const lowerParts = parts.map(p => p.toLowerCase());
      const hasNonAuthor = nonAuthorWords.some(w => lowerParts.includes(w));
      if (!hasNonAuthor) {
        return true;
      }
    }

    return false;
  };

  if (isAuthorName(q)) {
    suggestions.push({
      type: 'author',
      message: t('suggestAuthorMsg'),
      action: `document.getElementById('filterField').value='au'; window.doSmartSearch();`,
      actionLabel: t('searchByAuthor'),
    });
  }

  // 5. 检测特殊字符（可能输入错误）
  const specialChars = q.match(/[^a-zA-Z0-9一-鿿\s\-_.:\/]/g);
  if (specialChars && specialChars.length > 0) {
    const cleaned = q.replace(/[^a-zA-Z0-9一-鿿\s]/g, '').trim();
    if (cleaned.length > 0) {
      suggestions.push({
        type: 'typo',
        message: t('suggestTypoMsg'),
        action: `document.getElementById('searchInput').value=${JSON.stringify(cleaned)}; window.doSmartSearch();`,
        actionLabel: `${t('searchCleaned')} "${escapeHtml(cleaned)}"`,
      });
    }
  }

  // 6. 少结果时的通用建议（由调用方传入结果数判断）
  // 这个在 renderResults 中单独处理

  return suggestions;
}

/**
 * 生成简化后的查询建议
 * @param {string} query - 原始查询
 * @returns {string|null} 简化后的查询，如果没有可简化的则返回 null
 */
function getSimplifiedQuery(query) {
  if (!query) return null;
  const q = query.trim();
  const words = q.split(/\s+/);

  // 策略1: 去掉停用词
  const stopWords = ['the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'or', 'is', 'are', 'was', 'were',
    '最新', '的', '了', '在', '是', '和', '与', '研究', '综述'];
  const filtered = words.filter(w => !stopWords.includes(w.toLowerCase()));
  if (filtered.length >= 2 && filtered.length < words.length) {
    return filtered.join(' ');
  }

  // 策略2: 取前3个关键词
  if (words.length > 3) {
    return words.slice(0, 3).join(' ');
  }

  return null;
}

// 搜索模式
function setSearchMode(mode) {
  localStorage.setItem("searchMode", mode);
  window.PaperLens._searchMode = mode;
  document.getElementById("modeNormal").classList.toggle("active", mode === "normal");
  document.getElementById("modeAI").classList.toggle("active", mode === "ai");
}

function detectNeedAI(input) {
  if (/\[(?:ti|tiab|au|ta|tw|mh|pt|pdat)\]/i.test(input)) return false;
  // 只有包含多个关键词 + 布尔运算符才算普通检索（避免单个 "not"/"or" 被误判）
  if (/\b\w+\s+(AND|OR|NOT)\s+\w+\b/i.test(input)) return false;
  if (/^\d+$/.test(input)) return false;
  if (/^10\.\d{4,}\//.test(input)) return false;
  if (/[一-鿿]/.test(input)) return true;
  const nlWords = ['find','search','look for','latest','recent','review','survey','about','regarding','concerning','how','what','which','papers on','articles on','studies on','research on'];
  const lower = input.toLowerCase();
  for (const w of nlWords) { if (lower.includes(w)) return true; }
  if (input.split(/\s+/).length > 5) return true;
  return false;
}

// 骨架屏：搜索开始时显示占位卡片
function showSkeleton(count = 4) {
  const div = document.getElementById("results");
  if (!div) return;
  let html = '<div class="paper-list">';
  for (let i = 0; i < count; i++) {
    html += `
    <div class="skeleton-card" style="--stagger-delay: ${i * 60}ms">
      <div class="skeleton-bone skeleton-checkbox"></div>
      <div class="skeleton-content">
        <div class="skeleton-bone skeleton-title"></div>
        <div class="skeleton-bone skeleton-title-short"></div>
        <div class="skeleton-bone skeleton-meta"></div>
        <div class="skeleton-bone skeleton-meta-short"></div>
      </div>
      <div class="skeleton-actions">
        <div class="skeleton-bone skeleton-action"></div>
        <div class="skeleton-bone skeleton-action"></div>
        <div class="skeleton-bone skeleton-action"></div>
      </div>
    </div>`;
  }
  html += '</div>';
  div.innerHTML = html;
}

// 智能搜索
async function doSmartSearch(forceRefresh = false) {
  if (doSmartSearch._running) return;
  doSmartSearch._running = true;
  const input = document.getElementById("searchInput");
  let query = input.value.trim();
  if (!query) { input.focus(); window.showToast(t("enterQuery")); return; }
  safeSetDisabled("searchBtn", true);
  document.getElementById("results").classList.add("loading");
  showSkeleton();
  // 保存 forceRefresh 状态供子函数使用
  window._forceRefresh = forceRefresh;
  try {
    if (window.PaperLens._searchMode === "ai") await doAISearch();
    else await doSearch();
  } finally {
    safeSetDisabled("searchBtn", false);
    const btn = document.getElementById("searchBtn");
    if (btn) btn.textContent = t("search");
    document.getElementById("results").classList.remove("loading");
    doSmartSearch._running = false;
    window._forceRefresh = false;
  }
}

// 普通检索（流式）
async function doSearch() {
  const query = document.getElementById("searchInput").value.trim();
  if (!query) return;
  // [Fix] 统一 abort 逻辑：启动普通搜索时取消进行中的 AI 搜索
  if (_aiSearchAbort) { _aiSearchAbort.abort(); _aiSearchAbort = null; }
  safeSetDisabled("searchBtn", true);
  const btn = document.getElementById("searchBtn");
  if (btn) btn.textContent = t("searching");
  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) cancelBtn.style.display = "inline-block";
  window.setStatus(t("searching"));
  const modeEl = document.getElementById("searchMode");
  if (modeEl) modeEl.innerHTML = `<span style="color:#2563eb">${t("normalSearchBadge")}</span>`;

  const body = buildSearchBody({ query });

  try {
    _searchAbort = new AbortController();
    const r = await fetch(`${API}/api/search/stream`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
      signal: _searchAbort.signal,
    });
    if (!r.ok) {
      // 流式端点失败，回退到非流式
      console.warn("[SEARCH] Stream endpoint failed, falling back to non-stream");
      await _doSearchFallback(query, body);
      return;
    }

    // 流式读取 SSE 事件
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let searchData = null;
    let accumulatedPapers = [];
    let sourceDiag = [];  // 搜索诊断数据

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});

      // 解析 SSE 行
      const lines = buffer.split("\n");
      buffer = lines.pop(); // 保留未完成的行

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const jsonStr = line.substring(6);
        if (!jsonStr.trim()) continue;

        try {
          const event = JSON.parse(jsonStr);
          if (event.type === "source_done") {
            sourceDiag.push({name: event.source, status: "ok", count: event.count, duration: event.duration || 0});
            const durationStr = event.duration ? ` (${event.duration}s)` : "";
            window.setStatus(`✓ ${event.source} ${event.count}篇 ${durationStr} (${event.completed}/${event.total})`);
            debugLog(`[SEARCH] ${event.source} done: ${event.count} papers (${event.completed}/${event.total}) ${event.duration}s`);
            if (event.duration !== undefined) {
              updateSourceTimingIndicator(event.source, event.duration, "ok");
            }
            // 渐进渲染：每个源完成就更新结果列表
            if (accumulatedPapers.length > 0) {
              window.PaperLens.allPapers = [...accumulatedPapers];
              window.PaperLens._searchQuery = query;
              window.renderResults();
            }
          } else if (event.type === "source_error") {
            sourceDiag.push({name: event.source, status: "error", count: 0, duration: event.duration || 0, error: event.error});
            const durationStr = event.duration ? ` (${event.duration}s)` : "";
            debugLog(`[SEARCH] ${event.source} error: ${event.error} (${event.completed}/${event.total})${durationStr}`);
            if (event.duration !== undefined) {
              const errorStatus = event.error.includes("超时") ? "timeout" : "error";
              updateSourceTimingIndicator(event.source, event.duration, errorStatus);
            }
          } else if (event.type === "result_batch") {
            // 分批论文数据，累积并立即渲染
            if (event.papers && event.papers.length > 0) {
              accumulatedPapers.push(...event.papers);
              // 渐进渲染：每收到一批就更新界面
              window.PaperLens.allPapers = [...accumulatedPapers];
              window.PaperLens._searchQuery = query;
              window.renderResults();
            }
          } else if (event.type === "result") {
            // 最终结果：合并累积的论文与元数据
            event.papers = event.papers && event.papers.length > 0 ? event.papers : accumulatedPapers;
            searchData = event;
            window.PaperLens._lastSearchDiag = sourceDiag;  // 诊断数据
          } else if (event.type === "error") {
            window.showToast(te(event.error) || t("searchFailed"));
            window.setStatus(t("searchFailed"));
            window.renderResults(); // 清除骨架屏，显示空状态
            return;
          }
        } catch (e) {
          debugLog(`[SEARCH] SSE parse error: ${e.message}`);
        }
      }
    }

    if (!searchData) {
      window.showToast(t("searchFailed"));
      window.setStatus(t("searchFailed"));
      window.renderResults(); // 清除骨架屏，显示空状态
      return;
    }

    // 处理最终结果
    window.PaperLens.allPapers = searchData.papers || [];
    window.PaperLens._originalPapers = [...(searchData.papers || [])];
    window.PaperLens.currentPage = 1;
    getCheckedSet().clear();
    window.PaperLens._sortReversed = false;
    // 应用下拉框排序：重置 currentSort 后调用 sortPapers，避免 toggle 逻辑误触发
    const _sortBy = document.getElementById("sortBy").value;
    if (_sortBy && _sortBy !== "relevance") {
      window.PaperLens.currentSort = "relevance";
      window.sortPapers(_sortBy);
    } else {
      window.PaperLens.currentSort = "relevance";
      window.renderResults();
      window.renderPagination();
    }
    // 构建状态信息（含总耗时）
    let statusText = `${t("totalPapers")} ${searchData.total || 0} ${t("papers")}`;
    if (searchData.timing) {
      const totalDuration = Object.values(searchData.timing)
        .reduce((sum, t) => sum + (t.duration || 0), 0);
      const timeoutCount = Object.values(searchData.timing)
        .filter(t => t.status === "timeout").length;
      if (totalDuration > 0) {
        statusText += ` (${totalDuration.toFixed(1)}s)`;
      }
      if (timeoutCount > 0) {
        statusText += ` [${timeoutCount} ${t("searchTimeoutCount")}]`;
      }
    }
    window.setStatus(statusText);
    // 保存搜索历史
    if (typeof window.saveHistory === 'function') window.saveHistory(query, searchData.total || 0);
    // 显示数据源错误提示
    if (searchData.errors && searchData.errors.length > 0) {
      window.showToast(`${t("searchTips")}\n${searchData.errors.join("; ")}`, 8000);
    }
    // 刷新数据源健康状态（独立 try/catch，失败不影响搜索结果）
    try {
      if (typeof window.fetchSourceHealth === 'function') {
        const health = await window.fetchSourceHealth();
        if (health && typeof window.updateSourceIndicators === 'function') {
          window.updateSourceIndicators(health);
        }
      }
    } catch { /* 忽略 health 更新失败 */ }
  } catch (e) {
    if (e.name === 'AbortError') {
      window.setStatus(t("searchCancelled"));
      window.renderResults(); // 清除骨架屏，显示空状态
    } else {
      // 网络错误时回退到非流式
      debugLog(`[SEARCH] Stream fetch/read error: ${e.name}: ${e.message}, falling back to non-stream`);
      console.warn(`[SEARCH] Stream error: ${e.message}, falling back to non-stream`);
      await _doSearchFallback(query, body);
    }
  } finally {
    safeSetDisabled("searchBtn", false);
    const btn = document.getElementById("searchBtn");
    if (btn) btn.textContent = t("search");
    const cancelBtn = document.getElementById("cancelBtn");
    if (cancelBtn) cancelBtn.style.display = "none";
    _searchAbort = null;
  }
}

// 非流式搜索 fallback（流式端点不可用时使用）
async function _doSearchFallback(query, body) {
  try {
    window.setStatus(t("searching"));
    const r = await fetch(`${API}/api/search`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
      signal: _searchAbort?.signal,
    });
    if (!r.ok) {
      const errorData = await r.json().catch(() => ({}));
      window.showToast(te(errorData.error) || t("searchFailed"));
      if (getAllPapers().length === 0) {
        window.setStatus(t("searchFailed"));
        window.renderResults(); // 清除骨架屏，显示空状态
      }
      return;
    }
    const data = await r.json();
    window.PaperLens.allPapers = data.papers || [];
    window.PaperLens._originalPapers = [...(data.papers || [])];
    window.PaperLens.currentPage = 1;
    getCheckedSet().clear();
    window.PaperLens._sortReversed = false;
    // 应用下拉框排序：重置 currentSort 后调用 sortPapers，避免 toggle 逻辑误触发
    const _sortBy = document.getElementById("sortBy").value;
    if (_sortBy && _sortBy !== "relevance") {
      window.PaperLens.currentSort = "relevance";
      window.sortPapers(_sortBy);
    } else {
      window.PaperLens.currentSort = "relevance";
      window.renderResults();
      window.renderPagination();
    }
    // 构建状态信息（含总耗时）
    let statusText = `${t("totalPapers")} ${data.total || 0} ${t("papers")}`;
    if (data.timing) {
      const totalDuration = Object.values(data.timing)
        .reduce((sum, t) => sum + (t.duration || 0), 0);
      const timeoutCount = Object.values(data.timing)
        .filter(t => t.status === "timeout").length;
      if (totalDuration > 0) {
        statusText += ` (${totalDuration.toFixed(1)}s)`;
      }
      if (timeoutCount > 0) {
        statusText += ` [${timeoutCount} ${t("searchTimeoutCount")}]`;
      }
      // 更新每个源的指示器
      for (const [sourceName, info] of Object.entries(data.timing)) {
        if (window.updateSourceTimingIndicator) {
          window.updateSourceTimingIndicator(sourceName, info.duration, info.status);
        }
      }
    }
    window.setStatus(statusText);
    if (typeof window.saveHistory === 'function') window.saveHistory(query, data.total || 0);
    if (data.errors && data.errors.length > 0) {
      window.showToast(`${t("searchTips")}\n${data.errors.join("; ")}`, 8000);
    }
    // 刷新数据源健康状态（独立 try/catch，失败不影响搜索结果）
    try {
      if (typeof window.fetchSourceHealth === 'function') {
        const health = await window.fetchSourceHealth();
        if (health && typeof window.updateSourceIndicators === 'function') {
          window.updateSourceIndicators(health);
        }
      }
    } catch { /* 忽略 */ }
  } catch (e) {
    if (e.name !== 'AbortError') {
      debugLog(`[SEARCH] Fallback fetch failed: ${e.name}: ${e.message}`);
      console.error(`[SEARCH] Fallback fetch error:`, e);
      window.showToast(`${t("networkError")}: ${e.message}`);
      window.setStatus(t("networkErrorRetry"), "network_error");
      window.renderResults(); // 清除骨架屏，显示空状态
    }
  }
}

// 取消搜索
function cancelAISearch() {
  if (_searchAbort) _searchAbort.abort();
  if (_aiSearchAbort) _aiSearchAbort.abort();
}

// AI 智能检索
async function doAISearch() {
  const query = document.getElementById("searchInput").value.trim();
  if (!query) return;
  // [Fix] 统一 abort 逻辑：启动 AI 搜索时取消进行中的普通搜索
  if (_searchAbort) { _searchAbort.abort(); _searchAbort = null; }
  safeSetDisabled("searchBtn", true);
  const btn = document.getElementById("searchBtn");
  if (btn) btn.textContent = t("aiAnalyzing");
  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) cancelBtn.style.display = "inline-block";
  const modeEl = document.getElementById("searchMode");
  if (modeEl) modeEl.innerHTML = `<span style="color:#8b5cf6">${t("aiSearchModeBadge")}</span>`;

  // 显示 AI Panel 用于流式输出
  const aiPanel = document.getElementById("aiPanel");
  const aiContent = document.getElementById("aiContent");
  aiPanel.classList.add("show");
  aiContent.innerHTML = `<div class="ai-think-content" id="aiSearchStreamText"></div>`;
  const streamEl = document.getElementById("aiSearchStreamText");

  // 计时器
  let elapsed = 0;
  const timer = setInterval(() => {
    elapsed++;
    window.setStatus(`${t("aiWaiting")} ${elapsed} ${t("seconds")}`);
  }, 1000);

  // AI 搜索：只在用户明确指定年份时才发送，否则让 AI 决定
  const yearFromVal = parseInt(document.getElementById("yearFrom").value);
  const yearToVal = parseInt(document.getElementById("yearTo").value);
  const body = {
    query,
    stream: true,
    lang: currentLang,
    ...(yearFromVal ? { year_from: yearFromVal } : {}),
    ...(yearToVal ? { year_to: yearToVal } : {}),
    max_results: parseInt(document.getElementById("maxResults").value) || 50,
    // [Fix] 添加期刊和字段参数，确保前端设置的筛选条件传递给AI搜索
    journal: getJournalFilter(),
    field: document.getElementById("filterField").value,
    pub_type: document.getElementById("filterPubType").value,
    oa_only: document.getElementById("oaOnly")?.checked ?? false,
    affiliation: document.getElementById("filterAffiliation")?.value?.trim() || "",
    use_pubmed: document.getElementById("usePubmed").checked,
    use_openalex: document.getElementById("useOpenalex").checked,
    use_semantic_scholar: document.getElementById("useSemanticScholar")?.checked || false,
    use_google_scholar: document.getElementById("useGoogleScholar")?.checked || false,
    use_bing_academic: document.getElementById("useBingAcademic")?.checked || false,
    use_cnki: document.getElementById("useCNKI")?.checked || false,
    use_wanfang: document.getElementById("useWanfang")?.checked || false,
    use_vip: document.getElementById("useVIP")?.checked || false,
    use_dblp: document.getElementById("useDblp")?.checked ?? true,
    use_biorxiv: document.getElementById("useBiorxiv")?.checked ?? true,
    use_agris: document.getElementById("useAgris")?.checked ?? true,
    use_acs: document.getElementById("useAcs")?.checked ?? true,
    use_optica: document.getElementById("useOptica")?.checked ?? true,
    use_iop: document.getElementById("useIop")?.checked ?? true,
    use_aip: document.getElementById("useAip")?.checked ?? true,
    use_rsc: document.getElementById("useRsc")?.checked ?? true,
    use_europepmc: document.getElementById("useEuropepmc")?.checked ?? true,
    use_springer: document.getElementById("useSpringer")?.checked ?? true,
    use_wiley: document.getElementById("useWiley")?.checked ?? true,
    use_ieee: document.getElementById("useIeee")?.checked ?? true,
    use_muse: document.getElementById("useMuse")?.checked ?? true,
    // [新增] CORE 和 Lens.org 数据源
    use_core: document.getElementById("useCore")?.checked ?? true,
    use_lens: document.getElementById("useLens")?.checked ?? true,
    use_lens_patents: document.getElementById("useLensPatents")?.checked ?? false,
    force_refresh: window._forceRefresh || false,
  };

  try {
    window.setStatus(t("aiAnalyzing"));
    _aiSearchAbort = new AbortController();
    const r = await fetch(`${API}/api/ai-search`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
      signal: _aiSearchAbort.signal,
    });

    if (!r.ok) {
      let errorData;
      try { errorData = await r.json(); } catch (e) { errorData = {}; }
      window.showToast(te(errorData.error) || t("aiSearchFailed"));
      window.setStatus(t("aiSearchFailed"));
      window.renderResults(); // 清除骨架屏，显示空状态
      return;
    }

    // 流式读取响应
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    let searchData = null;
    let thinkDone = false;
    let lastChunkTime = Date.now();
    const STREAM_TIMEOUT = 120000; // 120秒不活动超时

    while (true) {
      // 带超时的读取
      const readPromise = reader.read();
      const timeoutPromise = new Promise((_, reject) => {
        const remaining = STREAM_TIMEOUT - (Date.now() - lastChunkTime);
        if (remaining <= 0) {
          reject(new Error("stream_timeout"));
        }
        setTimeout(() => reject(new Error("stream_timeout")), remaining);
      });

      let result;
      try {
        result = await Promise.race([readPromise, timeoutPromise]);
      } catch (e) {
        if (e.message === "stream_timeout") {
          window.showToast(t("searchTimeout"));
          window.setStatus(t("aiSearchFailed"));
          window.renderResults(); // 清除骨架屏，显示空状态
          reader.cancel();
          return;
        }
        throw e;
      }

      const {done, value} = result;
      if (done) {
        debugLog(`[AI-DEBUG] Stream ended. fullText length: ${fullText.length}, searchData: ${searchData ? 'ok' : 'null'}, hasMarker: ${fullText.includes("__SEARCH_RESULT__")}, hasAIError: ${fullText.includes("AI_ERROR:")}, last200: ${fullText.slice(-200)}`);
        break;
      }
      lastChunkTime = Date.now();
      const chunk = decoder.decode(value, {stream: true});
      fullText += chunk;

      // 检查是否包含搜索结果标记（论文数据在 __SEARCH_RESULT__ 中一次性返回）
      const resultMarker = fullText.indexOf("__SEARCH_RESULT__");
      if (resultMarker >= 0) {
        // 提取搜索结果 JSON（包含 papers）
        const jsonStr = fullText.substring(resultMarker + "__SEARCH_RESULT__".length);
        debugLog(`[AI-DEBUG] Found __SEARCH_RESULT__ at pos ${resultMarker}, jsonStr length: ${jsonStr.length}, first100: ${jsonStr.substring(0, 100)}`);
        try {
          searchData = JSON.parse(jsonStr);
          debugLog(`[AI-DEBUG] JSON parsed OK, total: ${searchData.total}, papers: ${searchData.papers?.length}`);
        } catch (e) {
          debugLog(`[AI-DEBUG] JSON parse FAILED: ${e.message}, jsonStr last100: ${jsonStr.slice(-100)}`);
        }
        // 显示标记之前的思考内容（去掉 __SEARCH_JSON__ 及之后的内容）
        let thinkContent = fullText.substring(0, resultMarker);
        const jsonMarker = thinkContent.indexOf("__SEARCH_JSON__");
        if (jsonMarker >= 0) {
          thinkContent = thinkContent.substring(0, jsonMarker);
        }
        // 也过滤掉截断的标记（如 __SE、__SEARCH_ 等）
        const truncatedMarkers = ["__SEARCH_JSON__", "SEARCH_JSON__", "__SEARCH_JSON", "SEARCH_JSON", "SEARCHJSON", "__SEARCH_", "__SE"];
        for (const marker of truncatedMarkers) {
          const markerPos = thinkContent.indexOf(marker);
          if (markerPos >= 0) {
            thinkContent = thinkContent.substring(0, markerPos);
            break;
          }
        }
        if (streamEl) {
          streamEl.innerHTML = window.formatAIText(teAI(thinkContent));
          // 添加思考完成标记
          const thinkBlock = streamEl.closest('.ai-think-block');
          if (thinkBlock) {
            thinkBlock.style.borderLeftColor = '#10b981';
          }
        }
        break;
      }

      // 检查错误标记
      if (fullText.includes("AI_ERROR:")) {
        const errorMsg = fullText.split("AI_ERROR:")[1]?.split("\n")[0] || "unknown_error";
        if (errorMsg.trim() === "search_timeout") {
          window.showToast(t("searchTimeout"));
        } else {
          window.showToast(te(errorMsg) || t("aiSearchFailed"));
        }
        window.setStatus(t("aiSearchFailed"));
        window.renderResults(); // 清除骨架屏，显示空状态
        return;
      }

      // 实时显示思考内容（过滤掉 __SEARCH_JSON__ 及之后的内容）
      if (streamEl && !thinkDone) {
        let displayText = fullText;
        // 1. 过滤标记格式的 JSON（支持多种格式）
        const markers = ["__SEARCH_JSON__", "SEARCH_JSON__", "__SEARCH_JSON", "SEARCH_JSON", "SEARCHJSON", "__SEARCH_", "__SE"];
        let markerFound = false;
        for (const marker of markers) {
          const markerPos = displayText.indexOf(marker);
          if (markerPos >= 0) {
            displayText = displayText.substring(0, markerPos);
            thinkDone = true;
            markerFound = true;
            break;
          }
        }
        // 2. 如果没有标记，尝试检测裸 JSON（非思考模型可能直接输出 JSON）
        if (!markerFound && !thinkDone) {
          const jsonResult = tryExtractJson(displayText);
          if (jsonResult) {
            displayText = jsonResult.before;
            thinkDone = true;
          }
        }
        streamEl.innerHTML = window.formatAIText(teAI(displayText));
        aiPanel.scrollTop = aiPanel.scrollHeight;
      }

      // 3. 提取数据源状态消息（✓ / ✗ 开头的行）— 不受 thinkDone 限制
      {
        const allLines = fullText.split('\n');
        let lastStatusLine = '';
        for (const line of allLines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('✓ ') || trimmed.startsWith('✗ ')) {
            lastStatusLine = trimmed;
          }
        }
        if (lastStatusLine) {
          window.setStatus(lastStatusLine);
        }
      }
    }

    // 尝试从文本中提取 JSON 对象
    function tryExtractJson(text) {
      // 查找所有 { 的位置
      let pos = 0;
      while (pos < text.length) {
        const bracePos = text.indexOf('{', pos);
        if (bracePos < 0) return null;

        // 检查是否在代码块中
        const before = text.substring(0, bracePos);
        if (before.split('```').length % 2 === 0) {
          pos = bracePos + 1;
          continue;
        }

        // 检查 { 是否在行首（前面只有空白字符）
        const lineStart = before.lastIndexOf('\n') + 1;
        const linePrefix = before.substring(lineStart).trim();
        // { 必须是行首，或者前面是空行、冒号等
        if (linePrefix !== '' && !linePrefix.endsWith(':') && !linePrefix.endsWith('：') && !linePrefix.endsWith('。')) {
          pos = bracePos + 1;
          continue;
        }

        // 尝试从这个位置解析 JSON
        const jsonCandidate = text.substring(bracePos);
        try {
          // 使用 Function 构造函数来解析 JSON（更安全）
          const parsed = JSON.parse(jsonCandidate);
          // 检查是否是有效的搜索结果 JSON
          if (parsed && typeof parsed === 'object' && (parsed.query || parsed.year_from)) {
            return { before: before, json: parsed };
          }
        } catch (e) {
          // JSON 解析失败，继续查找下一个 {
          pos = bracePos + 1;
          continue;
        }
        pos = bracePos + 1;
      }
      return null;
    }

    // 处理搜索结果
    if (searchData) {
      window.PaperLens.allPapers = searchData.papers || [];
      window.PaperLens._originalPapers = [...(searchData.papers || [])];
      window.PaperLens.currentPage = 1;
      getCheckedSet().clear();
      window.PaperLens.currentSort = "relevance";
      window.PaperLens._sortReversed = false;
      // 保存 AI 生成的查询，用于后续重新筛选
      if (searchData.query) window.PaperLens.lastAIQuery = searchData.query;

      // AI 搜索完成后，自动同步筛选条件到前端
      if (searchData.analysis) {
        // 更新年份范围
        if (searchData.analysis.year_from) {
          document.getElementById("yearFrom").value = searchData.analysis.year_from;
        }
        if (searchData.analysis.year_to) {
          document.getElementById("yearTo").value = searchData.analysis.year_to;
        }

        // 更新数据源勾选
        const sources = searchData.analysis.data_sources;
        if (sources && sources.length > 0) {
          // 用户指定了数据源 → 只勾选指定源
          document.getElementById("usePubmed").checked = sources.includes("pubmed");
          document.getElementById("useOpenalex").checked = sources.includes("openalex");
          document.getElementById("useCNKI").checked = sources.includes("cnki");
          document.getElementById("useWanfang").checked = sources.includes("wanfang");
          document.getElementById("useVIP").checked = sources.includes("vip");
          document.getElementById("useGoogleScholar").checked = sources.includes("google_scholar");
          document.getElementById("useBingAcademic").checked = sources.includes("bing_academic");
          document.getElementById("useSemanticScholar").checked = sources.includes("semantic_scholar");
          document.getElementById("useCrossref").checked = sources.includes("crossref");
          document.getElementById("useArxiv").checked = sources.includes("arxiv");
          document.getElementById("useSciencedirect").checked = sources.includes("sciencedirect");
          document.getElementById("useScopus").checked = sources.includes("scopus");
          document.getElementById("useJstor").checked = sources.includes("jstor");
          document.getElementById("useDblp").checked = sources.includes("dblp");
          document.getElementById("useBiorxiv").checked = sources.includes("biorxiv");
          document.getElementById("useAgris").checked = sources.includes("agris");
          document.getElementById("useAcs").checked = sources.includes("acs");
          document.getElementById("useOptica").checked = sources.includes("optica");
          document.getElementById("useIop").checked = sources.includes("iop");
          document.getElementById("useAip").checked = sources.includes("aip");
          document.getElementById("useRsc").checked = sources.includes("rsc");
          document.getElementById("useEuropepmc").checked = sources.includes("europepmc");
          document.getElementById("useSpringer").checked = sources.includes("springer");
          document.getElementById("useWiley").checked = sources.includes("wiley");
          document.getElementById("useIeee").checked = sources.includes("ieee");
          document.getElementById("useMuse").checked = sources.includes("muse");
          // [新增] CORE 和 Lens.org 数据源同步
          document.getElementById("useCore").checked = sources.includes("core");
          document.getElementById("useLens").checked = sources.includes("lens");
        } else {
          // AI 未指定数据源 → 用 timing 信息恢复实际使用的源
          const usedSources = searchData.timing ? Object.keys(searchData.timing) : [];
          if (usedSources.length > 0) {
            // 只勾选实际搜索了的源
            document.getElementById("usePubmed").checked = usedSources.includes("pubmed");
            document.getElementById("useOpenalex").checked = usedSources.includes("openalex");
            document.getElementById("useGoogleScholar").checked = usedSources.includes("google_scholar");
            document.getElementById("useBingAcademic").checked = usedSources.includes("bing_academic");
            document.getElementById("useCNKI").checked = usedSources.includes("cnki");
            document.getElementById("useWanfang").checked = usedSources.includes("wanfang");
            document.getElementById("useVIP").checked = usedSources.includes("vip");
            document.getElementById("useSemanticScholar").checked = usedSources.includes("semantic_scholar");
            document.getElementById("useCrossref").checked = usedSources.includes("crossref");
            document.getElementById("useArxiv").checked = usedSources.includes("arxiv");
            document.getElementById("useSciencedirect").checked = usedSources.includes("sciencedirect");
            document.getElementById("useScopus").checked = usedSources.includes("scopus");
            document.getElementById("useJstor").checked = usedSources.includes("jstor");
            document.getElementById("useDblp").checked = usedSources.includes("dblp");
            document.getElementById("useBiorxiv").checked = usedSources.includes("biorxiv");
            document.getElementById("useAgris").checked = usedSources.includes("agris");
            document.getElementById("useAcs").checked = usedSources.includes("acs");
            document.getElementById("useOptica").checked = usedSources.includes("optica");
            document.getElementById("useIop").checked = usedSources.includes("iop");
            document.getElementById("useAip").checked = usedSources.includes("aip");
            document.getElementById("useRsc").checked = usedSources.includes("rsc");
            document.getElementById("useEuropepmc").checked = usedSources.includes("europepmc");
            document.getElementById("useSpringer").checked = usedSources.includes("springer");
            document.getElementById("useWiley").checked = usedSources.includes("wiley");
            document.getElementById("useIeee").checked = usedSources.includes("ieee");
            document.getElementById("useMuse").checked = usedSources.includes("muse");
            document.getElementById("useCore").checked = usedSources.includes("core");
            document.getElementById("useLens").checked = usedSources.includes("lens");
          }
          // 没有 timing 信息时保持当前勾选状态不变
          document.getElementById("useCrossref").checked = true;
          document.getElementById("useArxiv").checked = true;
          document.getElementById("useSciencedirect").checked = true;
          document.getElementById("useScopus").checked = true;
          document.getElementById("useJstor").checked = true;
          document.getElementById("useDblp").checked = true;
          document.getElementById("useBiorxiv").checked = true;
          document.getElementById("useAgris").checked = true;
          document.getElementById("useAcs").checked = true;
          document.getElementById("useOptica").checked = true;
          document.getElementById("useIop").checked = true;
          document.getElementById("useAip").checked = true;
          document.getElementById("useRsc").checked = true;
          document.getElementById("useEuropepmc").checked = true;
          document.getElementById("useSpringer").checked = true;
          document.getElementById("useWiley").checked = true;
          document.getElementById("useIeee").checked = true;
          document.getElementById("useMuse").checked = true;
          // [新增] CORE 和 Lens.org 默认启用
          document.getElementById("useCore").checked = true;
          document.getElementById("useLens").checked = true;
        }

        // 更新期刊过滤
        if (searchData.analysis.journal) {
          const jVal = searchData.analysis.journal;
          // [Fix] 使用 getSelectedJournals() 替代直接引用 selectedJournals
          // ES module 中直接引用会抛出 ReferenceError
          const sj = getSelectedJournals();
          if (!sj.includes(jVal)) { sj.push(jVal); renderJournalTags(); }
        }

        // 更新文献类型过滤
        if (searchData.analysis.pub_type) {
          document.getElementById("filterPubType").value = searchData.analysis.pub_type;
        }

        // 更新检索字段过滤
        if (searchData.analysis.field) {
          document.getElementById("filterField").value = searchData.analysis.field;
        }

        window.updateDataSourceDisplay();
      }

      // 应用下拉框排序
      const _sortBy = document.getElementById("sortBy").value;
      if (_sortBy && _sortBy !== "relevance") {
        window.sortPapers(_sortBy);
      } else {
        window.renderResults();
        window.renderPagination();
      }

      // 显示搜索结果摘要（不重复显示 explanation，因为流式输出时已显示）
      let summaryHtml = `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">`;
      if (searchData.analysis?.suggested_keywords) {
        summaryHtml += `<b>${t("suggestedKeywords")}</b>${escapeHtml(searchData.analysis.suggested_keywords.join(", "))}<br>`;
      }
      summaryHtml += `<b>${t("actualQuery")}</b><code>${escapeHtml(searchData.query)}</code>`;
      summaryHtml += `<br><button class="btn btn-sm btn-outline" style="margin-top:8px" onclick="refilterWithAI()">${t("refilter") || "用新条件重新筛选"}</button>`;
      summaryHtml += `</div>`;
      aiContent.innerHTML += summaryHtml;
      aiContent.dataset.status = "done";

      // 构建状态信息（含耗时详情）
      let statusText = `${t("aiSearchComplete")} ${searchData.total} ${t("papersFound")} ${elapsed} ${t("seconds")}`;
      if (searchData.timing) {
        const totalDuration = Object.values(searchData.timing)
          .reduce((sum, t) => sum + (t.duration || 0), 0);
        const timeoutCount = Object.values(searchData.timing)
          .filter(t => t.status === "timeout").length;
        if (timeoutCount > 0) {
          statusText += ` [${timeoutCount} ${t("searchTimeoutCount")}]`;
        }
        // 更新每个源的指示器
        for (const [sourceName, info] of Object.entries(searchData.timing)) {
          if (window.updateSourceTimingIndicator) {
            window.updateSourceTimingIndicator(sourceName, info.duration, info.status);
          }
        }
      }
      window.setStatus(statusText + ")");
      // 保存搜索历史
      if (typeof window.saveHistory === 'function') window.saveHistory(query, searchData.total || 0);
      // 刷新数据源健康状态（独立 try/catch，失败不影响搜索结果）
      try {
        if (typeof window.fetchSourceHealth === 'function') {
          const health = await window.fetchSourceHealth();
          if (health && typeof window.updateSourceIndicators === 'function') {
            window.updateSourceIndicators(health);
          }
        }
      } catch { /* 忽略 */ }
    } else {
      // 流结束但没有搜索结果 — 尝试 fallback 从缓存端点获取
      debugLog(`[AI-DEBUG] No searchData! Trying fallback... fullText length: ${fullText.length}, hasMarker: ${fullText.includes("__SEARCH_RESULT__")}`);
      try {
        const fallbackResp = await fetch(`${API}/api/ai-search/result`);
        if (fallbackResp.ok) {
          searchData = await fallbackResp.json();
          debugLog(`[AI-DEBUG] Fallback OK, total: ${searchData.total}, papers: ${searchData.papers?.length}`);
        } else {
          debugLog(`[AI-DEBUG] Fallback failed: ${fallbackResp.status}`);
        }
      } catch (fallbackErr) {
        debugLog(`[AI-DEBUG] Fallback error: ${fallbackErr.message}`);
      }
      // fallback 成功则显示结果
      if (searchData) {
        window.PaperLens.allPapers = searchData.papers || [];
        window.PaperLens._originalPapers = [...(searchData.papers || [])];
        window.PaperLens.currentPage = 1;
        getCheckedSet().clear();
        if (searchData.query) window.PaperLens.lastAIQuery = searchData.query;
        if (searchData.analysis) {
          if (searchData.analysis.year_from) document.getElementById("yearFrom").value = searchData.analysis.year_from;
          if (searchData.analysis.year_to) document.getElementById("yearTo").value = searchData.analysis.year_to;
          const sources = searchData.analysis.data_sources;
          if (sources && sources.length > 0) {
            document.getElementById("usePubmed").checked = sources.includes("pubmed");
            document.getElementById("useOpenalex").checked = sources.includes("openalex");
            document.getElementById("useSemanticScholar").checked = sources.includes("semantic_scholar");
            document.getElementById("useCrossref").checked = sources.includes("crossref");
            document.getElementById("useArxiv").checked = sources.includes("arxiv");
            document.getElementById("useSciencedirect").checked = sources.includes("sciencedirect");
            document.getElementById("useScopus").checked = sources.includes("scopus");
            document.getElementById("useJstor").checked = sources.includes("jstor");
            document.getElementById("useGoogleScholar").checked = sources.includes("google_scholar");
            document.getElementById("useBingAcademic").checked = sources.includes("bing_academic");
            document.getElementById("useCNKI").checked = sources.includes("cnki");
            document.getElementById("useWanfang").checked = sources.includes("wanfang");
            document.getElementById("useVIP").checked = sources.includes("vip");
            document.getElementById("useDblp").checked = sources.includes("dblp");
            document.getElementById("useBiorxiv").checked = sources.includes("biorxiv");
            document.getElementById("useAgris").checked = sources.includes("agris");
            document.getElementById("useAcs").checked = sources.includes("acs");
            document.getElementById("useOptica").checked = sources.includes("optica");
            document.getElementById("useIop").checked = sources.includes("iop");
            document.getElementById("useAip").checked = sources.includes("aip");
            document.getElementById("useRsc").checked = sources.includes("rsc");
            document.getElementById("useEuropepmc").checked = sources.includes("europepmc");
            document.getElementById("useSpringer").checked = sources.includes("springer");
            document.getElementById("useWiley").checked = sources.includes("wiley");
            document.getElementById("useIeee").checked = sources.includes("ieee");
            document.getElementById("useMuse").checked = sources.includes("muse");
            // [新增] CORE 和 Lens.org 数据源同步（fallback路径）
            document.getElementById("useCore").checked = sources.includes("core");
            document.getElementById("useLens").checked = sources.includes("lens");
          }

          // 更新期刊过滤
          if (searchData.analysis.journal) {
            const jVal = searchData.analysis.journal;
            // [Fix] 使用 getSelectedJournals() 替代直接引用 selectedJournals
          // ES module 中直接引用会抛出 ReferenceError
          const sj = getSelectedJournals();
          if (!sj.includes(jVal)) { sj.push(jVal); renderJournalTags(); }
          }

          // 更新文献类型过滤
          if (searchData.analysis.pub_type) {
            document.getElementById("filterPubType").value = searchData.analysis.pub_type;
          }

          // 更新检索字段过滤
          if (searchData.analysis.field) {
            document.getElementById("filterField").value = searchData.analysis.field;
          }

          window.updateDataSourceDisplay();
        }
        // 应用下拉框排序
        const _sortBy2 = document.getElementById("sortBy").value;
        if (_sortBy2 && _sortBy2 !== "relevance") {
          window.sortPapers(_sortBy2);
        } else {
          window.renderResults();
          window.renderPagination();
        }
        let summaryHtml = `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">`;
        if (searchData.analysis?.suggested_keywords) {
          summaryHtml += `<b>${t("suggestedKeywords")}</b>${escapeHtml(searchData.analysis.suggested_keywords.join(", "))}<br>`;
        }
        summaryHtml += `<b>${t("actualQuery")}</b><code>${escapeHtml(searchData.query)}</code>`;
        summaryHtml += `<br><button class="btn btn-sm btn-outline" style="margin-top:8px" onclick="refilterWithAI()">${t("refilter") || "用新条件重新筛选"}</button>`;
        summaryHtml += `</div>`;
        aiContent.innerHTML += summaryHtml;
        // 构建状态信息（含耗时详情）
        let statusText = `${t("aiSearchComplete")} ${searchData.total} ${t("papersFound")} ${elapsed} ${t("seconds")}`;
        if (searchData.timing) {
          const timeoutCount = Object.values(searchData.timing)
            .filter(t => t.status === "timeout").length;
          if (timeoutCount > 0) {
            statusText += ` [${timeoutCount} ${t("searchTimeoutCount")}]`;
          }
          // 更新每个源的指示器
          for (const [sourceName, info] of Object.entries(searchData.timing)) {
            if (window.updateSourceTimingIndicator) {
              window.updateSourceTimingIndicator(sourceName, info.duration, info.status);
            }
          }
        }
        window.setStatus(statusText + ")");
        // 保存搜索历史
        if (typeof window.saveHistory === 'function') window.saveHistory(query, searchData.total || 0);
        // 刷新数据源健康状态（独立 try/catch，失败不影响搜索结果）
        try {
          if (typeof window.fetchSourceHealth === 'function') {
            const health = await window.fetchSourceHealth();
            if (health && typeof window.updateSourceIndicators === 'function') {
              window.updateSourceIndicators(health);
            }
          }
        } catch { /* 忽略 */ }
      } else {
        window.showToast(t("aiSearchFailedRetry"));
        window.setStatus(t("aiSearchFailed"));
        window.renderResults(); // 清除骨架屏，显示空状态
      }
    }
  } catch (e) {
    // [Fix #7] timer 统一在 finally 中清除
    if (e.name === 'AbortError') {
      window.setStatus(t("searchCancelled"));
      window.renderResults(); // 清除骨架屏，显示空状态
    } else {
      debugLog(`[SEARCH] AI search fetch/read failed: ${e.name}: ${e.message}`);
      console.error(`[SEARCH] AI search error:`, e);
      window.showToast(`${t("networkError")}: ${e.message}`);
      window.setStatus(t("networkError"), "network_error");
      window.renderResults(); // 清除骨架屏，显示空状态
    }
  } finally {
    clearInterval(timer); // [Fix #7] 确保所有路径都清除 timer
    safeSetDisabled("searchBtn", false);
    const btn = document.getElementById("searchBtn");
    if (btn) {
      btn.textContent = t("search");
      btn.onclick = doSmartSearch; // 恢复点击事件
    }
    const cancelBtn = document.getElementById("cancelBtn");
    if (cancelBtn) cancelBtn.style.display = "none"; // 隐藏取消按钮
    _aiSearchAbort = null;
  }
}

// 用 AI 生成的查询 + 新的筛选条件重新搜索
async function refilterWithAI() {
  if (!window.PaperLens.lastAIQuery) {
    window.showToast(t("noPreviousQuery") || "没有上次 AI 查询，请先进行 AI 搜索");
    return;
  }
  safeSetDisabled("searchBtn", true);
  const btn = document.getElementById("searchBtn");
  if (btn) btn.textContent = t("searching");
  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) cancelBtn.style.display = "inline-block";
  window.setStatus(t("searching"));
  showSkeleton();

  const body = buildSearchBody({ query: window.PaperLens.lastAIQuery });

  try {
    const r = await fetch(`${API}/api/search`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (r.ok) {
      window.PaperLens.allPapers = data.papers || [];
      window.PaperLens._originalPapers = [...(data.papers || [])];
      window.PaperLens.currentPage = 1;
      getCheckedSet().clear();
      window.PaperLens._sortReversed = false;
      // 应用下拉框排序
      const _sortBy = document.getElementById("sortBy").value;
      if (_sortBy && _sortBy !== "relevance") {
        window.PaperLens.currentSort = "relevance";
        window.sortPapers(_sortBy);
      } else {
        window.PaperLens.currentSort = "relevance";
        window.renderResults();
        window.renderPagination();
      }
      window.setStatus(`${t("totalPapers")} ${data.total || 0} ${t("papers")}`);
      // 显示数据源错误提示
      if (data.errors && data.errors.length > 0) {
        window.showToast(`${t("searchTips")}\n${data.errors.join("; ")}`, 8000);
      }
    } else {
      window.showToast(te(data.error) || t("searchFailed"));
      if (getAllPapers().length === 0) window.setStatus(t("searchFailed"));
    }
  } catch (e) {
    debugLog(`[SEARCH] refilterWithAI fetch failed: ${e.name}: ${e.message}`);
    console.error(`[SEARCH] refilterWithAI error:`, e);
    window.showToast(`${t("networkError")}: ${e.message}`);
    window.setStatus(t("networkErrorRetry"), "network_error");
  } finally {
    safeSetDisabled("searchBtn", false);
    const btn = document.getElementById("searchBtn");
    if (btn) btn.textContent = t("search");
    const cancelBtn = document.getElementById("cancelBtn");
    if (cancelBtn) cancelBtn.style.display = "none";
  }
}

// 导出到 window 供其他模块使用
window.doSmartSearch = doSmartSearch;
window.doSearch = doSearch;
window.doAISearch = doAISearch;
window.cancelAISearch = cancelAISearch;
window.refilterWithAI = refilterWithAI;
window.setSearchMode = setSearchMode;
window.handleSearchKeydown = handleSearchKeydown;
window.handleJournalKeydown = handleJournalKeydown;
window.renderJournalTags = renderJournalTags;
window.removeJournal = removeJournal;
window.getJournalFilter = getJournalFilter;
window.savePreferences = savePreferences;
window.initSuggestions = initSuggestions;
window.startPlaceholderRotation = startPlaceholderRotation;
window.showSuggestDropdown = showSuggestDropdown;
window.addJournalGroup = addJournalGroup;
window.addJournalsBatch = addJournalsBatch;
window.clearAllJournals = clearAllJournals;
window.renderJournalGroupUI = renderJournalGroupUI;
window.setupJournalFuzzySearch = setupJournalFuzzySearch;
window.generateSearchSuggestions = generateSearchSuggestions;
window.getSimplifiedQuery = getSimplifiedQuery;
window.showSkeleton = showSkeleton;
window.renderSourceChips = renderSourceChips;
window.toggleSourcePicker = toggleSourcePicker;
window.renderSourcePickerFilter = renderSourcePickerFilter;
window.updateDataSourceDisplay = updateDataSourceDisplay;

// ========== 数据源健康监控 ==========

// 数据源名称到 checkbox ID 的映射
const SOURCE_CHECKBOX_MAP = {
  'PubMed': 'usePubmed',
  'OpenAlex': 'useOpenalex',
  'Semantic Scholar': 'useSemanticScholar',
  'arXiv': 'useArxiv',
  'DBLP': 'useDblp',
  'bioRxiv': 'useBiorxiv',
  'AGRIS': 'useAgris',
  'ACS': 'useAcs',
  'Optica': 'useOptica',
  'IOP': 'useIop',
  'AIP': 'useAip',
  'RSC': 'useRsc',
  'Europe PMC': 'useEuropepmc',
  'Springer': 'useSpringer',
  'Wiley': 'useWiley',
  'IEEE': 'useIeee',
  'MUSE': 'useMuse',
  'CrossRef': 'useCrossref',
  'ScienceDirect': 'useSciencedirect',
  'Scopus': 'useScopus',
  'JSTOR': 'useJstor',
  'Google Scholar': 'useGoogleScholar',
  'Bing Academic': 'useBingAcademic',
  'CNKI': 'useCNKI',
  '万方': 'useWanfang',
  '维普': 'useVIP',
  'CORE': 'useCore',
  'Lens': 'useLens',
  'Frontiers': 'useFrontiers', 'ACM': 'useAcm',
  'Oxford Academic': 'useOup', 'Cambridge Core': 'useCup', 'SAGE': 'useSage',
  'Taylor & Francis': 'useTaylor_francis', 'EBSCO': 'useEbsco',
  'Web of Science': 'useWos', 'ProQuest': 'useProquest',
  'J-STAGE': 'useJstage', 'Cochrane': 'useCochrane',
};

// 健康状态颜色映射
const HEALTH_COLORS = {
  'green': '#22c55e',
  'yellow': '#eab308',
  'red': '#ef4444',
  'disabled': '#9ca3af',
  'timeout': '#9ca3af',  // 超时源用灰色
};

// 健康状态名称（使用 i18n 翻译）
function getHealthLabel(status) {
  const labels = {
    'green': t("healthStatusNormal"),
    'yellow': t("healthStatusDegraded"),
    'red': t("healthStatusAbnormal"),
    'disabled': t("healthStatusDisabled"),
  };
  return labels[status] || status;
}

let _healthPanelVisible = false;
let _healthData = null;

/**
 * 获取数据源健康状态（带 30s 缓存，减少重复请求）
 */
let _healthCacheTime = 0;
async function fetchSourceHealth() {
  const now = Date.now();
  if (now - _healthCacheTime < 30000) return _healthData;
  try {
    const r = await fetch(`${API}/api/source-health`);
    if (!r.ok) return null;
    const data = await r.json();
    _healthData = data.sources || {};
    _healthCacheTime = now;
    return _healthData;
  } catch (e) {
    console.warn('Failed to fetch source health:', e);
    return null;
  }
}

/**
 * 刷新并显示健康状态
 */
async function refreshSourceHealth() {
  const health = await fetchSourceHealth();
  if (!health) return;
  renderHealthPanel(health);
  updateSourceIndicators(health);
}

/**
 * 根据搜索耗时实时更新源的指示器颜色
 * @param {string} sourceName - 数据源名称
 * @param {number} duration - 耗时（秒）
 * @param {string} status - 状态：ok, timeout, error
 */
function updateSourceTimingIndicator(sourceName, duration, status) {
  const checkboxId = SOURCE_CHECKBOX_MAP[sourceName];
  if (!checkboxId) return;

  const checkbox = document.getElementById(checkboxId);
  if (!checkbox) return;

  const label = checkbox.closest('label');
  if (!label) return;

  // 移除旧的 timing 指示器
  const existingDot = label.querySelector('.source-timing-dot');
  if (existingDot) existingDot.remove();

  // 创建 timing 指示点
  const dot = document.createElement('span');
  dot.className = 'source-timing-dot';

  // 根据耗时和状态设置颜色
  let color;
  if (status === 'timeout') {
    color = HEALTH_COLORS['timeout'];
  } else if (status === 'error') {
    color = HEALTH_COLORS['red'];
  } else if (duration > 10) {
    // 超过 10 秒用黄色
    color = HEALTH_COLORS['yellow'];
  } else {
    color = HEALTH_COLORS['green'];
  }

  dot.style.cssText = `
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: ${color};
    margin-left: 4px;
    vertical-align: middle;
    cursor: pointer;
    transition: all 0.3s ease;
  `;
  dot.title = `${sourceName}: ${duration}s`;

  // 如果是超时或错误，添加闪烁效果
  if (status === 'timeout' || status === 'error') {
    dot.style.animation = 'pulse 1.5s infinite';
  }

  label.appendChild(dot);
}

/**
 * 更新数据源 checkbox 旁边的健康指示器
 */
function updateSourceIndicators(health) {
  // 移除旧的指示器
  document.querySelectorAll('.source-health-dot').forEach(el => el.remove());

  for (const [sourceName, status] of Object.entries(health)) {
    const checkboxId = SOURCE_CHECKBOX_MAP[sourceName];
    if (!checkboxId) continue;

    const checkbox = document.getElementById(checkboxId);
    if (!checkbox) continue;

    const label = checkbox.closest('label');
    if (!label) continue;

    // 创建健康指示点
    const dot = document.createElement('span');
    dot.className = 'source-health-dot';
    dot.style.cssText = `
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: ${HEALTH_COLORS[status.status] || HEALTH_COLORS['disabled']};
      margin-left: 4px;
      vertical-align: middle;
      cursor: pointer;
      title: ${sourceName}: ${getHealthLabel(status.status)}
    `;
    dot.title = `${sourceName}\n${t("healthStatus")}: ${getHealthLabel(status.status)}\n${t("healthSuccessRate")}: ${status.success_rate}%\n${t("healthAvgResponse")}: ${status.avg_time}s\n${t("healthSampleCount")}: ${status.total}`;
    dot.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleHealthPanel();
    };
    label.appendChild(dot);
  }
}

/**
 * 渲染健康面板内容
 */
function renderHealthPanel(health) {
  const container = document.getElementById('healthPanelContent');
  if (!container) return;

  let html = '<table style="width:100%;font-size:12px;border-collapse:collapse">';
  html += '<tr style="border-bottom:1px solid var(--border);color:var(--text-secondary)">';
  html += `<th style="text-align:left;padding:4px">${t("healthSource")}</th>`;
  html += `<th style="text-align:center;padding:4px">${t("healthStatus")}</th>`;
  html += `<th style="text-align:center;padding:4px">${t("healthSuccessRate")}</th>`;
  html += `<th style="text-align:center;padding:4px">${t("healthAvgResponse")}</th>`;
  html += `<th style="text-align:center;padding:4px">${t("healthSampleCount")}</th>`;
  html += `<th style="text-align:center;padding:4px">${t("healthAction")}</th>`;
  html += '</tr>';

  // 按状态排序：red > yellow > disabled > green
  const statusOrder = { 'red': 0, 'yellow': 1, 'disabled': 2, 'green': 3 };
  const sorted = Object.entries(health).sort((a, b) => {
    return (statusOrder[a[1].status] ?? 4) - (statusOrder[b[1].status] ?? 4);
  });

  for (const [sourceName, info] of sorted) {
    const statusColor = HEALTH_COLORS[info.status] || '#9ca3af';
    const statusLabel = getHealthLabel(info.status);
    const isDisabled = info.status === 'disabled';
    const toggleLabel = isDisabled ? t("healthEnable") : t("healthDisable");
    const toggleEnabled = !isDisabled;

    html += `<tr style="border-bottom:1px solid var(--border)">`;
    html += `<td style="padding:4px;font-weight:500">${sourceName}</td>`;
    html += `<td style="text-align:center;padding:4px">
      <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${statusColor};margin-right:4px;vertical-align:middle"></span>
      ${statusLabel}
    </td>`;
    html += `<td style="text-align:center;padding:4px">${info.success_rate}%</td>`;
    html += `<td style="text-align:center;padding:4px">${info.avg_time}s</td>`;
    html += `<td style="text-align:center;padding:4px">${info.total}</td>`;
    html += `<td style="text-align:center;padding:4px">
      <button class="btn btn-outline" style="font-size:10px;padding:1px 6px"
        onclick="toggleSourceHealth('${sourceName}', ${!toggleEnabled})">${toggleLabel}</button>
    </td>`;
    html += '</tr>';
  }

  html += '</table>';
  container.innerHTML = html;
}

/**
 * 切换健康面板显示/隐藏
 */
function toggleHealthPanel() {
  const panel = document.getElementById('healthPanel');
  if (!panel) return;

  _healthPanelVisible = !_healthPanelVisible;
  panel.style.display = _healthPanelVisible ? 'block' : 'none';

  if (_healthPanelVisible) {
    refreshSourceHealth();
  }
}

/**
 * 手动启用/禁用数据源
 */
async function toggleSourceHealth(sourceName, enabled) {
  try {
    const r = await fetch(`${API}/api/source-health/toggle`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source: sourceName, enabled}),
    });
    if (!r.ok) throw new Error('Failed to toggle');
    // 刷新面板
    await refreshSourceHealth();
    const action = enabled ? t("healthEnable") : t("healthDisable");
    window.showToast(t("healthSourceToggled").replace("{source}", sourceName).replace("{action}", action));
  } catch (e) {
    window.showToast(`${t("healthOperationFailed")}: ${e.message}`);
  }
}

/**
 * 重置所有数据源健康状态
 */
async function resetAllSourceHealth() {
  try {
    const r = await fetch(`${API}/api/source-health/reset`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error('Failed to reset');
    await refreshSourceHealth();
    window.showToast(t("healthResetSuccess"));
  } catch (e) {
    window.showToast(`${t("healthResetFailed")}: ${e.message}`);
  }
}

// 导出到 window
window.fetchSourceHealth = fetchSourceHealth;
window.refreshSourceHealth = refreshSourceHealth;
window.toggleHealthPanel = toggleHealthPanel;
window.toggleSourceHealth = toggleSourceHealth;
window.resetAllSourceHealth = resetAllSourceHealth;
window.updateSourceIndicators = updateSourceIndicators;
window.updateSourceTimingIndicator = updateSourceTimingIndicator;

export {
  doSmartSearch,
  doSearch,
  doAISearch,
  cancelAISearch,
  refilterWithAI,
  setSearchMode,
  detectNeedAI,
  handleSearchKeydown,
  handleJournalKeydown,
  renderJournalTags,
  removeJournal,
  getJournalFilter,
  savePreferences,
  initSuggestions,
  startPlaceholderRotation,
  showSuggestDropdown,
  DEFAULT_SUGGESTIONS,
  addJournalGroup,
  addJournalsBatch,
  clearAllJournals,
  renderJournalGroupUI,
  setupJournalFuzzySearch,
};

// ========== 数据源选择器 ==========
const SOURCE_GROUPS = [
  { title: "核心数据库", sources: ["pubmed","openalex","semantic_scholar","crossref","core","lens"] },
  { title: "预印本 / OA", sources: ["arxiv","biorxiv","europepmc","pubag"] },
  { title: "出版商", sources: ["sciencedirect","scopus","jstor","springer","wiley","ieee","acs","optica","iop","aip","rsc","muse","dblp","frontiers","acm","oup","cup","sage","taylor_francis","ebsco"] },
  { title: "中文学术", sources: ["cnki","wanfang","vip"] },
  { title: "CARSI 聚合器", sources: ["wos","proquest"] },
  { title: "实验性", sources: ["google_scholar","bing_academic","lens_patents"] },
  { title: "开放仓储", sources: ["zenodo","datacite","jstage","cochrane"] },
  { title: "本地", sources: ["zotero_mcp"] },
];
const SOURCE_LABELS = {
  pubmed:"PubMed", openalex:"OpenAlex", semantic_scholar:"S2", crossref:"CrossRef",
  arxiv:"arXiv", biorxiv:"bioRxiv", europepmc:"Europe PMC", agris:"AGRIS", pubag:"USDA PubAg",
  sciencedirect:"ScienceDirect", scopus:"Scopus", jstor:"JSTOR",
  springer:"Springer", wiley:"Wiley", ieee:"IEEE", acs:"ACS", optica:"Optica",
  iop:"IOP", aip:"AIP", rsc:"RSC", muse:"MUSE", dblp:"DBLP",
  cnki:"CNKI", wanfang:"万方", vip:"维普",
  google_scholar:"GScholar", bing_academic:"Bing", lens_patents:"专利",
  core:"CORE", lens:"Lens", zotero_mcp:"Zotero", zenodo:"Zenodo", datacite:"DataCite",
  frontiers:"Frontiers", acm:"ACM", oup:"Oxford Academic", cup:"Cambridge Core",
  sage:"SAGE", taylor_francis:"Taylor & Francis", ebsco:"EBSCO",
  wos:"Web of Science", proquest:"ProQuest", jstage:"J-STAGE", cochrane:"Cochrane",
};
const SOURCE_BADGES = {
  sciencedirect:"🔐", scopus:"🔐", jstor:"🔐",
  google_scholar:"β", bing_academic:"β", cnki:"β", wanfang:"β", vip:"β",
  lens_patents:"🔬", zotero_mcp:"📚", core:"OA", lens:"📚", zenodo:"📦", datacite:"🌐",
  frontiers:"OA", acm:"OA", oup:"OA", cup:"OA", sage:"OA", taylor_francis:"OA", ebsco:"OA",
  wos:"🔐", proquest:"🔐", jstage:"OA", cochrane:"OA",
};
const CHECKBOX_MAP = {
  pubmed:"usePubmed", openalex:"useOpenalex", semantic_scholar:"useSemanticScholar",
  crossref:"useCrossref", arxiv:"useArxiv", sciencedirect:"useSciencedirect",
  scopus:"useScopus", jstor:"useJstor", dblp:"useDblp", biorxiv:"useBiorxiv",
  agris:"useAgris", pubag:"usePubag", acs:"useAcs", optica:"useOptica", iop:"useIop", aip:"useAip",
  rsc:"useRsc", europepmc:"useEuropepmc", springer:"useSpringer", wiley:"useWiley",
  ieee:"useIeee", muse:"useMuse", google_scholar:"useGoogleScholar",
  bing_academic:"useBingAcademic", cnki:"useCNKI", wanfang:"useWanfang", vip:"useVIP",
  core:"useCore", lens:"useLens", lens_patents:"useLensPatents", zotero_mcp:"useZoteroMcp",
  zenodo:"useZenodo", datacite:"useDatacite", frontiers:"useFrontiers", acm:"useAcm",
  oup:"useOup", cup:"useCup", sage:"useSage", taylor_francis:"useTaylor_francis",
  ebsco:"useEbsco", wos:"useWos", proquest:"useProquest",
  jstage:"useJstage", cochrane:"useCochrane",
};

function _findCbId(sourceName) { return CHECKBOX_MAP[sourceName] || ""; }

function _renderPickerHTML(dd) {
  const searchFilter = dd.querySelector(".source-picker-search")?.value?.toLowerCase() || "";
  let html = `<input type="text" class="source-picker-search" placeholder="搜索数据源..." oninput="window.renderSourcePickerFilter(this.value)" value="${escapeHtml(searchFilter)}">`;
  SOURCE_GROUPS.forEach(group => {
    const visibleSources = group.sources.filter(s => !searchFilter || (SOURCE_LABELS[s]||s).toLowerCase().includes(searchFilter));
    if (!visibleSources.length) return;
    html += `<div class="source-picker-group"><div class="source-picker-group-title">${group.title}</div>`;
    visibleSources.forEach(s => {
      const cbId = _findCbId(s);
      const elem = document.getElementById(cbId);
      const checked = elem ? elem.checked : false;
      const label = SOURCE_LABELS[s] || s;
      const badge = SOURCE_BADGES[s] || "";
      const tips = { sciencedirect:"需 CARSI 认证", scopus:"需 CARSI 认证", jstor:"需 CARSI 认证", google_scholar:"反爬风险高，需 ScraperAPI", bing_academic:"需安装 Playwright", cnki:"Playwright 浏览器模式", wanfang:"需 Cookie 登录", vip:"需机构权限", core:"开放获取聚合，3亿+记录", lens:"学术文献+专利，2.5亿+记录", lens_patents:"Lens.org 专利检索", zotero_mcp:"搜索本地 Zotero 库" };
      const tip = tips[s] || "";
      html += `<label class="source-picker-item"${tip?` title="${tip}"`:""}><input type="checkbox" ${checked?"checked":""} onchange="document.getElementById('${cbId}').checked=this.checked;window.renderSourceChips();window.updateDataSourceDisplay()">${label}${badge?` <span class="src-badge">${badge}</span>`:""}</label>`;
    });
    html += `</div>`;
  });
  html += `<div class="source-picker-actions"><button class="btn btn-sm btn-outline" onclick="document.querySelectorAll('#legacySourceChecks input[type=checkbox]').forEach(c=>c.checked=true);window.renderSourceChips();window.updateDataSourceDisplay()">全选</button><button class="btn btn-sm btn-outline" onclick="document.querySelectorAll('#legacySourceChecks input[type=checkbox]').forEach(c=>c.checked=false);window.renderSourceChips();window.updateDataSourceDisplay()">取消全选</button></div>`;
  dd.innerHTML = `<div class="source-picker-dropdown-inner">${html}</div>`;
}

function renderSourceChips() {
  const container = document.getElementById("sourceChips");
  if (!container) return;
  const chips = [];
  document.querySelectorAll("#legacySourceChecks input[type=checkbox]").forEach(cb => {
    if (cb.checked) {
      let name = "";
      for (const [k, v] of Object.entries(CHECKBOX_MAP)) {
        if (v === cb.id) { name = k; break; }
      }
      const label = (name && SOURCE_LABELS[name]) || name || cb.id;
      chips.push(`<span class="source-chip" title="点击移除">${label}<span class="chip-remove" onclick="event.stopPropagation();document.getElementById('${cb.id}').checked=false;window.renderSourceChips();window.updateDataSourceDisplay()">×</span></span>`);
    }
  });
  if (chips.length === 0) {
    container.innerHTML = '<span style="font-size:11px;color:var(--text-secondary)">未选择数据源</span>';
  } else {
    container.innerHTML = chips.join("");
  }
  const dd = document.getElementById("sourcePickerDropdown");
  if (dd && dd.classList.contains("show")) _renderPickerHTML(dd);
}

function toggleSourcePicker() {
  const dd = document.getElementById("sourcePickerDropdown");
  if (!dd) return;
  if (dd.classList.contains("show")) {
    dd.classList.remove("show");
    _restoreSourcePickerDropdown(dd);
    return;
  }
  _renderPickerHTML(dd);
  // 移到 body 下，脱离 .search-section 的 backdrop-filter stacking context
  if (dd.parentElement !== document.body) {
    dd._searchBarParent = dd.parentElement;
    document.body.appendChild(dd);
  }
  // fixed 定位，相对 sourcePickerBtn
  dd.style.position = "fixed";
  const btn = document.getElementById("sourcePickerBtn");
  if (btn) {
    const btnRect = btn.getBoundingClientRect();
    dd.style.top = btnRect.bottom + 6 + "px";
    dd.style.left = btnRect.left + "px";
  }
  dd.classList.add("show");
  setTimeout(() => {
    const handler = (e) => {
      if (!dd.contains(e.target) && e.target.id !== "sourcePickerBtn") {
        dd.classList.remove("show");
        _restoreSourcePickerDropdown(dd);
        document.removeEventListener("click", handler);
      }
    };
    document.addEventListener("click", handler);
  }, 0);
}

function _restoreSourcePickerDropdown(dd) {
  if (dd._searchBarParent && dd.parentElement === document.body) {
    dd._searchBarParent.appendChild(dd);
    dd._searchBarParent = null;
  }
  dd.style.position = "";
  dd.style.top = "";
  dd.style.left = "";
}

function renderSourcePickerFilter(value) {
  const dd = document.getElementById("sourcePickerDropdown");
  if (dd) { dd.querySelector(".source-picker-search").value = value; _renderPickerHTML(dd); }
}