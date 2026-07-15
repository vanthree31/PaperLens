// ========== 共享状态 ==========
const API = "";
let allPapers = [];
let currentPage = 1;
const pageSize = 20;
let collectionsData = { groups: [{ id: "default", name: "默认收藏夹" }], items: [] };
let currentGroupId = "default";
let checkedSet = new Set();
let currentSort = "";
let _sortReversed = false;
let lastAIQuery = "";
let _originalPapers = [];

// 全局搜索模式
let _searchMode = "normal";

// 期刊过滤和搜索历史（跨模块共享）
let selectedJournals = [];
let _historyCache = [];

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// encodeURIComponent + 单引号转义（用于 onclick 属性中的 JS 字符串安全嵌入）
function safeURI(str) {
  return encodeURIComponent(str || "").replace(/'/g, "%27");
}

// 前端日志回传到后端控制台（用于调试桌面应用）
function debugLog(msg) {
  console.log(msg);
  try { fetch(`${API}/api/log`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({msg}) }); } catch(e) {}
}

// 导出到 window 供其他模块使用
window.PaperLens = {
  API,
  get allPapers() { return allPapers; },
  set allPapers(v) { allPapers = v; },
  get currentPage() { return currentPage; },
  set currentPage(v) { currentPage = v; },
  get collectionsData() { return collectionsData; },
  set collectionsData(v) { collectionsData = v; },
  get currentGroupId() { return currentGroupId; },
  set currentGroupId(v) { currentGroupId = v; },
  get checkedSet() { return checkedSet; },
  set checkedSet(v) { checkedSet = v; },
  get currentSort() { return currentSort; },
  set currentSort(v) { currentSort = v; },
  get _sortReversed() { return _sortReversed; },
  set _sortReversed(v) { _sortReversed = v; },
  get lastAIQuery() { return lastAIQuery; },
  set lastAIQuery(v) { lastAIQuery = v; },
  get _originalPapers() { return _originalPapers; },
  set _originalPapers(v) { _originalPapers = v; },
  get _searchMode() { return _searchMode; },
  set _searchMode(v) { _searchMode = v; },
  get selectedJournals() { return selectedJournals; },
  set selectedJournals(v) { selectedJournals = v; },
  get _historyCache() { return _historyCache; },
  set _historyCache(v) { _historyCache = v; },
  pageSize,
  escapeHtml,
  safeURI,
  debugLog,
};

// 导出供其他模块直接引用
export {
  API,
  allPapers,
  currentPage,
  pageSize,
  collectionsData,
  currentGroupId,
  checkedSet,
  currentSort,
  _sortReversed,
  lastAIQuery,
  _originalPapers,
  _searchMode,
  selectedJournals,
  _historyCache,
  escapeHtml,
  safeURI,
  debugLog,
};