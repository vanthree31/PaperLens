// PaperLens 后台服务工作者
// 管理扩展图标状态和通信

// PaperLens 服务器地址
const PAPERLENS_API = 'http://127.0.0.1:51234';

// 监听来自 content script 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'doisFound') {
    // 更新扩展图标 badge（需要检查 sender.tab 是否存在）
    if (!sender.tab) return;
    const tabId = sender.tab.id;
    const count = request.count;

    chrome.action.setBadgeText({
      text: count > 0 ? count.toString() : '',
      tabId: tabId
    });

    chrome.action.setBadgeBackgroundColor({
      color: '#2563eb',
      tabId: tabId
    });
  }

  if (request.action === 'queryPaper') {
    // 查询论文详情
    queryPaper(request.doi)
      .then(paper => sendResponse({ success: true, paper }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true; // 保持消息通道开放
  }

  if (request.action === 'addToCollection') {
    // 添加到收藏
    addToCollection(request.paper)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (request.action === 'syncToZotero') {
    // 同步到 Zotero
    syncToZotero(request.paper)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (request.action === 'checkConnection') {
    // 检查 PaperLens 连接
    checkConnection()
      .then(connected => sendResponse({ connected }))
      .catch(() => sendResponse({ connected: false }));
    return true;
  }
});

/**
 * 查询论文详情
 */
async function queryPaper(doi) {
  const response = await fetch(`${PAPERLENS_API}/api/paper-by-doi`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doi }),
    signal: AbortSignal.timeout(15000)
  });

  if (!response.ok) {
    let errorMsg = '查询失败';
    try {
      const error = await response.json();
      errorMsg = error.error || errorMsg;
    } catch {}
    throw new Error(errorMsg);
  }

  const data = await response.json();
  return data.paper;
}

/**
 * 添加到收藏
 */
async function addToCollection(paper) {
  const response = await fetch(`${PAPERLENS_API}/api/collections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      paper: {
        doi: paper.doi,
        title: paper.title,
        authors: paper.authors,
        journal: paper.journal,
        year: paper.year,
        citation_count: paper.citation_count,
        oa_url: paper.oa_url,
        pmid: paper.pmid,
        abstract: paper.abstract,
        keywords: paper.keywords
      },
      group_id: 'default'
    }),
    signal: AbortSignal.timeout(10000)
  });

  if (!response.ok) {
    let errorMsg = '收藏失败';
    try {
      const error = await response.json();
      errorMsg = error.error || errorMsg;
    } catch {}
    throw new Error(errorMsg);
  }

  return await response.json();
}

/**
 * 检查 PaperLens 连接
 */
async function checkConnection() {
  try {
    const response = await fetch(`${PAPERLENS_API}/api/collections`, {
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * 同步到 Zotero
 */
async function syncToZotero(paper) {
  // 先获取 Zotero 配置
  const configResponse = await fetch(`${PAPERLENS_API}/api/zotero/config`, {
    signal: AbortSignal.timeout(5000)
  });
  if (!configResponse.ok) {
    throw new Error('无法获取 Zotero 配置');
  }
  const config = await configResponse.json();

  if (!config.api_key || !config.user_id) {
    throw new Error('请先在 PaperLens 设置中配置 Zotero API Key 和 User ID');
  }

  // 同步论文到 Zotero
  const response = await fetch(`${PAPERLENS_API}/api/zotero/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: config.api_key,
      user_id: config.user_id,
      collection_key: '',
      papers: [{
        doi: paper.doi,
        title: paper.title,
        authors: paper.authors,
        journal: paper.journal,
        year: paper.year,
        abstract: paper.abstract,
        keywords: paper.keywords
      }]
    }),
    signal: AbortSignal.timeout(30000)
  });

  if (!response.ok) {
    let errorMsg = '同步失败';
    try {
      const error = await response.json();
      errorMsg = error.error || errorMsg;
    } catch {}
    throw new Error(errorMsg);
  }

  return await response.json();
}

// 标签页更新时重新检测 DOI
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // 清除 badge
    chrome.action.setBadgeText({ text: '', tabId });
  }
});
