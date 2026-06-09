// PaperLens DOI Lookup 弹出窗口逻辑

document.addEventListener('DOMContentLoaded', () => {
  // DOM 元素
  const connectionStatus = document.getElementById('connectionStatus');
  const doisSection = document.getElementById('doisSection');
  const doisList = document.getElementById('doisList');
  const paperSection = document.getElementById('paperSection');
  const paperTitle = document.getElementById('paperTitle');
  const paperAuthors = document.getElementById('paperAuthors');
  const paperJournal = document.getElementById('paperJournal');
  const paperYear = document.getElementById('paperYear');
  const paperCitations = document.getElementById('paperCitations');
  const paperDoi = document.getElementById('paperDoi');
  const paperAbstract = document.getElementById('paperAbstract');
  const paperKeywords = document.getElementById('paperKeywords');
  const btnCollect = document.getElementById('btnCollect');
  const btnZotero = document.getElementById('btnZotero');
  const btnOpenOa = document.getElementById('btnOpenOa');
  const message = document.getElementById('message');
  const emptyState = document.getElementById('emptyState');
  const errorState = document.getElementById('errorState');
  const errorMessage = document.getElementById('errorMessage');
  const btnRetry = document.getElementById('btnRetry');

  // 当前论文数据
  let currentPaper = null;

  // 初始化
  init();

  async function init() {
    // 检查 PaperLens 连接
    checkConnection();

    // 检测当前标签页的 DOI
    detectDois();

    // 绑定重试按钮
    btnRetry.addEventListener('click', () => {
      errorState.style.display = 'none';
      detectDois();
    });
  }

  /**
   * 检查 PaperLens 连接状态
   */
  async function checkConnection() {
    try {
      const response = await chrome.runtime.sendMessage({ action: 'checkConnection' });
      const dot = connectionStatus.querySelector('.status-dot');
      const text = connectionStatus.querySelector('.status-text');

      if (response.connected) {
        dot.className = 'status-dot connected';
        text.textContent = '已连接';
      } else {
        dot.className = 'status-dot disconnected';
        text.textContent = '未连接';
      }
    } catch {
      const dot = connectionStatus.querySelector('.status-dot');
      const text = connectionStatus.querySelector('.status-text');
      dot.className = 'status-dot disconnected';
      text.textContent = '未连接';
    }
  }

  /**
   * 检测当前标签页的 DOI
   */
  async function detectDois() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

      if (!tab) {
        showEmpty();
        return;
      }

      // 向 content script 发送消息
      const response = await chrome.tabs.sendMessage(tab.id, { action: 'detectDois' });

      if (response && response.dois && response.dois.length > 0) {
        showDoiList(response.dois);
      } else {
        showEmpty();
      }
    } catch (error) {
      // content script 可能未加载
      console.error('检测 DOI 失败:', error);
      showEmpty();
    }
  }

  /**
   * 显示 DOI 列表
   */
  function showDoiList(dois) {
    doisSection.style.display = 'block';
    emptyState.style.display = 'none';
    errorState.style.display = 'none';

    doisList.innerHTML = '';

    dois.forEach(doi => {
      const item = document.createElement('div');
      item.className = 'doi-item';
      item.innerHTML = `
        <span class="doi-text">${escapeHtml(doi)}</span>
        <button class="btn btn-sm btn-primary doi-query" data-doi="${escapeHtml(doi)}">查询</button>
      `;
      doisList.appendChild(item);
    });

    // 绑定查询按钮
    document.querySelectorAll('.doi-query').forEach(btn => {
      btn.addEventListener('click', () => {
        const doi = btn.dataset.doi;
        queryPaper(doi);
      });
    });

    // 如果只有一个 DOI，自动查询
    if (dois.length === 1) {
      queryPaper(dois[0]);
    }
  }

  /**
   * 查询论文详情
   */
  async function queryPaper(doi) {
    showLoading('正在查询论文...');

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'queryPaper',
        doi: doi
      });

      if (response.success) {
        currentPaper = response.paper;
        showPaper(response.paper);
      } else {
        showError(response.error || '查询失败');
      }
    } catch (error) {
      showError('无法连接到 PaperLens，请确保应用正在运行');
    }
  }

  /**
   * 显示论文详情
   */
  function showPaper(paper) {
    doisSection.style.display = 'none';
    paperSection.style.display = 'block';
    emptyState.style.display = 'none';
    errorState.style.display = 'none';
    message.style.display = 'none';

    paperTitle.textContent = unescapeHtml(paper.title || '无标题');
    paperAuthors.textContent = paper.authors ? paper.authors.join(', ') : '未知作者';
    paperJournal.textContent = paper.journal || '未知期刊';
    paperYear.textContent = paper.year || '未知年份';
    paperCitations.textContent = paper.citation_count || '0';
    paperDoi.textContent = paper.doi || '-';

    // 摘要
    if (paper.abstract) {
      paperAbstract.textContent = '';
      const strong = document.createElement('strong');
      strong.textContent = '摘要：';
      paperAbstract.appendChild(strong);
      paperAbstract.appendChild(document.createTextNode(unescapeHtml(paper.abstract)));
      paperAbstract.style.display = 'block';
    } else {
      paperAbstract.style.display = 'none';
    }

    // 关键词
    if (paper.keywords && paper.keywords.length > 0) {
      paperKeywords.textContent = '';
      const strong = document.createElement('strong');
      strong.textContent = '关键词：';
      paperKeywords.appendChild(strong);
      paper.keywords.forEach(k => {
        const span = document.createElement('span');
        span.className = 'keyword';
        span.textContent = unescapeHtml(k);
        paperKeywords.appendChild(document.createTextNode(' '));
        paperKeywords.appendChild(span);
      });
      paperKeywords.style.display = 'block';
    } else {
      paperKeywords.style.display = 'none';
    }

    // OA 链接
    if (paper.oa_url && /^https?:\/\//i.test(paper.oa_url)) {
      btnOpenOa.href = paper.oa_url;
      btnOpenOa.style.display = 'flex';
    } else {
      btnOpenOa.style.display = 'none';
    }

    // 启用收藏按钮
    btnCollect.disabled = false;
    btnCollect.onclick = () => addToCollection(paper);

    // 启用 Zotero 同步按钮
    btnZotero.disabled = false;
    btnZotero.onclick = () => syncToZotero(paper);
  }

  /**
   * 添加到收藏
   */
  async function addToCollection(paper) {
    btnCollect.disabled = true;
    btnCollect.querySelector('.btn-text').textContent = '收藏中...';

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'addToCollection',
        paper: paper
      });

      if (response.success) {
        showMessage('已成功收藏到 PaperLens', 'success');
        btnCollect.querySelector('.btn-text').textContent = '已收藏 ✓';

        // 通知当前标签页刷新收藏数据
        try {
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (tab) {
            chrome.tabs.sendMessage(tab.id, { action: 'refreshCollections' });
          }
        } catch { /* 忽略 */ }
      } else {
        showMessage(response.error || '收藏失败', 'error');
        btnCollect.disabled = false;
        btnCollect.querySelector('.btn-text').textContent = '收藏到 PaperLens';
      }
    } catch (error) {
      showMessage('无法连接到 PaperLens', 'error');
      btnCollect.disabled = false;
      btnCollect.querySelector('.btn-text').textContent = '收藏到 PaperLens';
    }
  }

  /**
   * 同步到 Zotero
   */
  async function syncToZotero(paper) {
    btnZotero.disabled = true;
    btnZotero.querySelector('.btn-text').textContent = '同步中...';

    try {
      const response = await chrome.runtime.sendMessage({
        action: 'syncToZotero',
        paper: paper
      });

      if (response.success) {
        showMessage('已成功同步到 Zotero', 'success');
        btnZotero.querySelector('.btn-text').textContent = '已同步 ✓';
      } else {
        showMessage(response.error || '同步失败', 'error');
        btnZotero.disabled = false;
        btnZotero.querySelector('.btn-text').textContent = '同步到 Zotero';
      }
    } catch (error) {
      showMessage('无法连接到 PaperLens', 'error');
      btnZotero.disabled = false;
      btnZotero.querySelector('.btn-text').textContent = '同步到 Zotero';
    }
  }

  /**
   * 显示加载状态
   */
  function showLoading(text) {
    doisSection.style.display = 'none';
    paperSection.style.display = 'none';
    emptyState.style.display = 'none';
    errorState.style.display = 'none';
    message.style.display = 'block';
    message.className = 'message loading';
    message.textContent = text;
  }

  /**
   * 显示消息
   */
  function showMessage(text, type = 'info') {
    message.style.display = 'block';
    message.className = `message ${type}`;
    message.textContent = text;

    // 3秒后自动隐藏
    setTimeout(() => {
      message.style.display = 'none';
    }, 3000);
  }

  /**
   * 显示空状态
   */
  function showEmpty() {
    doisSection.style.display = 'none';
    paperSection.style.display = 'none';
    emptyState.style.display = 'block';
    errorState.style.display = 'none';
    message.style.display = 'none';
  }

  /**
   * 显示错误状态
   */
  function showError(text) {
    doisSection.style.display = 'none';
    paperSection.style.display = 'none';
    emptyState.style.display = 'none';
    errorState.style.display = 'block';
    errorMessage.textContent = text;
    message.style.display = 'none';
  }

  /**
   * HTML 转义
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * HTML 反转义
   */
  function unescapeHtml(text) {
    const div = document.createElement('div');
    div.innerHTML = text;
    return div.textContent;
  }
});
