// ========== 工具函数 ==========
import { API, escapeHtml, debugLog } from './state.js';
import { t, te, teAI, safeSetDisabled, currentLang } from './i18n.js';

// 状态栏
function setStatus(text, statusKey) {
  const el = document.getElementById("statusText");
  el.textContent = text;
  // 始终更新 data-status：无 statusKey 时清除，避免旧错误状态残留
  el.dataset.status = statusKey || "";
}

// Toast 通知（支持多个堆叠）
let _toastTimers = [];
function showToast(msg, duration) {
  const container = document.getElementById("toastContainer");
  if (!container) {
    // 兼容：如果容器不存在，退化为单 toast 行为
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(_toastTimers[0]);
    _toastTimers[0] = setTimeout(() => el.classList.remove("show"), duration || 2500);
    return;
  }
  const toast = document.createElement("div");
  toast.className = "toast show";
  toast.textContent = msg;
  container.appendChild(toast);
  const timer = setTimeout(() => {
    toast.classList.remove("show");
    // 从数组中移除自身 ID
    const idx = _toastTimers.indexOf(timer);
    if (idx > -1) _toastTimers.splice(idx, 1);
    setTimeout(() => toast.remove(), 300);
  }, duration || 2500);
  _toastTimers.push(timer);
}

// 下载文件
function downloadFile(content, filename, mime) {
  const blob = new Blob([content], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// 液态玻璃效果初始化
function initGlassEffect(element) {
  // 清理旧的 RAF 循环和事件监听器
  if (element._glassRAFId) {
    cancelAnimationFrame(element._glassRAFId);
  }
  if (element._glassCleanup) {
    element._glassCleanup();
  }

  let currentX = 0, currentY = 0, targetX = 0, targetY = 0;
  const elasticity = 0.15;
  let rafId = null;

  function updateTransform() {
    currentX += (targetX - currentX) * elasticity;
    currentY += (targetY - currentY) * elasticity;

    const distance = Math.sqrt(currentX * currentX + currentY * currentY);
    const scale = 1 + distance * 0.0003;

    element.style.transform = `translateX(calc(-50% + ${currentX}px)) translateY(${currentY}px) scale(${scale})`;
    rafId = requestAnimationFrame(updateTransform);
    element._glassRAFId = rafId;
  }

  // 鼠标追踪
  const parent = element.closest('.search-section') || document.body;
  const onMouseMove = (e) => {
    const rect = element.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const deltaX = e.clientX - centerX;
    const deltaY = e.clientY - centerY;
    const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

    // 只在一定范围内影响
    if (distance < 300) {
      targetX = deltaX * 0.1;
      targetY = deltaY * 0.1;
    } else {
      targetX = 0;
      targetY = 0;
    }
  };

  const onMouseLeave = () => {
    targetX = 0;
    targetY = 0;
  };

  parent.addEventListener('mousemove', onMouseMove);
  parent.addEventListener('mouseleave', onMouseLeave);
  updateTransform();

  // 保存清理函数
  element._glassCleanup = () => {
    parent.removeEventListener('mousemove', onMouseMove);
    parent.removeEventListener('mouseleave', onMouseLeave);
    if (element._glassRAFId) {
      cancelAnimationFrame(element._glassRAFId);
      element._glassRAFId = null;
    }
  };
}

// AI 文本格式化
function formatAIText(text) {
  if (!text) return "";
  // [Fix] 先替换 Markdown 粗体为占位符，再转义 HTML，最后还原粗体标签
  // 这样粗体内容中的 & < > 不会被错误转义
  const BOLD_S = "\x00BOLD_S\x00";
  const BOLD_E = "\x00BOLD_E\x00";
  let s = text.replace(/\*\*(.+?)\*\*/g, `${BOLD_S}$1${BOLD_E}`);
  // 处理 Ollama 思考模型的 <think> 标签（用特殊样式显示）
  // 支持完整 <think>... 和未闭合的 <think>（流式输出时）
  s = s
    // 先转义思考过程外的 HTML
    .replace(/([\s\S]*?)(<think>[\s\S]*?<\/think>|<think>[\s\S]*$|$)/g, (match, before, think) => {
      let result = before
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
      if (think) {
        // 提取思考内容并用特殊样式包装
        const thinkContent = think.replace(/<\/?think>/g, "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;")
          .replace(/\n\n+/g, '</p><p style="margin:6px 0">')
          .replace(/\n/g, '<br>');
        result += `<div class="ai-think-block"><div class="ai-think-label">💭 ${t("aiThinkProcess")}</div><div class="ai-think-content">${thinkContent}</div></div>`;
      }
      return result;
    });
  // [Fix] 还原粗体占位符为 HTML 标签
  s = s.replace(new RegExp(BOLD_S.replace(/\x00/g, "\\x00"), "g"), "<b>")
       .replace(new RegExp(BOLD_E.replace(/\x00/g, "\\x00"), "g"), "</b>");
  // 换行处理
  s = s
    .replace(/\n\n+/g, '</p><p style="margin:10px 0">')
    .replace(/\n/g, '<br>');
  return '<p style="margin:8px 0">' + s + '</p>';
}

// 更新数据源显示
function updateDataSourceDisplay() {
  const checkboxIds = [];
  const sources = [];
  if (document.getElementById("usePubmed")?.checked) sources.push("PubMed");
  if (document.getElementById("useOpenalex")?.checked) sources.push("OpenAlex");
  if (document.getElementById("useSemanticScholar")?.checked) sources.push("S2");
  if (document.getElementById("useCrossref")?.checked) sources.push("CrossRef");
  if (document.getElementById("useArxiv")?.checked) sources.push("arXiv");
  if (document.getElementById("useSciencedirect")?.checked) sources.push("SD");
  if (document.getElementById("useScopus")?.checked) sources.push("Scopus");
  if (document.getElementById("useJstor")?.checked) sources.push("JSTOR");
  if (document.getElementById("useGoogleScholar")?.checked) sources.push("GS");
  if (document.getElementById("useBingAcademic")?.checked) sources.push("Bing");
  if (document.getElementById("useCNKI")?.checked) sources.push("CNKI");
  if (document.getElementById("useWanfang")?.checked) sources.push(t("wanfang"));
  if (document.getElementById("useVIP")?.checked) sources.push(t("vip"));
  if (document.getElementById("useDblp")?.checked) sources.push("DBLP");
  if (document.getElementById("useBiorxiv")?.checked) sources.push("bioRxiv");
  if (document.getElementById("useAgris")?.checked) sources.push("AGRIS");
  if (document.getElementById("usePubag")?.checked) sources.push("USDA PubAg");
  if (document.getElementById("useAcs")?.checked) sources.push("ACS");
  if (document.getElementById("useOptica")?.checked) sources.push("Optica");
  if (document.getElementById("useIop")?.checked) sources.push("IOP");
  if (document.getElementById("useAip")?.checked) sources.push("AIP");
  if (document.getElementById("useRsc")?.checked) sources.push("RSC");
  if (document.getElementById("useEuropepmc")?.checked) sources.push("Europe PMC");
  if (document.getElementById("useSpringer")?.checked) sources.push("Springer");
  if (document.getElementById("useWiley")?.checked) sources.push("Wiley");
  if (document.getElementById("useIeee")?.checked) sources.push("IEEE");
  if (document.getElementById("useMuse")?.checked) sources.push("MUSE");
  if (document.getElementById("useCore")?.checked) sources.push("CORE");
  if (document.getElementById("useLens")?.checked) sources.push("Lens");
  if (document.getElementById("useLensPatents")?.checked) sources.push(t("patents"));
  if (document.getElementById("useZenodo")?.checked) sources.push("Zenodo");
  if (document.getElementById("useDatacite")?.checked) sources.push("DataCite");
  if (document.getElementById("useJstage")?.checked) sources.push("J-STAGE");
  if (document.getElementById("useCochrane")?.checked) sources.push("Cochrane");
  if (document.getElementById("useZoteroMcp")?.checked) sources.push("Zotero Local");
  if (document.getElementById("useFrontiers")?.checked) sources.push("Frontiers");
  if (document.getElementById("useAcm")?.checked) sources.push("ACM");
  if (document.getElementById("useOup")?.checked) sources.push("Oxford Academic");
  if (document.getElementById("useCup")?.checked) sources.push("Cambridge Core");
  if (document.getElementById("useSage")?.checked) sources.push("SAGE");
  if (document.getElementById("useTaylor_francis")?.checked) sources.push("Taylor & Francis");
  if (document.getElementById("useEbsco")?.checked) sources.push("EBSCO");
  if (document.getElementById("useWos")?.checked) sources.push("WoS");
  if (document.getElementById("useProquest")?.checked) sources.push("ProQuest");
  const dataSourceLabel = t("dataSourceLabel");
  // 更新源计数芯片
  const chip = document.getElementById("sourceCountChip");
  if (chip) {
    chip.style.display = sources.length > 0 ? "" : "none";
    chip.textContent = `${sources.length} 源`;
    chip.title = `${dataSourceLabel}: ${sources.join(", ")}`;
  }
  // [Fix] 数据源变更时保存偏好设置
  if (typeof window.savePreferences === 'function') window.savePreferences();
}

// 导出到 window 供其他模块使用
window.showToast = showToast;
window.setStatus = setStatus;
window.downloadFile = downloadFile;
window.initGlassEffect = initGlassEffect;
window.formatAIText = formatAIText;
window.updateDataSourceDisplay = updateDataSourceDisplay;

export {
  setStatus,
  showToast,
  downloadFile,
  initGlassEffect,
  formatAIText,
  updateDataSourceDisplay,
};