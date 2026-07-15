// ========== Zotero 同步 ==========
import { API, escapeHtml } from './state.js';
import { t, te, teAI, safeSetDisabled } from './i18n.js';

let zoteroConfig = { api_key: "", user_id: "" };
let zoteroCollections = [];
let _zoteroSyncPapers = [];

async function loadZoteroConfig(retryCount = 0) {
  try {
    const r = await fetch(`${API}/api/zotero/config`);
    if (r.ok) {
      zoteroConfig = await r.json();
      const keyEl = document.getElementById("cfgZoteroKey");
      const userIdEl = document.getElementById("cfgZoteroUserId");
      if (keyEl) keyEl.value = zoteroConfig.api_key || "";
      if (userIdEl) userIdEl.value = zoteroConfig.user_id || "";
      return true;
    }
  } catch (e) {
    if (retryCount < 1) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      return loadZoteroConfig(retryCount + 1);
    }
  }
  return false;
}

async function testZoteroConnection() {
  const keyEl = document.getElementById("cfgZoteroKey");
  const userIdEl = document.getElementById("cfgZoteroUserId");
  const statusEl = document.getElementById("zoteroStatus");
  if (!keyEl || !userIdEl || !statusEl) return;
  const api_key = keyEl.value.trim();
  const user_id = userIdEl.value.trim();
  if (!api_key || !user_id) {
    statusEl.innerHTML = `<span style="color:var(--danger)">${t("configureZoteroFirst")}</span>`;
    return;
  }
  statusEl.innerHTML = `<div class="spinner" style="width:16px;height:16px"></div> ${t("testingConnection")}`;
  try {
    const r = await fetch(`${API}/api/zotero/test`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ api_key, user_id }),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      statusEl.innerHTML = `<span style="color:var(--success)">✓ ${t("connectionSuccess")}</span>`;
    } else {
      statusEl.innerHTML = `<span style="color:var(--danger)">✗ ${te(data.error) || t("connectionFailed")}</span>`;
    }
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--danger)">✗ ${t("networkError")}</span>`;
  }
}

async function autoFetchZotero() {
  const statusEl = document.getElementById("zoteroStatus");
  const btn = document.getElementById("autoFetchZoteroBtn");
  if (!statusEl) return;
  statusEl.innerHTML = `<div class="spinner" style="width:16px;height:16px"></div> ${t("openingBrowser")}`;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`${API}/api/zotero/auto-fetch`, { method: "POST" });
    const data = await r.json();
    if (r.ok && data.ok) {
      document.getElementById("cfgZoteroKey").value = data.api_key || "";
      document.getElementById("cfgZoteroUserId").value = data.user_id || "";
      statusEl.innerHTML = `<span style="color:var(--success)">${t("fetchedUserId")} ${data.user_id}</span>`;
      await fetch(`${API}/api/zotero/config`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ api_key: data.api_key, user_id: data.user_id }),
      });
      zoteroConfig = { api_key: data.api_key, user_id: data.user_id };
    } else {
      statusEl.innerHTML = `<span style="color:var(--danger)">✗ ${te(data.error) || t("fetchFailed")}</span>`;
    }
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--danger)">✗ ${t("networkError")}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveZoteroConfig() {
  const statusEl = document.getElementById("zoteroStatus");
  const api_key = document.getElementById("cfgZoteroKey").value.trim();
  const user_id = document.getElementById("cfgZoteroUserId").value.trim();
  if (!api_key || !user_id) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">${t("configureZoteroFirst")}</span>`;
    return;
  }
  // 脱敏值可安全发送，后端会从已有配置恢复真实值（检测 **** 后回退到 load_zotero_config）
  // 不跳过脱敏值，否则后端收不到 api_key 字段会误存空字符串
  try {
    const r = await fetch(`${API}/api/zotero/config`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ api_key, user_id }),
    });
    if (r.ok) {
      zoteroConfig = { api_key, user_id };
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--success)">${t("savedSuccess")}</span>`;
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">${t("saveFailed")}</span>`;
    }
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">✗ ${t("networkError")}</span>`;
  }
}

async function syncToZotero() {
  if (!zoteroConfig.api_key || !zoteroConfig.user_id) {
    window.showToast(t("configureZoteroFirst"));
    window.toggleSettings();
    return;
  }
  const selectedPapers = [];
  window.PaperLens.checkedSet.forEach(idx => {
    if (window.PaperLens.allPapers[idx]) selectedPapers.push(window.PaperLens.allPapers[idx]);
  });
  if (selectedPapers.length === 0) {
    window.showToast(t("pleaseSelectPapers"));
    return;
  }
  window.showToast(t("loadingZoteroCollections"));
  try {
    const r = await fetch(`${API}/api/zotero/collections`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(zoteroConfig),
    });
    const data = await r.json();
    if (!r.ok) {
      window.showToast(t("zoteroFetchFailed"));
      return;
    }
    zoteroCollections = data.collections || [];
    showZoteroSyncDialog(selectedPapers);
  } catch (e) {
    window.showToast(t("zoteroFetchFailed"));
  }
}

function showZoteroSyncDialog(papers) {
  _zoteroSyncPapers = papers;
  const modal = document.createElement("div");
  modal.className = "modal-overlay show";
  modal.id = "zoteroModal";
  modal.innerHTML = `
    <div class="modal" style="width:450px">
      <h3>📤 ${t("syncToZotero")}</h3>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">
        ${t("syncToZoteroHint").replace("{count}", papers.length)}
      </p>
      <div class="form-group">
        <label>${t("zoteroCollection")}</label>
        <select id="zoteroCollectionSelect" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:4px">
          <option value="">${t("zoteroDefaultLibrary")}</option>
          ${zoteroCollections.map(c => `<option value="${escapeHtml(c.key)}">${escapeHtml(c.name)} (${c.numItems})</option>`).join("")}
        </select>
      </div>
      <div class="modal-btns">
        <button class="btn btn-outline" onclick="closeZoteroModal()">${t("cancel")}</button>
        <button class="btn btn-primary" onclick="doZoteroSync()">${t("sync")}</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

function closeZoteroModal() {
  const modal = document.getElementById("zoteroModal");
  if (modal) modal.remove();
}

async function doZoteroSync() {
  const collectionSelect = document.getElementById("zoteroCollectionSelect");
  const collection_key = collectionSelect ? collectionSelect.value : "";
  const papers = _zoteroSyncPapers;
  closeZoteroModal();
  window.showToast(t("syncingToZotero"));
  try {
    const r = await fetch(`${API}/api/zotero/sync`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        ...zoteroConfig,
        collection_key,
        papers,
      }),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      window.showToast(`${t("zoteroSyncSuccess")} ${data.successful}/${data.total}`);
    } else {
      window.showToast(t("zoteroSyncFailed"));
    }
  } catch (e) {
    window.showToast(t("zoteroSyncFailed"));
  }
}

// ========== Zotero 数据目录管理 ==========
async function loadZoteroDataDir() {
  try {
    const r = await fetch(`${API}/api/zotero/data-dir`);
    if (r.ok) {
      const data = await r.json();
      const el = document.getElementById("cfgZoteroDataDir");
      if (el && data.data_dir) el.value = data.data_dir;
    }
  } catch (e) { /* ignore */ }
}

async function chooseZoteroDataDir() {
  try {
    const r = await fetch(`${API}/api/choose-folder`, { method: "POST" });
    if (!r.ok) { window.showToast("打开文件夹对话框失败"); return; }
    const data = await r.json();
    if (!data.path) return;
    const el = document.getElementById("cfgZoteroDataDir");
    if (el) el.value = data.path;
    // 保存到后端
    const sr = await fetch(`${API}/api/zotero/data-dir`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data_dir: data.path }),
    });
    if (sr.ok) {
      window.showToast("✓ Zotero 数据目录已更新，刷新状态中...");
      if (typeof testZoteroMcp === "function") setTimeout(testZoteroMcp, 500);
    } else {
      window.showToast("保存失败，请重试");
    }
  } catch (e) {
    window.showToast("操作失败: " + e.message);
  }
}

// 导出到 window
window.loadZoteroConfig = loadZoteroConfig;
window.testZoteroConnection = testZoteroConnection;
window.autoFetchZotero = autoFetchZotero;
window.saveZoteroConfig = saveZoteroConfig;
window.syncToZotero = syncToZotero;
window.showZoteroSyncDialog = showZoteroSyncDialog;
window.closeZoteroModal = closeZoteroModal;
window.doZoteroSync = doZoteroSync;
window.loadZoteroDataDir = loadZoteroDataDir;
window.chooseZoteroDataDir = chooseZoteroDataDir;

export { loadZoteroConfig, testZoteroConnection, autoFetchZotero, saveZoteroConfig, syncToZotero, loadZoteroDataDir, chooseZoteroDataDir };