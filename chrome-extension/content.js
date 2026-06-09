// PaperLens DOI 检测内容脚本
// 在所有网页上运行，检测页面中的 DOI

(function() {
  'use strict';

  // DOI 正则表达式
  const DOI_REGEX = /\b(10\.\d{4,9}\/[-._;()\/:A-Za-z0-9]+)\b/g;

  /**
   * 从 meta 标签检测 DOI
   */
  function getDoiFromMeta() {
    const dois = [];

    // 常见的 DOI meta 标签
    const metaSelectors = [
      'meta[name="citation_doi"]',
      'meta[name="DOI"]',
      'meta[name="dc.identifier"]',
      'meta[property="citation_doi"]',
      'meta[scheme="doi"]'
    ];

    for (const selector of metaSelectors) {
      const meta = document.querySelector(selector);
      if (meta && meta.content) {
        const doi = meta.content.trim();
        if (doi && doi.match(/^10\./)) {
          dois.push(doi);
        }
      }
    }

    return dois;
  }

  /**
   * 从页面内容正则匹配 DOI
   */
  function getDoiFromContent() {
    const dois = new Set();

    // 从 body 文本匹配
    const bodyText = document.body.innerText;
    let match;
    while ((match = DOI_REGEX.exec(bodyText)) !== null) {
      dois.add(match[1]);
    }

    // 从链接匹配
    const links = document.querySelectorAll('a[href*="doi.org"]');
    links.forEach(link => {
      const href = link.href;
      const doiMatch = href.match(/doi\.org\/(10\..+)/);
      if (doiMatch) {
        dois.add(doiMatch[1].replace(/\/$/, ''));
      }
    });

    return Array.from(dois);
  }

  /**
   * 从 URL 检测 DOI（适用于 DOI 链接页面）
   */
  function getDoiFromUrl() {
    const url = window.location.href;
    const doiMatch = url.match(/doi\.org\/(10\..+)/);
    if (doiMatch) {
      return [doiMatch[1].replace(/\/$/, '')];
    }
    return [];
  }

  /**
   * 获取页面上所有 DOI
   */
  function detectDois() {
    const allDois = new Set();

    // 优先级：meta 标签 > URL > 内容匹配
    getDoiFromMeta().forEach(doi => allDois.add(doi));
    getDoiFromUrl().forEach(doi => allDois.add(doi));

    // 如果 meta 标签没有 DOI，再从内容匹配
    if (allDois.size === 0) {
      getDoiFromContent().forEach(doi => allDois.add(doi));
    }

    return Array.from(allDois);
  }

  // 监听来自 popup 的消息
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'detectDois') {
      const dois = detectDois();
      sendResponse({ dois });
    }
    return true;
  });

  // 页面加载完成后通知 background
  const dois = detectDois();
  if (dois.length > 0) {
    chrome.runtime.sendMessage({
      action: 'doisFound',
      count: dois.length
    });
  }
})();
