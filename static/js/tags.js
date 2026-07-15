// ========== 标签管理模块 ==========
import { API, escapeHtml } from './state.js';
import { t } from './i18n.js';

// 标签缓存
let _tagsCache = [];
let _activeTagFilter = null;

// 通过 getter 访问可变状态
function getAllPapers() { return window.PaperLens.allPapers; }
function getCollectionsData() { return window.PaperLens.collectionsData; }

// ========== API 调用 ==========

async function loadTags() {
  try {
    const r = await fetch(`${API}/api/tags`);
    if (r.ok) {
      const data = await r.json();
      _tagsCache = data.tags || [];
    }
  } catch { /* 忽略 */ }
}

async function createTag(name, color) {
  try {
    const r = await fetch(`${API}/api/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color }),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      _tagsCache.push(data.tag);
      return data.tag;
    }
    if (data.error === 'duplicate_name') {
      window.showToast(t('tagDuplicateName'));
    }
    return null;
  } catch {
    return null;
  }
}

async function updateTag(tagId, updates) {
  try {
    const r = await fetch(`${API}/api/tags/${tagId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      const idx = _tagsCache.findIndex(t => t.id === tagId);
      if (idx >= 0) _tagsCache[idx] = data.tag;
      return data.tag;
    }
    return null;
  } catch {
    return null;
  }
}

async function deleteTag(tagId) {
  try {
    const r = await fetch(`${API}/api/tags/${tagId}`, {
      method: 'DELETE',
    });
    if (r.ok) {
      _tagsCache = _tagsCache.filter(t => t.id !== tagId);
      // 同时清理收藏中的标签引用
      const collections = getCollectionsData();
      let changed = false;
      for (const item of (collections.items || [])) {
        const tags = item.tags || [];
        if (tags.includes(tagId)) {
          item.tags = tags.filter(t => t !== tagId);
          changed = true;
        }
      }
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

async function setPaperTags(paperDoi, paperTitle, groupId, tagIds) {
  // 通过 PATCH 更新收藏 item 的 tags 字段
  try {
    const r = await fetch(`${API}/api/collections/item`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doi: paperDoi || '',
        title: paperTitle || '',
        group_id: groupId || 'default',
        tags: tagIds,
      }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

// ========== 标签过滤 ==========

function getActiveTagFilter() {
  return _activeTagFilter;
}

function setActiveTagFilter(tagId) {
  if (_activeTagFilter === tagId) {
    _activeTagFilter = null; // 取消筛选
  } else {
    _activeTagFilter = tagId;
  }
  // 切换筛选时重置到第一页
  window.PaperLens.currentPage = 1;
  renderTagFilter();
  window.renderCollections();
  // 如果搜索结果存在，也过滤
  if (window.renderResults) window.renderResults();
  if (window.renderPagination) window.renderPagination();
}

function clearTagFilter() {
  _activeTagFilter = null;
  // 清除筛选时重置到第一页
  window.PaperLens.currentPage = 1;
  renderTagFilter();
  window.renderCollections();
  if (window.renderResults) window.renderResults();
  if (window.renderPagination) window.renderPagination();
}

function isPaperMatchingFilter(paper) {
  if (!_activeTagFilter) return true;
  // 检查论文是否在收藏中且有该标签
  const collections = getCollectionsData();
  const item = (collections.items || []).find(item => {
    if (paper.doi && item.doi && item.doi.toLowerCase() === paper.doi.toLowerCase()) return true;
    if (!paper.doi && paper.title && item.title && item.title === paper.title) return true;
    return false;
  });
  return item && (item.tags || []).includes(_activeTagFilter);
}

// ========== 渲染 ==========

function getTagById(tagId) {
  return _tagsCache.find(t => t.id === tagId) || null;
}

function renderTagPill(tag) {
  if (!tag) return '';
  return `<span class="tag-pill" style="--tag-bg:${tag.color}15;--tag-color:${tag.color}" onclick="event.stopPropagation();setActiveTagFilter('${tag.id}')"><span class="tag-pill-dot" style="background:${tag.color}"></span>${escapeHtml(tag.name)}</span>`;
}

function renderTagPills(tagIds) {
  if (!tagIds || !tagIds.length) return '';
  return tagIds.map(id => {
    const tag = getTagById(id);
    return tag ? renderTagPill(tag) : '';
  }).join('');
}

function renderTagFilter() {
  const container = document.getElementById('tagFilterList');
  const clearBtn = document.getElementById('tagFilterClear');
  if (!container) return;

  if (!_tagsCache.length) {
    const filterEl = document.getElementById('tagFilter');
    if (filterEl) filterEl.style.display = 'none';
    return;
  }

  const filterEl = document.getElementById('tagFilter');
  if (filterEl) filterEl.style.display = '';

  let html = _tagsCache.map(tag => {
    const isActive = _activeTagFilter === tag.id;
    return `<span class="tag-filter-pill${isActive ? ' active' : ''}" style="--tag-bg:${tag.color}15;--tag-color:${tag.color}" onclick="setActiveTagFilter('${tag.id}')">
      <span class="tag-pill-dot" style="background:${tag.color}"></span>
      ${escapeHtml(tag.name)}
    </span>`;
  }).join('');
  container.innerHTML = html;

  if (clearBtn) {
    clearBtn.classList.toggle('show', !!_activeTagFilter);
  }
}

function renderCollectionItemTags(item) {
  const tagIds = item.tags || [];
  if (!tagIds.length) return '';
  const pills = tagIds.map(id => {
    const tag = getTagById(id);
    if (!tag) return '';
    return `<span class="tag-pill" style="--tag-bg:${tag.color}15;--tag-color:${tag.color}"><span class="tag-pill-dot" style="background:${tag.color}"></span>${escapeHtml(tag.name)}</span>`;
  }).join('');
  return `<div class="collection-item-tags">${pills}</div>`;
}

// ========== Tag Selector（论文卡片标签选择） ==========

function _closeAllSelectors() {
  document.querySelectorAll('.tag-selector-dropdown.show').forEach(el => {
    el.classList.remove('show');
    el.style.left = ''; el.style.right = ''; el.style.top = ''; el.style.width = '';
    if (el._originalParent) { el._originalParent.appendChild(el); el._originalParent = null; }
    const card = el.closest('.paper-card');
    if (card) { card.style.zIndex = ''; card.style.position = ''; }
  });
}

function toggleTagSelector(e, paperIdx, triggerEl) {
  e.stopPropagation();
  // 使用传入的 triggerEl（内联 onclick 中 event.currentTarget 可能为 null）
  const el = triggerEl || e.currentTarget;
  const selector = el ? el.closest('.tag-selector') : null;
  if (!selector) return;
  const dropdown = selector.querySelector('.tag-selector-dropdown');
  if (!dropdown) return;

  const wasOpen = dropdown.classList.contains('show');
  _closeAllSelectors();
  if (wasOpen) return;

  // 渲染标签选项
  const paper = getAllPapers()[paperIdx];
  if (!paper) return;
  const collections = getCollectionsData();
  const existingItem = (collections.items || []).find(item => {
    if (paper.doi && item.doi && item.doi.toLowerCase() === paper.doi.toLowerCase()) return true;
    if (!paper.doi && paper.title && item.title && item.title === paper.title) return true;
    return false;
  });
  const currentTags = existingItem ? (existingItem.tags || []) : [];

  let optionsHtml = _tagsCache.map(tag => {
    const selected = currentTags.includes(tag.id);
    return `<div class="tag-option${selected ? ' selected' : ''}" onclick="event.stopPropagation();togglePaperTag('${paperIdx}','${tag.id}')">
      <span class="tag-option-dot" style="background:${tag.color}"></span>
      <span class="tag-option-name">${escapeHtml(tag.name)}</span>
      <span class="tag-option-check">✓</span>
    </div>`;
  }).join('');

  dropdown.innerHTML = `
    <div class="tag-option-list">${optionsHtml || '<div style="padding:8px;color:var(--text-secondary);font-size:12px">暂无标签</div>'}</div>
    <div class="tag-selector-footer">
      <button onclick="event.stopPropagation();closeAllTagSelectors();openTagManager()" style="padding:6px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);cursor:pointer;font-size:12px;color:var(--text)">🏷 ${t('manageTags') || '管理标签'}</button>
    </div>`;

  // 移到 body 下脱离 paper-card 的 contain/overflow 裁剪
  if (dropdown.parentElement !== document.body) {
    dropdown._originalParent = dropdown.parentElement;
    document.body.appendChild(dropdown);
  }
  // 用 fixed 定位相对于触发按钮
  const triggerRect = el.getBoundingClientRect();
  dropdown.style.position = 'fixed';
  dropdown.style.width = '200px';
  // 默认左对齐，右边界超出则翻转到右边对齐
  let left = triggerRect.left;
  if (left + 200 > window.innerWidth - 8) left = window.innerWidth - 208;
  dropdown.style.left = left + 'px';
  dropdown.style.top = (triggerRect.bottom + 4) + 'px';
  dropdown.classList.add('show');
  const card = selector.closest('.paper-card');
  if (card) { card.style.position = 'relative'; card.style.zIndex = '100'; }
}

async function quickCreateTag(paperIdx, name) {
  name = name.trim();
  if (!name || name.length > 50) {
    window.showToast(t('tagNameLength') || 'Tag name must be 1-50 characters');
    return;
  }
  try {
    const colors = ['#007AFF','#34C759','#FF9500','#FF3B30','#AF52DE','#5856D6','#FF2D55','#00C7BE'];
    const color = colors[Math.floor(Math.random() * colors.length)];
    const r = await fetch(`${API}/api/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color }),
    });
    if (r.ok) {
      await loadTags();
      // 自动应用新标签
      const newTag = _tagsCache.find(t => t.name === name);
      if (newTag) await togglePaperTag(paperIdx, newTag.id);
      _closeAllSelectors();
    } else {
      window.showToast(t('tagCreateFailed') || 'Failed to create tag');
    }
  } catch {
    window.showToast(t('tagCreateFailed') || 'Failed to create tag');
  }
}

function filterTagOptions(input) {
  const query = input.value.toLowerCase();
  const options = input.closest('.tag-selector-dropdown').querySelectorAll('.tag-option');
  options.forEach(opt => {
    const name = opt.querySelector('.tag-option-name').textContent.toLowerCase();
    opt.style.display = name.includes(query) ? '' : 'none';
  });
}

async function togglePaperTag(paperIdx, tagId) {
  const paper = getAllPapers()[paperIdx];
  if (!paper) return;

  const collections = getCollectionsData();
  let existingItem = (collections.items || []).find(item => {
    if (paper.doi && item.doi && item.doi.toLowerCase() === paper.doi.toLowerCase()) return true;
    if (!paper.doi && paper.title && item.title && item.title === paper.title) return true;
    return false;
  });

  // 如果论文不在收藏中，先自动添加到收藏
  if (!existingItem) {
    try {
      const r = await fetch(`${API}/api/collections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper: {
            doi: paper.doi || '',
            title: paper.title || '',
            authors: paper.authors || [],
            journal: paper.journal || '',
            year: paper.year || 0,
            citation_count: paper.citation_count || 0,
            oa_url: paper.oa_url || '',
            pmid: paper.pmid || '',
            abstract: paper.abstract || '',
            keywords: paper.keywords || [],
            source: paper.source || '',
            volume: paper.volume || '',
            issue: paper.issue || '',
            pages: paper.pages || '',
          },
          group_id: 'default',
        }),
      });
      if (r.ok) {
        // 重新加载收藏数据
        await window.loadCollections();
        // 重新查找 item
        const updatedCollections = getCollectionsData();
        existingItem = (updatedCollections.items || []).find(item => {
          if (paper.doi && item.doi && item.doi.toLowerCase() === paper.doi.toLowerCase()) return true;
          if (!paper.doi && paper.title && item.title && item.title === paper.title) return true;
          return false;
        });
      }
    } catch {
      // 添加失败则忽略
    }
  }

  let currentTags = existingItem ? [...(existingItem.tags || [])] : [];
  const tagIdx = currentTags.indexOf(tagId);
  if (tagIdx >= 0) {
    currentTags.splice(tagIdx, 1);
  } else {
    currentTags.push(tagId);
  }

  const paperDoi = paper.doi || '';
  const paperTitle = paper.title || '';
  const groupId = existingItem ? (existingItem.group_id || 'default') : 'default';

  // 保存原始 tags 用于回滚
  const originalTags = existingItem ? [...(existingItem.tags || [])] : [];

  // 乐观更新
  if (existingItem) {
    existingItem.tags = currentTags;
  }

  try {
    const ok = await setPaperTags(paperDoi, paperTitle, groupId, currentTags);
    if (ok) {
      await loadTags();
      // 异步推送到 Zotero MCP
      const tagIdsForNames = currentTags.map(id => {
        const tag = getTagById(id);
        return tag ? tag.name : null;
      }).filter(Boolean);
      if (tagIdsForNames.length > 0) {
        _pushTagsToZotero(paperDoi, paperTitle, tagIdsForNames);
      }
      renderTagFilter();
      if (window.renderResults) window.renderResults();
      if (window.renderPagination) window.renderPagination();
      if (window.renderCollections) window.renderCollections();
    } else {
      throw new Error('setPaperTags failed');
    }
  } catch {
    // API 失败或异常时回滚乐观更新
    if (existingItem) {
      existingItem.tags = originalTags;
    }
    if (window.renderResults) window.renderResults();
    if (window.renderCollections) window.renderCollections();
    window.showToast(t('tagUpdateFailed'));
  }
}

function closeAllTagSelectors() {
  _closeAllSelectors();
}
// 点击外部关闭
document.addEventListener("click", (e) => {
  if (!e.target.closest(".tag-selector") && !e.target.closest(".tag-selector-dropdown")) _closeAllSelectors();
});

// ========== Tag Manager Modal ==========

let _selectedColor = '#007AFF';

function openTagManager() {
  _closeAllSelectors();
  const overlay = document.getElementById('tagManagerOverlay');
  if (overlay) {
    overlay.classList.add('show');
    renderTagManagerList();
    const input = document.getElementById('newTagName');
    if (input) input.value = '';
  }
}

function closeTagManager() {
  const overlay = document.getElementById('tagManagerOverlay');
  if (overlay) overlay.classList.remove('show');
}

function renderColorPicker() {
  const picker = document.getElementById('tagColorPicker');
  if (!picker) return;
  const presets = ['#007AFF','#34C759','#FF9500','#FF3B30','#AF52DE','#5856D6','#FF2D55','#00C7BE',
                   '#8E44AD','#2ECC71','#E74C3C','#3498DB','#F39C12','#1ABC9C','#E91E63','#00BCD4'];
  let html = presets.map(c =>
    `<span class="tag-color-dot${c === _selectedColor ? ' selected' : ''}" style="background:${c}" onclick="selectTagColor('${c}')"></span>`
  ).join('');
  html += `<input type="color" id="tagCustomColor" value="${_selectedColor}" onchange="selectTagColor(this.value)" style="width:28px;height:28px;border:none;cursor:pointer;border-radius:50%;padding:0;vertical-align:middle" title="自定义颜色">`;
  picker.innerHTML = html;
}

function selectTagColor(color) {
  _selectedColor = color;
  renderColorPicker();
}

async function createTagFromModal() {
  const input = document.getElementById('newTagName');
  const name = input ? input.value.trim() : '';
  if (!name) {
    window.showToast(t('tagNameRequired'));
    return;
  }
  const colorInput = document.getElementById('tagColorPicker');
  const color = colorInput ? colorInput.value : '#007AFF';
  const tag = await createTag(name, color);
  if (tag) {
    if (input) input.value = '';
    renderTagManagerList();
    renderTagFilter();
    // 刷新论文卡片的标签选择器
    if (window.renderResults) window.renderResults();
  }
}

function renderTagManagerList() {
  const list = document.getElementById('tagManagerList');
  if (!list) return;

  if (!_tagsCache.length) {
    list.innerHTML = `<div class="tag-manager-empty">${t('noTagsYet')}</div>`;
    return;
  }

  list.innerHTML = _tagsCache.map(tag => `
    <div class="tag-manager-item">
      <span class="tag-manager-item-dot" style="background:${tag.color}"></span>
      <span class="tag-manager-item-name">${escapeHtml(tag.name)}</span>
      <span class="tag-manager-item-count">${tag.count || 0} ${t('papers')}</span>
      <div class="tag-manager-item-actions">
        <button onclick="editTag('${tag.id}')">✎</button>
        <button class="delete-btn" onclick="confirmDeleteTag('${tag.id}','${escapeHtml(tag.name)}')">✕</button>
      </div>
    </div>
  `).join('');
}

async function editTag(tagId) {
  const tag = getTagById(tagId);
  if (!tag) return;
  window.showPromptModal(t('editTagName') || '编辑标签名', tag.name, async newName => {
    if (!newName || !newName.trim()) return;
    const ok = await updateTag(tagId, { name: newName.trim() });
    if (ok) {
      renderTagManagerList();
      renderTagFilter();
      if (window.renderResults) window.renderResults();
    }
  });
}

async function confirmDeleteTag(tagId, tagName) {
  window.showConfirmModal('删除标签', t('deleteTagConfirm').replace('{name}', tagName), async () => {
    const ok = await deleteTag(tagId);
    if (ok) {
      if (_activeTagFilter === tagId) _activeTagFilter = null;
      renderTagManagerList();
      renderTagFilter();
      window.renderCollections();
      if (window.renderResults) window.renderResults();
      if (window.renderPagination) window.renderPagination();
    }
  });
}

// ========== Zotero 标签同步 ==========

async function importZoteroTags() {
  const btn = document.getElementById("importZoteroTagsBtn");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ 导入中..."; }
  try {
    const r = await fetch(`${API}/api/tags/import-zotero`, { method: "POST" });
    const data = await r.json();
    if (data.ok) {
      await loadTags();
      renderTagManagerList();
      window.showToast(`✅ 导入了 ${data.imported} 个 Zotero 标签`);
    } else {
      window.showToast("❌ " + (data.error || "导入失败"));
    }
  } catch (e) {
    window.showToast("❌ 导入失败: " + e.message);
  }
  if (btn) { btn.disabled = false; btn.textContent = "📥 导入 Zotero 标签"; }
}

// 推送标签到 Zotero MCP（异步，不阻塞UI）
async function _pushTagsToZotero(doi, title, tagNames) {
  try {
    const r = await fetch(`${API}/api/tags/push-to-zotero`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doi, title, tags: tagNames }),
    });
    const data = await r.json();
    if (data.ok) {
      debugLog(`[Tags] Pushed ${tagNames.length} tags to Zotero item ${data.itemKey}`);
    } else {
      console.warn('[Zotero] Tag sync failed:', data.error || 'unknown');
    }
  } catch (e) {
    console.warn('[Zotero] Tag sync error:', e.message || e);
  }
}

// ========== 初始化 ==========

async function initTags() {
  await loadTags();
  renderTagFilter();
}

// 导出到 window
window.getActiveTagFilter = getActiveTagFilter;
window.loadTags = loadTags;
window.renderTagFilter = renderTagFilter;
window.renderTagPills = renderTagPills;
window.renderCollectionItemTags = renderCollectionItemTags;
window.renderTagPill = renderTagPill;
window.setActiveTagFilter = setActiveTagFilter;
window.clearTagFilter = clearTagFilter;
window.toggleTagSelector = toggleTagSelector;
window.filterTagOptions = filterTagOptions;
window.togglePaperTag = togglePaperTag;
window.quickCreateTag = quickCreateTag;
window.importZoteroTags = importZoteroTags;
window.closeAllTagSelectors = closeAllTagSelectors;
window.openTagManager = openTagManager;
window.closeTagManager = closeTagManager;
window.selectTagColor = selectTagColor;
window.createTagFromModal = createTagFromModal;
window.editTag = editTag;
window.confirmDeleteTag = confirmDeleteTag;
window.initTags = initTags;

export {
  getActiveTagFilter,
  loadTags,
  renderTagFilter,
  renderTagPills,
  renderCollectionItemTags,
  renderTagPill,
  setActiveTagFilter,
  clearTagFilter,
  toggleTagSelector,
  togglePaperTag,
  closeAllTagSelectors,
  openTagManager,
  closeTagManager,
  createTagFromModal,
  editTag,
  confirmDeleteTag,
  initTags,
};
