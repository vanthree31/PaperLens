// PaperLens 后台服务工作者
// 管理扩展图标状态和通信

// PaperLens 服务器地址
const PAPERLENS_API = 'http://127.0.0.1:51234';

// 监听来自 content script 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'doisFound') {
    // 更新扩展图标 badge
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
    body: JSON.stringify({ doi })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || '查询失败');
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
        abstract: paper.abstract
      },
      group_id: 'default'
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || '收藏失败');
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

// 标签页更新时重新检测 DOI
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // 清除 badge
    chrome.action.setBadgeText({ text: '', tabId });
  }
});
