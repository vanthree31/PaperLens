// ========== PaperLens 入口模块 ==========
// 导入所有子模块
import './state.js';
import './i18n.js';
import './utils.js';
import './search.js';
import './collection.js';
import './tags.js';
import './zotero.js';
import './graph.js';

// 导入需要暴露到 window 的函数
import { t, te, teAI, safeSetDisabled, setLang, currentLang } from './i18n.js';
import { escapeHtml, debugLog, safeURI } from './state.js';

// ========== Window 导出：i18n 函数 ==========
// inline 代码直接调用 t() / te() / teAI() 等，需要在 window 作用域
window.t = t;
window.te = te;
window.teAI = teAI;
window.safeSetDisabled = safeSetDisabled;
window.escapeHtml = escapeHtml;
window.debugLog = debugLog;
window.safeURI = safeURI;

// currentLang 桥接（inline setLang() 使用裸变量名）
Object.defineProperty(window, 'currentLang', {
  get() { return window.PaperLens.currentLang; },
  set(v) { window.PaperLens.currentLang = v; },
  configurable: true,
  enumerable: true,
});

// ========== 主题切换 ==========
const STORAGE_KEY_THEME = "paperlens_theme";

/**
 * 应用主题模式
 * @param {string} mode - 'auto' | 'light' | 'dark'
 */
function applyThemeMode(mode) {
  const root = document.documentElement;
  // 移除所有主题属性
  root.removeAttribute('data-theme');

  if (mode === 'auto') {
    // Auto 模式：设置 data-theme="auto"，CSS 会根据 prefers-color-scheme 切换
    root.setAttribute('data-theme', 'auto');
  } else if (mode === 'dark') {
    root.setAttribute('data-theme', 'dark');
  } else {
    // Light 模式：设置 data-theme="light"
    root.setAttribute('data-theme', 'light');
  }
}

/**
 * 设置主题模式并保存到 localStorage
 * @param {string} mode - 'auto' | 'light' | 'dark'
 */
function setThemeMode(mode) {
  // 验证模式值
  if (!['auto', 'light', 'dark'].includes(mode)) {
    mode = 'auto';
  }
  // 保存到 localStorage
  localStorage.setItem(STORAGE_KEY_THEME, mode);
  // 应用主题
  applyThemeMode(mode);
  // 更新设置面板中的下拉框
  const select = document.getElementById('cfgThemeMode');
  if (select) select.value = mode;
}

/**
 * 初始化主题（页面加载时调用）
 */
function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY_THEME) || 'auto';
  applyThemeMode(saved);
  const select = document.getElementById('cfgThemeMode');
  if (select) select.value = saved;
  // 语言下拉框同步
  const langSelect = document.getElementById('cfgLanguage');
  if (langSelect) langSelect.value = currentLang || 'zh';
}

// 导出到 window 供 inline 代码使用
window.setThemeMode = setThemeMode;
window.applyThemeMode = applyThemeMode;
window.initTheme = initTheme;

// ========== Window 桥接：状态变量 ==========
// inline 代码使用裸变量名（allPapers, checkedSet 等），
// 模块使用 window.PaperLens getter/setter，需要桥接
const _stateKeys = [
  'API', 'allPapers', 'currentPage', 'pageSize',
  'collectionsData', 'currentGroupId', 'checkedSet',
  'currentSort', '_sortReversed', 'lastAIQuery', '_originalPapers',
  'selectedJournals', '_historyCache',
];
for (const key of _stateKeys) {
  Object.defineProperty(window, key, {
    get() { return window.PaperLens[key]; },
    set(v) { window.PaperLens[key] = v; },
    configurable: true,
    enumerable: true,
  });
}

// _searchMode 需要从 localStorage 初始化（模块默认为 "normal"）
// 先设置到 PaperLens 对象，再定义 window 桥接
window.PaperLens._searchMode = localStorage.getItem("searchMode") || "normal";
Object.defineProperty(window, '_searchMode', {
  get() { return window.PaperLens._searchMode; },
  set(v) { window.PaperLens._searchMode = v; },
  configurable: true,
  enumerable: true,
});

// ========== 初始化 ==========
(async function init() {
  // 初始化主题（尽早调用，避免闪烁）
  initTheme();

  const now = new Date().getFullYear();
  document.getElementById("yearFrom").value = now - 10;
  document.getElementById("yearTo").value = now;
  document.getElementById("searchInput").focus();

  // 并行加载所有初始化数据
  const [prefsResult] = await Promise.allSettled([
    fetch(`${window.PaperLens.API}/api/preferences`).then(r => r.ok ? r.json() : null),
    window.loadHistory(),
    window.loadCollections(),
    window.loadZoteroConfig(),
    window.initTags(),
  ]);

  // 应用偏好设置
  if (prefsResult.status === "fulfilled" && prefsResult.value) {
    const prefs = prefsResult.value;
    if (prefs.yearFrom) document.getElementById("yearFrom").value = prefs.yearFrom;
    if (prefs.yearTo) document.getElementById("yearTo").value = prefs.yearTo;
    if (prefs.sortBy) document.getElementById("sortBy").value = prefs.sortBy;
    if (prefs.maxResults) document.getElementById("maxResults").value = prefs.maxResults;
    if (prefs.filterJournal) {
      try { window.selectedJournals = JSON.parse(prefs.filterJournal); } catch { window.selectedJournals = []; }
      if (typeof window.selectedJournals === 'string') window.selectedJournals = window.selectedJournals ? [window.selectedJournals] : [];
      window.renderJournalTags();
      window.renderJournalGroupUI();
    }
    if (prefs.filterField) document.getElementById("filterField").value = prefs.filterField;
    if (prefs.filterPubType) document.getElementById("filterPubType").value = prefs.filterPubType;
    if (prefs.oaOnly !== undefined && document.getElementById("oaOnly")) document.getElementById("oaOnly").checked = prefs.oaOnly;
    if (prefs.filterAffiliation !== undefined && document.getElementById("filterAffiliation")) document.getElementById("filterAffiliation").value = prefs.filterAffiliation;
    if (prefs.lang) {
      window.PaperLens.currentLang = prefs.lang;
      localStorage.setItem("paperlang", prefs.lang);
    }
    // 恢复数据源状态
    if (prefs.dataSources) {
      Object.entries(prefs.dataSources).forEach(([id, checked]) => {
        const el = document.getElementById(id);
        if (el && el.type === 'checkbox') el.checked = checked;
      });
    }
  }

  // 初始化搜索建议
  window.initSuggestions();
  window.renderSourceChips();
  window.updateDataSourceDisplay();

  // 初始化期刊分组 UI 和模糊搜索
  window.renderJournalGroupUI();
  window.setupJournalFuzzySearch();

  // 初始化搜索模式
  window.setSearchMode(window._searchMode || "normal");

  // 应用语言
  window.applyLang();

  // 点击外部关闭标签选择器
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.tag-selector')) {
      if (window.closeAllTagSelectors) window.closeAllTagSelectors();
    }
  });
})();

// renderCollections 已在 collection.js 中直接实现阅读状态显示
