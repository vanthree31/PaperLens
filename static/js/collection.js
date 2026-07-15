// ========== 收藏功能 ==========
// 只导入不可变值，可变状态通过 window.PaperLens 访问
import { API, pageSize, escapeHtml, safeURI, debugLog } from './state.js';
import { t, te, teAI, safeSetDisabled, currentLang } from './i18n.js';

// 通过 getter 函数访问可变状态
function getAllPapers() { return window.PaperLens.allPapers; }
function getCurrentPage() { return window.PaperLens.currentPage; }
function getCheckedSet() { return window.PaperLens.checkedSet; }
function getCollectionsData() { return window.PaperLens.collectionsData; }
function getCurrentGroupId() { return window.PaperLens.currentGroupId; }

// 收藏数据
let _lastCollectionsJson = "";

// 加载收藏数据
async function loadCollections() {
  try {
    const r = await fetch(`${API}/api/collections`);
    if (r.ok) {
      window.PaperLens.collectionsData = await r.json();
      renderGroupTabs();
      if (window.loadTags) await window.loadTags();
      if (window.renderTagFilter) window.renderTagFilter();
    } else {
      console.warn('[Collections] Load failed:', r.status);
      if (document.getElementById("collectionsPanel")?.classList.contains("show")) {
        window.showToast(t("collectionsLoadFailed"));
      }
    }
  } catch (e) {
    console.warn('[Collections] Load error:', e);
  }
}

// 刷新收藏数据
async function refreshCollections() {
  try {
    const r = await fetch(`${API}/api/collections`);
    if (!r.ok) {
      console.error('[Collections] Refresh failed:', r.status);
      window.showToast(t("collectionsLoadFailed"));
      return;
    }
    window.PaperLens.collectionsData = await r.json();
    renderGroupTabs();
    if (window.loadTags) await window.loadTags();
    if (window.renderTagFilter) window.renderTagFilter();
    renderCollections();
  } catch (e) {
    console.error('[Collections] Refresh error:', e);
    window.showToast(t("collectionsLoadFailed"));
  }
}

// 切换收藏面板
function toggleCollections() {
  const panel = document.getElementById("collectionsPanel");
  const overlay = document.getElementById("collectionsOverlay");
  panel.classList.toggle("show");
  overlay.classList.toggle("show");
  if (panel.classList.contains("show")) {
    // 打开面板时重新加载收藏数据和标签
    Promise.all([loadCollections(), window.loadTags ? window.loadTags() : Promise.resolve()]).then(() => {
      if (window.renderTagFilter) window.renderTagFilter();
      renderCollections();
    });
  }
}

// 渲染分组标签
function renderGroupTabs() {
  const tabs = document.getElementById("groupTabs");
  if (!tabs) return;
  const groups = (window.PaperLens.collectionsData.groups || []);
  let html = groups.map(g => {
    const isActive = g.id === window.PaperLens.currentGroupId;
    const canDelete = g.id !== 'default';
    const displayName = g.id === 'default' ? t('defaultGroup') : g.name;
    const safeId = escapeHtml(g.id);
    const safeName = escapeHtml(displayName);
    return `<span class="group-tab-wrapper">
      <button class="group-tab${isActive ? ' active' : ''}" onclick="switchGroup('${safeId}')">${safeName}</button>
      ${canDelete ? `<button class="group-tab-delete" onclick="deleteGroup('${safeId}', this.getAttribute('data-name'))" data-name="${safeName}" title="${t('deleteGroup')}">✕</button>` : ''}
    </span>`;
  }).join('');
  html += `<button class="add-group-btn" onclick="addGroup()">${t('newGroup')}</button>`;
  tabs.innerHTML = html;
}

// 切换分组
function switchGroup(groupId) {
  window.PaperLens.currentGroupId = groupId;
  renderGroupTabs();
  renderCollections();
}

// 添加分组
function addGroup() {
  showPromptModal(t('enterGroupName') || '输入收藏夹名称', '', name => {
    if (!name || !name.trim()) return;
    const id = 'group_' + Date.now();
    window.PaperLens.collectionsData.groups = window.PaperLens.collectionsData.groups || [];
    window.PaperLens.collectionsData.groups.push({ id, name: name.trim() });
    saveCollectionGroups();
    window.PaperLens.currentGroupId = id;
    renderGroupTabs();
    renderCollections();
  });
}

// 删除分组
async function deleteGroup(groupId, groupName) {
  const confirmMsg = t('deleteGroupConfirm').replace('{name}', groupName);
  showConfirmModal('删除收藏夹', confirmMsg, async () => {
    try {
      const r = await fetch(`${API}/api/collections/groups`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_id: groupId }),
      });
      if (r.ok) {
        window.PaperLens.collectionsData.items = (window.PaperLens.collectionsData.items || []).filter(item => (item.group_id || "default") !== groupId);
        window.PaperLens.collectionsData.groups = (window.PaperLens.collectionsData.groups || []).filter(g => g.id !== groupId);
        if (window.PaperLens.currentGroupId === groupId) {
          window.PaperLens.currentGroupId = 'default';
        }
        renderGroupTabs();
        renderCollections();
      } else {
        window.showToast(t("deleteGroupFailed"));
      }
    } catch (e) {
      window.showToast(t("deleteGroupFailed"));
    }
  });
}

// 保存分组配置
async function saveCollectionGroups() {
  try {
    const r = await fetch(`${API}/api/collections/groups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groups: window.PaperLens.collectionsData.groups }),
    });
    if (!r.ok) {
      window.showToast(t("saveGroupFailed"));
    }
  } catch (e) {
    window.showToast(t("saveGroupFailed"));
  }
}

// 渲染收藏列表
function renderCollections() {
  const body = document.getElementById("collectionsBody");
  if (!body) return;
  const activeTagFilter = window.getActiveTagFilter ? window.getActiveTagFilter() : null;
  const items = (window.PaperLens.collectionsData.items || []).filter(item => {
    if ((item.group_id || "default") !== window.PaperLens.currentGroupId) return false;
    if (activeTagFilter) {
      return (item.tags || []).includes(activeTagFilter);
    }
    return true;
  });
  if (items.length === 0) {
    body.innerHTML = `<div class="collections-empty"><div class="icon">📚</div><p>${t("collectionsEmpty")}</p></div>`;
    return;
  }
  let html = '';
  items.forEach((item, i) => {
    const authors = (item.authors || []).length > 2 ? item.authors.slice(0, 2).map(a => escapeHtml(a)).join(", ") + " et al." : (item.authors || []).map(a => escapeHtml(a)).join(", ");
    const citedText = item.citation_count > 0 ? `· ${t("cited")} ${item.citation_count.toLocaleString()}` : '';
    const volumeInfo = item.volume ? `, ${escapeHtml(item.volume)}` : '';
    const issueInfo = item.issue ? ` (${escapeHtml(item.issue)})` : '';
    const pagesInfo = item.pages ? `, ${escapeHtml(item.pages)}` : '';
    const readingStatus = item.reading_status || "unread";
    const statusClass = window.getReadingStatusIcon ? window.getReadingStatusIcon(readingStatus) : '';
    const statusLabel = window.getReadingStatusLabel ? window.getReadingStatusLabel(readingStatus) : '';
    html += `
    <div class="collection-item" onclick="viewCollectionItem('${item.doi ? safeURI(item.doi) : ''}')">
      <div class="title">${escapeHtml(item.title) || t("noTitle")}</div>
      <div class="meta">${authors} · ${escapeHtml(item.journal)}${volumeInfo}${issueInfo}${pagesInfo} (${item.year || "?"}) ${citedText}</div>
      ${window.renderCollectionItemTags ? window.renderCollectionItemTags(item) : ''}
      <div class="actions">
        <span class="reading-status ${statusClass}" onclick="event.stopPropagation();toggleReadingStatus('${item.doi ? safeURI(item.doi) : ''}','${readingStatus}')" title="${t('readingStatusTip')}">
          <span class="reading-status-dot"></span>
          ${statusLabel}
        </span>
        ${item.doi ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();window.open('https://doi.org/${encodeURIComponent(item.doi)}')">${t("original")}</button>` : ''}
        ${item.doi ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();showCitationGraph('${safeURI(item.doi)}','${safeURI(item.title || '')}')">${t("citationGraph")}</button>` : ''}
        <button class="btn btn-sm btn-outline" style="color:var(--danger)" onclick="event.stopPropagation();removeFromCollection('${item.doi ? safeURI(item.doi) : ''}', '${safeURI(item.title || '')}')">${t("remove")}</button>
      </div>
    </div>`;
  });
  body.innerHTML = html;
}

// 查看收藏项
function viewCollectionItem(encodedDoi) {
  const doi = (encodedDoi && encodedDoi !== "undefined") ? decodeURIComponent(encodedDoi) : "";
  if (!doi) {
    window.showToast(t("noDOI"));
    return;
  }
  const idx = getAllPapers().findIndex(p => p.doi && p.doi.toLowerCase() === doi.toLowerCase());
  if (idx >= 0) {
    toggleCollections();
    const targetPage = Math.floor(idx / window.PaperLens.pageSize) + 1;
    if (targetPage !== getCurrentPage()) {
      window.PaperLens.currentPage = targetPage;
      window.renderResults();
      window.renderPagination();
    }
    setTimeout(() => {
      const card = document.getElementById(`card-${idx}`);
      if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.style.outline = "2px solid var(--primary)";
        setTimeout(() => { card.style.outline = ""; }, 2000);
      }
    }, 100);
    return;
  }
  window.open(`https://doi.org/${encodeURIComponent(doi)}`);
}

// 切换收藏状态
async function toggleFavorite(idx, btn) {
  if (toggleFavorite._running) return;
  toggleFavorite._running = true;
  try {
    const paper = getAllPapers()[idx];
    if (!paper) return;
    // 检查是否已收藏（任意分组）
    let existingItem = null;
    if (window.PaperLens.collectionsData.items) {
      existingItem = window.PaperLens.collectionsData.items.find(item => {
        if (paper.doi && item.doi) return item.doi.toLowerCase() === paper.doi.toLowerCase();
        if (!paper.doi && paper.title && item.title) return item.title === paper.title;
        return false;
      });
    }
    if (existingItem) {
      // 已收藏 → 取消收藏
      await removeFromCollection(
        paper.doi ? encodeURIComponent(paper.doi) : null,
        paper.doi ? null : encodeURIComponent(paper.title || ''),
        existingItem.group_id || "default"
      );
    } else {
      // 未收藏 → 弹窗选分组
      const groups = window.PaperLens.collectionsData.groups || [];
      if (groups.length <= 1) {
        // 只有一个分组，直接存
        await addToCollection(paper, groups[0]?.id || "default");
      } else {
        showGroupPicker(paper);
      }
    }
  } finally {
    toggleFavorite._running = false;
  }
}

function showGroupPicker(paper, callback) {
  const groups = window.PaperLens.collectionsData.groups || [];
  const s = _glassModalStyles();
  const overlay = document.createElement("div");
  overlay.className = "group-picker-overlay";
  overlay.style.cssText = `position:fixed;inset:0;background:${s.overlayBg};backdrop-filter:${s.overlayBlur};-webkit-backdrop-filter:${s.overlayBlur};z-index:1200;display:flex;align-items:center;justify-content:center`;
  let html = `<div style="position:relative;background:${s.cardBg};backdrop-filter:${s.cardBlur};-webkit-backdrop-filter:${s.cardBlur};border:1px solid ${s.cardBorder};border-radius:16px;padding:24px;min-width:280px;max-width:360px;box-shadow:${s.cardShadow},${s.insetTop};overflow:hidden">`;
  html += `<div style="position:absolute;inset:0;background:${s.highlight};pointer-events:none;z-index:0"></div>`;
  html += `<div style="position:absolute;top:0;left:0;right:0;height:1px;background:${s.refraction};pointer-events:none;z-index:0"></div>`;
  html += '<div style="position:relative;z-index:1">';
  html += `<div style="font-size:14px;font-weight:600;margin-bottom:12px;color:${s.textColor}">选择收藏夹</div>`;
  html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">';
  for (const g of groups) {
    const name = escapeHtml(g.name || "默认收藏夹");
    html += `<button class="group-pick-btn" data-gid="${g.id}" style="padding:8px 14px;border:1px solid ${s.btnBorder};border-radius:10px;background:${s.btnBg};cursor:pointer;font-size:13px;color:${s.textColor};transition:all 0.15s">${name}</button>`;
  }
  html += '</div>';
  html += `<button class="group-pick-cancel" style="width:100%;padding:8px;border:none;background:transparent;color:${s.subColor};cursor:pointer;font-size:13px;border-radius:8px">取消</button>`;
  html += '</div></div>';
  overlay.innerHTML = html;
  const style = document.createElement("style");
  style.textContent = ".group-pick-btn:hover { transform:scale(1.03); filter:brightness(1.1); } .group-pick-cancel:hover { background:rgba(128,128,128,0.1); }";
  overlay.appendChild(style);
  overlay.addEventListener("click", async e => {
    if (e.target === overlay || e.target.classList.contains("group-pick-cancel")) {
      overlay.remove();
      return;
    }
    const btn = e.target.closest(".group-pick-btn");
    if (!btn) return;
    const gid = btn.dataset.gid;
    overlay.remove();
    if (callback) {
      callback(gid);
    } else {
      await addToCollection(paper, gid);
    }
  });
  document.body.appendChild(overlay);
}

// 添加到收藏
async function addToCollection(paper, groupId) {
  try {
    const gid = groupId || window.PaperLens.currentGroupId || "default";
    const r = await fetch(`${API}/api/collections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper, group_id: gid }),
    });
    if (r.ok) {
      const resp = await r.json();
      await loadCollections();
      window.renderResults();
      window.renderPagination();
      const panel = document.getElementById("collectionsPanel");
      if (panel && panel.classList.contains("show")) {
        renderCollections();
      }
      if (resp.message === '已收藏') {
        window.showToast(t("alreadyCollected") || resp.message);
      } else {
        window.showToast(t("addedToCollection"));
      }
    }
  } catch (e) {
    window.showToast(t("operationFailed"));
  }
}

// 从收藏移除
async function removeFromCollection(encodedDoi, encodedTitle, groupId) {
  const doi = encodedDoi ? decodeURIComponent(encodedDoi) : null;
  const title = encodedTitle ? decodeURIComponent(encodedTitle) : null;
  try {
    const r = await fetch(`${API}/api/collections`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doi, title, group_id: groupId || window.PaperLens.currentGroupId }),
    });
    if (r.ok) {
      await loadCollections();
      renderCollections();
      window.renderResults();
      window.renderPagination();
      window.showToast(t("removedFromCollection"));
    }
  } catch (e) {
    window.showToast(t("operationFailed"));
  }
}

// 推荐功能
let recommendPapers = [];

function toggleRecommend() {
  const panel = document.getElementById("recommendPanel");
  const overlay = document.getElementById("recommendOverlay");
  panel.classList.toggle("show");
  overlay.classList.toggle("show");
  if (panel.classList.contains("show")) {
    loadRecommendations();
  }
}

async function loadRecommendations() {
  const body = document.getElementById("recommendBody");
  if (!body) return;
  body.innerHTML = `<div class="collections-empty"><div class="spinner"></div><p>${t("recommendLoading")}</p></div>`;
  try {
    const r = await fetch(`${API}/api/recommendations?lang=${currentLang}`);
    const data = await r.json();
    if (data.papers && data.papers.length > 0) {
      recommendPapers = data.papers;
      renderRecommendations(data);
    } else {
      body.innerHTML = `<div class="collections-empty">
        <div class="icon">📚</div>
        <p>${t("recommendEmpty")}</p>
        <p style="font-size:12px;margin-top:8px;color:#94a3b8">${t("recommendHint")}</p>
        ${data.keywords && data.keywords.length > 0 ? `<p style="font-size:12px;margin-top:12px;color:#64748b">${t("interestKeywords")}：${data.keywords.slice(0, 5).join(" · ")}</p>` : ''}
      </div>`;
    }
  } catch (e) {
    body.innerHTML = `<div class="collections-empty">
      <div class="icon">⚠️</div>
      <p>${t("recommendFailed")}</p>
      <p style="font-size:12px;margin-top:8px;color:#94a3b8">${e.message}</p>
    </div>`;
  }
}

function renderRecommendations(data) {
  const body = document.getElementById("recommendBody");
  if (!body) return;
  let html = '';
  const recommendType = data.recommendation_type || "keyword";
  const typeHintMap = {
    keyword: t("recommendTypeKeyword"),
    journal: t("recommendTypeJournal"),
    citation: t("recommendTypeCitation"),
    mixed: t("recommendTypeMixed"),
  };
  const typeHint = typeHintMap[recommendType] || t("recommendTypeKeyword");
  html += `<div style="padding:6px 12px;margin-bottom:8px;background:#f8fafc;border-radius:6px;font-size:11px;color:#64748b">
    💡 ${typeHint}
  </div>`;
  if (data.keywords && data.keywords.length > 0) {
    html += `<div style="padding:8px 12px;margin-bottom:12px;background:#f0f9ff;border-radius:8px;font-size:12px">
      <div style="font-weight:600;color:#1e40af;margin-bottom:4px">${t("yourInterests")}</div>
      <div style="color:#3b82f6">${data.keywords.slice(0, 8).join(" · ")}</div>
    </div>`;
  }
  html += '<div style="display:flex;flex-direction:column;gap:8px">';
  data.papers.forEach((paper, idx) => {
    const title = escapeHtml(paper.title || "");
    const authors = (paper.authors || []).slice(0, 3).map(a => escapeHtml(a)).join(", ");
    const journal = escapeHtml(paper.journal || "");
    const year = paper.year || "";
    const citations = paper.citation_count || 0;
    const doi = escapeHtml(paper.doi || "");
    html += `<div class="collection-item" onclick="openRecommendPaper(${idx})" style="cursor:pointer">
      <div class="title">${title}</div>
      <div class="meta">
        ${authors}${authors && journal ? ' · ' : ''}${journal}${year ? ` (${year})` : ''}
        ${citations > 0 ? ` · <span style="color:#2563eb">${t("cited")} ${citations}</span>` : ''}
      </div>
      ${doi ? `<div class="meta" style="color:#64748b;font-size:11px;margin-top:2px">DOI: ${doi}</div>` : ''}
    </div>`;
  });
  html += '</div>';
  body.innerHTML = html;
}

function openRecommendPaper(idx) {
  const paper = recommendPapers[idx];
  if (!paper) return;
  const ap = getAllPapers();
  const isDuplicate = paper.doi
    ? ap.some(p => p.doi && p.doi.toLowerCase() === paper.doi.toLowerCase())
    : ap.some(p => p.title === paper.title);
  if (!isDuplicate) {
    ap.unshift(paper);
    const shifted = new Set();
    getCheckedSet().forEach(i => shifted.add(i + 1));
    window.PaperLens.checkedSet = shifted;
    window.PaperLens.currentPage = 1;
    window.renderResults();
    window.renderPagination();
  }
  recordReadingAction('recommend_click', paper);
  toggleRecommend();
  window.showToast(t("recommendAdded"));
}

// 记录阅读行为
async function recordReadingAction(action, paper) {
  try {
    await fetch(`${API}/api/reading-history`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ action, paper }),
    });
  } catch { /* 忽略 */ }
}

// 导出到 window 供其他模块使用
window.loadCollections = loadCollections;
window.toggleCollections = toggleCollections;
window.refreshCollections = refreshCollections;
window.renderCollections = renderCollections;
window.renderGroupTabs = renderGroupTabs;
window.switchGroup = switchGroup;
window.addGroup = addGroup;
window.deleteGroup = deleteGroup;
window.viewCollectionItem = viewCollectionItem;
window.toggleFavorite = toggleFavorite;
window.addToCollection = addToCollection;
window.removeFromCollection = removeFromCollection;
window.toggleRecommend = toggleRecommend;
window.loadRecommendations = loadRecommendations;
window.openRecommendPaper = openRecommendPaper;
window.recordReadingAction = recordReadingAction;

async function importFromZotero() {
  const btn = document.getElementById("importZoteroBtn");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ 导入中..."; }
  try {
    const r = await fetch(`${API}/api/collections/import-from-zotero`, { method: "POST" });
    const data = await r.json();
    if (data.ok) {
      window.showToast(`✓ 已导入 ${data.added} 篇文献到「Zotero」收藏夹（共 ${data.total} 篇）`);
      refreshCollections();
    } else {
      const diag = data.diagnosis || {};
      console.log("Zotero import diagnosis:", JSON.stringify(diag, null, 2));
      window.showToast("✗ " + (data.hint || "导入失败") +
        ` [API:${diag.native_api || "?"}] [SQLite:${diag.sqlite || "?"}]`);
    }
  } catch (e) {
    window.showToast("导入失败: " + e.message);
  }
  if (btn) { btn.disabled = false; btn.textContent = "📥 从 Zotero 导入"; }
}

window.importFromZotero = importFromZotero;

// ========== 文件拖入导入 ==========
function initDropZone() {
  const panel = document.getElementById("collectionsPanel");
  if (!panel) return;
  panel.addEventListener("dragover", e => {
    e.preventDefault();
    e.stopPropagation();
    panel.style.boxShadow = "0 0 0 2px var(--primary)";
  });
  panel.addEventListener("dragleave", e => {
    e.preventDefault();
    panel.style.boxShadow = "";
  });
  panel.addEventListener("drop", async e => {
    e.preventDefault();
    e.stopPropagation();
    panel.style.boxShadow = "";
    const files = e.dataTransfer.files;
    if (!files.length) return;
    const groups = window.PaperLens.collectionsData.groups || [];
    if (groups.length <= 1) {
      await handleFileImport(files, groups[0]?.id || "default");
    } else {
      showGroupPicker(null, gid => handleFileImport(files, gid));
    }
  });
  // Click fallback: hidden <input> triggered by drag hint
  const emptyEl = document.getElementById("collectionsEmpty");
  if (emptyEl) {
    emptyEl.style.cursor = "pointer";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = ".xml,.ris,.bib,.enw,.csv,.tsv,.txt,.nbib,.json";
    fileInput.style.display = "none";
    fileInput.addEventListener("change", async () => {
      if (!fileInput.files.length) return;
      const groups = window.PaperLens.collectionsData.groups || [];
      if (groups.length <= 1) {
        await handleFileImport(fileInput.files, groups[0]?.id || "default");
      } else {
        showGroupPicker(null, gid => handleFileImport(fileInput.files, gid));
      }
      fileInput.value = "";
    });
    document.body.appendChild(fileInput);
    emptyEl.addEventListener("click", () => fileInput.click());
  }
}

async function handleFileImport(files, groupId) {
  const fileArr = Array.from(files);
  window.showToast(`⏳ 正在解析 ${fileArr.length} 个文件...`);
  const fileData = [];
  for (const f of fileArr) {
    try {
      const text = await f.text();
      fileData.push({ name: f.name, content: text });
    } catch (err) {
      console.warn("Failed to read file:", f.name, err);
    }
  }
  if (!fileData.length) {
    window.showToast("✗ 无法读取文件");
    return;
  }
  const gid = groupId || "default";
  try {
    const r = await fetch(`${API}/api/import-file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: fileData, group_id: gid }),
    });
    const data = await r.json();
    if (data.ok) {
      window.showToast(`✓ 已导入 ${data.added} 篇（${data.skipped} 篇重复跳过）`);
      refreshCollections();
    } else {
      window.showToast("✗ " + (data.hint || "导入失败"));
    }
  } catch (err) {
    window.showToast("导入失败: " + err.message);
  }
}

// ========== 液态玻璃弹窗组件 ==========
function _glassModalStyles() {
  const theme = document.documentElement.getAttribute("data-theme") || "auto";
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = theme === "dark" || (theme === "auto" && prefersDark);
  const rootStyle = getComputedStyle(document.documentElement);
  // 复用全局 CSS 变量，与 onboarding-tooltip 完全一致
  const cardBg = rootStyle.getPropertyValue("--glass-e-bg").trim() || (isDark ? "rgba(30,30,35,0.94)" : "rgba(255,255,255,0.92)");
  const cardBlur = rootStyle.getPropertyValue("--glass-e-blur").trim() || "blur(20px) saturate(180%)";
  const cardBorder = rootStyle.getPropertyValue("--glass-e-border").trim() || (isDark ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.6)");
  const cardShadow = rootStyle.getPropertyValue("--glass-e-shadow").trim() || "0 8px 32px rgba(0,0,0,0.12)";
  const insetTop = rootStyle.getPropertyValue("--glass-inset-top").trim() || "inset 0 1px 0 rgba(255,255,255,0.5)";
  const highlight = rootStyle.getPropertyValue("--glass-highlight").trim() || "linear-gradient(135deg, rgba(255,255,255,0.1) 0%, transparent 50%)";
  const refraction = rootStyle.getPropertyValue("--glass-refraction").trim() || "rgba(255,255,255,0.6)";
  return {
    isDark,
    overlayBg: rootStyle.getPropertyValue("--glass-overlay-bg").trim() || "rgba(0,0,0,0.4)",
    overlayBlur: rootStyle.getPropertyValue("--glass-overlay-blur").trim() || "blur(4px)",
    cardBg, cardBlur, cardBorder, cardShadow, insetTop, highlight, refraction,
    textColor: isDark ? "#e0e0e0" : "#1d1d1f",
    subColor: isDark ? "#98989d" : "#6e6e73",
    inputBg: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)",
    inputBorder: isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)",
    btnBg: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)",
    btnBorder: isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)",
  };
}

function showPromptModal(title, placeholder, callback) {
  const s = _glassModalStyles();
  const overlay = document.createElement("div");
  overlay.style.cssText = `position:fixed;inset:0;background:${s.overlayBg};backdrop-filter:${s.overlayBlur};-webkit-backdrop-filter:${s.overlayBlur};z-index:1200;display:flex;align-items:center;justify-content:center`;
  overlay.innerHTML = `<div style="position:relative;background:${s.cardBg};backdrop-filter:${s.cardBlur};-webkit-backdrop-filter:${s.cardBlur};border:1px solid ${s.cardBorder};border-radius:16px;padding:24px;min-width:300px;max-width:400px;box-shadow:${s.cardShadow},${s.insetTop};overflow:hidden">
    <div style="position:absolute;inset:0;background:${s.highlight};pointer-events:none;z-index:0"></div>
    <div style="position:absolute;top:0;left:0;right:0;height:1px;background:${s.refraction};pointer-events:none;z-index:0"></div>
    <div style="position:relative;z-index:1">
      <div style="font-size:15px;font-weight:600;margin-bottom:16px;color:${s.textColor}">${escapeHtml(title)}</div>
      <input id="_pmInput" style="width:100%;padding:10px 12px;border:1px solid ${s.inputBorder};border-radius:10px;background:${s.inputBg};color:${s.textColor};font-size:13px;outline:none;box-sizing:border-box" placeholder="${escapeHtml(placeholder)}" autofocus>
      <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end">
        <button id="_pmCancel" style="padding:8px 16px;border:1px solid ${s.btnBorder};border-radius:10px;background:${s.btnBg};color:${s.subColor};cursor:pointer;font-size:13px">取消</button>
        <button id="_pmOk" style="padding:8px 20px;border:none;border-radius:10px;background:var(--primary,#007AFF);color:#fff;cursor:pointer;font-size:13px;font-weight:500">确定</button>
      </div>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  const input = document.getElementById("_pmInput");
  const submit = () => { overlay.remove(); callback(input.value.trim()); };
  document.getElementById("_pmOk").onclick = submit;
  document.getElementById("_pmCancel").onclick = () => { overlay.remove(); };
  input.addEventListener("keydown", e => { if (e.key === "Enter") submit(); if (e.key === "Escape") overlay.remove(); });
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
  setTimeout(() => input.focus(), 100);
}

function showConfirmModal(title, message, callback) {
  const s = _glassModalStyles();
  const overlay = document.createElement("div");
  overlay.style.cssText = `position:fixed;inset:0;background:${s.overlayBg};backdrop-filter:${s.overlayBlur};-webkit-backdrop-filter:${s.overlayBlur};z-index:1200;display:flex;align-items:center;justify-content:center`;
  overlay.innerHTML = `<div style="position:relative;background:${s.cardBg};backdrop-filter:${s.cardBlur};-webkit-backdrop-filter:${s.cardBlur};border:1px solid ${s.cardBorder};border-radius:16px;padding:24px;min-width:300px;max-width:400px;box-shadow:${s.cardShadow},${s.insetTop};overflow:hidden">
    <div style="position:absolute;inset:0;background:${s.highlight};pointer-events:none;z-index:0"></div>
    <div style="position:absolute;top:0;left:0;right:0;height:1px;background:${s.refraction};pointer-events:none;z-index:0"></div>
    <div style="position:relative;z-index:1">
      <div style="font-size:15px;font-weight:600;margin-bottom:8px;color:${s.textColor}">${escapeHtml(title)}</div>
      <div style="font-size:13px;color:${s.subColor};margin-bottom:16px;line-height:1.5">${escapeHtml(message)}</div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_cmCancel" style="padding:8px 16px;border:1px solid ${s.btnBorder};border-radius:10px;background:${s.btnBg};color:${s.subColor};cursor:pointer;font-size:13px">取消</button>
        <button id="_cmOk" style="padding:8px 20px;border:none;border-radius:10px;background:var(--danger,#FF3B30);color:#fff;cursor:pointer;font-size:13px;font-weight:500">删除</button>
      </div>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  document.getElementById("_cmOk").onclick = () => { overlay.remove(); callback(); };
  document.getElementById("_cmCancel").onclick = () => overlay.remove();
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
  overlay.addEventListener("keydown", e => { if (e.key === "Escape") overlay.remove(); });
}

// 导出弹窗组件到 window（tags/index 等模块共享）
window.showPromptModal = showPromptModal;
window.showConfirmModal = showConfirmModal;

// 页面加载时初始化
document.addEventListener("DOMContentLoaded", initDropZone);

export {
  loadCollections,
  refreshCollections,
  toggleCollections,
  renderCollections,
  renderGroupTabs,
  switchGroup,
  addGroup,
  deleteGroup,
  viewCollectionItem,
  toggleFavorite,
  addToCollection,
  removeFromCollection,
  toggleRecommend,
  openRecommendPaper,
  importFromZotero,
  recordReadingAction,
};