"""Zotero integration routes for PaperLens"""

import os
import sys
import json
import re
import requests
from flask import Blueprint, request, jsonify, current_app
from core.config import _mask_keys
from core.utils import _get_user_data_path

zotero_bp = Blueprint('zotero', __name__)


def _state():
    return current_app.config["APP_STATE"]


def load_zotero_config():
    """读取 Zotero 配置（原始值，非脱敏）"""
    state = _state()
    path = _get_user_data_path("zotero_config.json")
    with state.preferences_lock:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {"api_key": "", "user_id": ""}


@zotero_bp.route("/api/zotero/test", methods=["POST"])
def zotero_test():
    """测试 Zotero API 连接"""
    data = request.json or {}
    api_key = data.get("api_key", "").strip()
    user_id = data.get("user_id", "").strip()
    # 如果前端传的是脱敏值或空值，使用后端存储的真实配置
    if not api_key or not user_id or "****" in api_key:
        stored = load_zotero_config()
        api_key = api_key if api_key and "****" not in api_key else stored.get("api_key", "")
        user_id = user_id or stored.get("user_id", "")
    if not api_key or not user_id:
        return jsonify({"error": "missing_zotero_config"}), 400
    if not user_id.isdigit():
        return jsonify({"error": "invalid_user_id"}), 400

    try:
        import requests as req
        headers = {"Zotero-API-Key": api_key}
        r = req.get(f"https://api.zotero.org/users/{user_id}/collections?limit=1",
                   headers=headers, timeout=10)
        if r.status_code == 200:
            return jsonify({"ok": True})
        elif r.status_code == 403:
            return jsonify({"error": "zotero_auth_failed"}), 403
        else:
            return jsonify({"error": "zotero_connection_failed"}), 400
    except Exception as e:
        print(f"[ERROR] Zotero test failed: {e}")
        return jsonify({"error": "zotero_connection_failed"}), 500


@zotero_bp.route("/api/zotero/collections", methods=["POST"])
def zotero_get_collections():
    """获取用户的 Zotero 收藏夹列表"""
    data = request.json or {}
    api_key = data.get("api_key", "").strip()
    user_id = data.get("user_id", "").strip()
    # 脱敏值回退到存储的真实值
    if not api_key or "****" in api_key or not user_id:
        stored = load_zotero_config()
        api_key = api_key if api_key and "****" not in api_key else stored.get("api_key", "")
        user_id = user_id or stored.get("user_id", "")
    if not api_key or not user_id:
        return jsonify({"error": "missing_zotero_config"}), 400
    if not user_id.isdigit():
        return jsonify({"error": "invalid_user_id"}), 400

    try:
        import requests as req
        headers = {"Zotero-API-Key": api_key}
        r = req.get(f"https://api.zotero.org/users/{user_id}/collections?limit=100&sort=title",
                   headers=headers, timeout=15)
        if r.status_code != 200:
            return jsonify({"error": "zotero_fetch_failed"}), 400

        collections = []
        for col in r.json():
            data_col = col.get("data", {})
            collections.append({
                "key": data_col.get("key", ""),
                "name": data_col.get("name", ""),
                "parentCollection": data_col.get("parentCollection", ""),
                "numItems": col.get("meta", {}).get("numItems", 0),
            })

        return jsonify({"collections": collections})
    except Exception as e:
        print(f"[ERROR] Zotero collections fetch failed: {e}")
        return jsonify({"error": "zotero_fetch_failed"}), 500


@zotero_bp.route("/api/zotero/sync", methods=["POST"])
def zotero_sync():
    """将论文同步到 Zotero"""
    data = request.json or {}
    api_key = data.get("api_key", "").strip()
    user_id = data.get("user_id", "").strip()
    collection_key = data.get("collection_key", "").strip()
    papers = data.get("papers", [])

    # 脱敏值回退到存储的真实值
    if not api_key or "****" in api_key or not user_id:
        stored = load_zotero_config()
        api_key = api_key if api_key and "****" not in api_key else stored.get("api_key", "")
        user_id = user_id or stored.get("user_id", "")
    if not api_key or not user_id:
        return jsonify({"error": "missing_zotero_config"}), 400
    if not user_id.isdigit():
        return jsonify({"error": "invalid_user_id"}), 400
    if not papers:
        return jsonify({"error": "no_papers"}), 400

    try:
        import requests as req
        headers = {
            "Zotero-API-Key": api_key,
            "Content-Type": "application/json",
        }

        # 构建 Zotero items
        items = []
        for p in papers[:50]:  # 限制每次最多50篇
            item = {
                "itemType": "journalArticle",
                "title": p.get("title", ""),
                "creators": [
                    {"creatorType": "author", "name": author}
                    for author in p.get("authors", [])[:10]
                ],
                "publicationTitle": p.get("journal", ""),
                "date": str(p.get("year", "")),
                "DOI": p.get("doi", ""),
                "abstractNote": p.get("abstract", ""),
                "volume": p.get("volume", ""),
                "issue": p.get("issue", ""),
                "pages": p.get("pages", ""),
                "ISSN": p.get("issn", ""),
                "tags": [
                    {"tag": kw} for kw in p.get("keywords", [])[:5]
                ],
            }
            if collection_key:
                item["collections"] = [collection_key]
            items.append(item)

        # 批量创建 items
        r = req.post(
            f"https://api.zotero.org/users/{user_id}/items",
            headers=headers,
            json=items,
            timeout=30,
        )

        # Zotero API 返回 200 成功，409 表示部分冲突（重复项）
        if r.status_code in (200, 201, 409):
            result = r.json()
            successful = len(result.get("successful", []))
            failed = len(result.get("failed", []))
            # 409 时 successful 中仍包含已存在的项，算作成功
            return jsonify({
                "ok": True,
                "successful": successful,
                "failed": failed,
                "total": len(items),
            })
        else:
            return jsonify({"error": "zotero_sync_failed"}), 400
    except Exception as e:
        print(f"[ERROR] Zotero sync failed: {e}")
        return jsonify({"error": "zotero_sync_failed"}), 500


@zotero_bp.route("/api/zotero/config", methods=["GET"])
def zotero_get_config():
    """获取 Zotero 配置（脱敏）"""
    return jsonify(_mask_keys(load_zotero_config()))


@zotero_bp.route("/api/zotero/config", methods=["POST"])
def zotero_save_config():
    """保存 Zotero 配置"""
    state = _state()
    data = request.json or {}
    path = _get_user_data_path("zotero_config.json")
    with state.preferences_lock:
        try:
            api_key = data.get("api_key", "")
            user_id = data.get("user_id", "")
            # 脱敏值回退：如果前端传了 ****，从已有配置恢复真实值
            if "****" in api_key:
                existing = load_zotero_config()
                api_key = existing.get("api_key", "")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "api_key": api_key,
                    "user_id": user_id,
                }, f, ensure_ascii=False)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@zotero_bp.route("/api/zotero/auto-fetch", methods=["POST"])
def zotero_auto_fetch():
    """用 Playwright 自动获取 Zotero API Key 和 User ID"""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "local_only"}), 403
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return jsonify({"ok": False, "error": "playwright_not_installed"}), 400

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, channel="chrome")
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.zotero.org/settings/keys", timeout=30000)

            # 等待用户登录（最多 120 秒）
            # 登录后页面会显示 User ID 或 API key 内容
            logged_in = False
            for _ in range(120):
                page.wait_for_timeout(1000)
                url = page.url
                # 检查是否在 keys 页面且已登录
                if "/settings/keys" in url:
                    # 查找 User ID 元素
                    try:
                        # Zotero keys 页面显示 User ID
                        uid_el = page.query_selector("#user-id")
                        if uid_el and uid_el.text_content().strip():
                            logged_in = True
                            break
                    except Exception:
                        pass
                    # 也可能用其他方式显示
                    try:
                        body_text = page.text_content("body") or ""
                        if "Your user ID is" in body_text or "User ID:" in body_text:
                            logged_in = True
                            break
                    except Exception:
                        pass

            if not logged_in:
                browser.close()
                return jsonify({"ok": False, "error": "zotero_login_timeout"})

            # 提取 User ID
            user_id = ""
            try:
                uid_el = page.query_selector("#user-id")
                if uid_el:
                    user_id = uid_el.text_content().strip()
            except Exception:
                pass
            if not user_id:
                try:
                    body_text = page.text_content("body") or ""
                    m = re.search(r'(?:Your user ID is|User ID:)\s*(\d+)', body_text)
                    if m:
                        user_id = m.group(1)
                except Exception:
                    pass

            # 查找已有的 API key（PaperLens 专用）
            api_key = ""
            try:
                # 查找已存在的 PaperLens key
                rows = page.query_selector_all("table tbody tr")
                for row in rows:
                    text = row.text_content() or ""
                    if "PaperLens" in text:
                        # 找到已有的 key，提取值
                        key_el = row.query_selector("code, .key-value, td:nth-child(2)")
                        if key_el:
                            api_key = key_el.text_content().strip()
                            break
            except Exception:
                pass

            # 如果没有已有的 key，创建新的
            if not api_key:
                try:
                    # 点击创建新 key 按钮
                    create_btn = page.query_selector("a[href*='keys/new'], button:has-text('Create'), a:has-text('Create')")
                    if create_btn:
                        create_btn.click()
                        page.wait_for_timeout(2000)

                        # 填写 key 名称
                        name_input = page.query_selector("input[name='name'], #key-name")
                        if name_input:
                            name_input.fill("PaperLens")

                        # 提交
                        submit_btn = page.query_selector("button[type='submit'], input[type='submit']")
                        if submit_btn:
                            submit_btn.click()
                            page.wait_for_timeout(3000)

                        # 提取新创建的 key
                        key_el = page.query_selector("code, .key-value, .alert code")
                        if key_el:
                            api_key = key_el.text_content().strip()
                except Exception:
                    pass

            browser.close()

            if not user_id:
                return jsonify({"ok": False, "error": "zotero_user_id_not_found"})

            return jsonify({
                "ok": True,
                "user_id": user_id,
                "api_key": api_key,
            })
    except Exception as e:
        print(f"[ERROR] Zotero auto-fetch failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@zotero_bp.route("/api/zotero/local-status", methods=["GET"])
def zotero_local_status():
    """检测本地 Zotero 库状态（原生 API > MCP > SQLite）"""
    import os as _os
    try:
        from search_engine import ZoteroNativeClient, ZoteroSQLiteReader, ZoteroMCPClient
        from core.config import load_config
        cfg = load_config()
        stats = {}
        # Tier 1: Zotero 9 原生 API
        try:
            native = ZoteroNativeClient()
            if native.ping():
                tags = native.get_tags()
                stats["available"] = True
                stats["backend"] = "native"
                stats["items"] = -1  # 数量未知但有数据
                stats["tags"] = len(tags)
                return jsonify(stats)
        except Exception:
            pass
        # Tier 2: MCP + SQLite 原有逻辑
        custom_dir = (cfg.get("sources", {}).get("zotero_mcp", {}).get("data_dir") or "").strip()
        profile = ZoteroSQLiteReader.find_profile_dir(custom_dir=custom_dir)
        sqlite = ZoteroSQLiteReader(profile_dir=profile)
        stats = sqlite.stats
        stats["available"] = sqlite.available
        stats["profile_found"] = profile is not None
        if profile:
            stats["profile_path"] = profile
        else:
            stats["diagnosis"] = "zotero_profile_not_found"
            home = _os.path.expanduser("~")
            if sys.platform == "win32":
                appdata = _os.environ.get("APPDATA", home)
                stats["expected_path"] = _os.path.join(appdata, "Zotero", "Zotero", "profiles.ini")
            stats["hint"] = "请确认已安装并至少启动过一次 Zotero"
        mcp_cfg = cfg.get("sources", {}).get("zotero_mcp", {})
        mcp_url = mcp_cfg.get("zotero_mcp_url", "http://127.0.0.1:23120")
        if mcp_url and not mcp_url.startswith("http"):
            mcp_url = f"http://127.0.0.1:{mcp_url}"
        try:
            mcp = ZoteroMCPClient(base_url=mcp_url)
            stats["mcp_available"] = mcp.ping()
        except Exception:
            stats["mcp_available"] = False
        if stats.get("mcp_available"):
            stats["backend"] = "mcp"
        elif sqlite.available:
            stats["backend"] = "sqlite"
        else:
            stats["backend"] = "none"
        return jsonify(stats)
    except Exception as e:
        return jsonify({"available": False, "items": 0, "tags": 0, "error": str(e)})


@zotero_bp.route("/api/zotero/install-mcp", methods=["POST"])
def zotero_install_mcp():
    """一键安装 Zotero MCP 插件（从 GitHub 下载 .xpi 到 Zotero plugins 目录）"""
    try:
        from search_engine import ZoteroSQLiteReader
        from core.config import load_config
        cfg = load_config()
        custom_dir = (cfg.get("sources", {}).get("zotero_mcp", {}).get("data_dir") or "").strip()
        profile = ZoteroSQLiteReader.find_profile_dir(custom_dir=custom_dir)
        if not profile:
            return jsonify({"ok": False, "error": "zotero_profile_not_found",
                           "hint": "未检测到 Zotero 安装，请先安装 Zotero 7"})
        plugins_dir = os.path.join(profile, "plugins")
        os.makedirs(plugins_dir, exist_ok=True)

        # 从 GitHub API 获取最新 release 的 xpi 下载地址
        api_url = "https://api.github.com/repos/cookjohn/zotero-mcp/releases/latest"
        print(f"[Zotero] Fetching latest release info from {api_url}")
        r = requests.get(api_url, timeout=30,
                        headers={"User-Agent": "PaperLens/1.0", "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return jsonify({"ok": False, "error": "github_api_failed",
                           "hint": f"GitHub API 请求失败 (HTTP {r.status_code})"})
        release = r.json()
        xpi_asset = None
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".xpi"):
                xpi_asset = asset
                break
        if not xpi_asset:
            return jsonify({"ok": False, "error": "no_xpi_found",
                           "hint": "在最新 release 中未找到 .xpi 文件"})
        download_url = xpi_asset["browser_download_url"]
        print(f"[Zotero] Downloading MCP plugin from {download_url}")
        r = requests.get(download_url, timeout=60,
                        headers={"User-Agent": "PaperLens/1.0"})
        if r.status_code != 200:
            return jsonify({"ok": False, "error": "download_failed",
                           "hint": f"GitHub 下载失败 (HTTP {r.status_code})，请手动安装"})

        # 保存到 Zotero plugins 目录
        xpi_path = os.path.join(plugins_dir, "zotero-mcp.xpi")
        with open(xpi_path, "wb") as f:
            f.write(r.content)

        # 检查是否已安装成功
        # 删除旧版本（如果有）
        for fname in os.listdir(plugins_dir):
            if fname.startswith("zotero-mcp") and fname != "zotero-mcp.xpi":
                old = os.path.join(plugins_dir, fname)
                if os.path.isfile(old):
                    os.remove(old)
                    print(f"[Zotero] Removed old plugin: {fname}")

        print(f"[Zotero] MCP plugin installed to {xpi_path}")
        return jsonify({
            "ok": True,
            "message": "MCP 插件已安装，请重启 Zotero 后生效",
            "path": xpi_path,
        })
    except Exception as e:
        print(f"[ERROR] Zotero MCP install failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@zotero_bp.route("/api/zotero/fulltext", methods=["POST"])
def zotero_fulltext():
    """从 Zotero 提取论文 PDF 全文（需要 MCP 插件 + PDF attachment）"""
    data = request.json or {}
    doi = (data.get("doi") or "").strip()
    title = (data.get("title") or "").strip()
    if not doi and not title:
        return jsonify({"ok": False, "error": "missing_params"}), 400

    # 先尝试 MCP
    try:
        from search_engine import ZoteroMCPClient
        from core.config import load_config
        cfg = load_config()
        mcp_cfg = cfg.get("sources", {}).get("zotero_mcp", {})
        mcp_url = mcp_cfg.get("zotero_mcp_url", "http://127.0.0.1:23120")
        if mcp_url and not mcp_url.startswith("http"):
            mcp_url = f"http://127.0.0.1:{mcp_url}"
        mcp = ZoteroMCPClient(base_url=mcp_url)
        if mcp.ping():
            # 搜索找到条目
            query = doi or title
            results = mcp.search(query, limit=1)
            if not results:
                return jsonify({"ok": False, "error": "item_not_found"})
            item_key = results[0].get("key", "")
            # 获取内容（PDF + 摘要）
            content = mcp.call_tool("get_content", {
                "itemKey": item_key,
                "include": {"pdf": True, "notes": False, "abstract": True},
            })
            fulltext = content.get("fulltext", "") or ""
            abstract = content.get("abstract", "") or ""
            return jsonify({
                "ok": True,
                "itemKey": item_key,
                "fulltext": fulltext[:100000],  # 截断到 100KB
                "abstract": abstract[:5000],
                "word_count": len(fulltext.split()),
            })
    except Exception as e:
        print(f"[Zotero Fulltext] MCP failed: {e}")

    # SQLite 回退：查找附件路径
    try:
        from search_engine import ZoteroSQLiteReader
        sqlite = ZoteroSQLiteReader()
        if sqlite.available:
            # 搜索条目
            papers = sqlite.search(doi or title, limit=1)
            if papers and papers[0].title:
                cur = sqlite._conn.execute("""
                    SELECT ia.path, ia.itemID FROM itemAttachments ia
                    JOIN items i ON ia.itemID = i.itemID
                    WHERE i.itemID IN (
                        SELECT id.itemID FROM itemData id
                        JOIN itemDataValues idv ON id.valueID = idv.valueID
                        JOIN fields f ON id.fieldID = f.fieldID
                        WHERE (f.fieldName = 'DOI' AND idv.value = ?)
                           OR (f.fieldName = 'title' AND idv.value LIKE ?)
                    ) AND ia.contentType = 'application/pdf'
                    LIMIT 1
                """, (doi, f"%{title}%" if title else ""))
                row = cur.fetchone()
                if row and row["path"]:
                    pdf_path = row["path"]
                    if os.path.isfile(pdf_path):
                        try:
                            import subprocess
                            result = subprocess.run(
                                ["pdftotext", "-layout", pdf_path, "-"],
                                capture_output=True, text=True, timeout=30)
                            if result.returncode == 0 and result.stdout.strip():
                                return jsonify({
                                    "ok": True,
                                    "fulltext": result.stdout[:100000],
                                    "abstract": papers[0].abstract[:5000] if papers else "",
                                    "word_count": len(result.stdout.split()),
                                    "source": "sqlite_pdf",
                                })
                        except Exception:
                            pass
                    return jsonify({
                        "ok": True,
                        "fulltext": "",
                        "abstract": papers[0].abstract[:5000] if papers else "",
                        "hint": f"PDF found at {pdf_path} but pdftotext not available",
                    })
    except Exception as e:
        print(f"[Zotero Fulltext] SQLite failed: {e}")

    return jsonify({"ok": False, "error": "fulltext_not_available",
                   "hint": "需安装 Zotero MCP 插件或 pdftotext 工具"})


@zotero_bp.route("/api/zotero/data-dir", methods=["GET"])
def zotero_get_data_dir():
    """获取用户设置的自定义 Zotero 数据目录"""
    try:
        from core.config import load_config
        cfg = load_config()
        saved = (cfg.get("sources", {}).get("zotero_mcp", {}).get("data_dir") or "").strip()
        return jsonify({"data_dir": saved})
    except Exception:
        return jsonify({"data_dir": ""})


@zotero_bp.route("/api/zotero/data-dir", methods=["POST"])
def zotero_set_data_dir():
    """设置自定义 Zotero 数据目录"""
    data = request.get_json(silent=True) or {}
    data_dir = (data.get("data_dir") or "").strip()
    try:
        from core.config import load_config, _get_config_path
        cfg = load_config()
        if "sources" not in cfg:
            cfg["sources"] = {}
        if "zotero_mcp" not in cfg["sources"]:
            cfg["sources"]["zotero_mcp"] = {}
        cfg["sources"]["zotero_mcp"]["data_dir"] = data_dir
        import yaml
        config_path = _get_config_path()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        # 同步到运行时
        state = current_app.config.get("APP_STATE")
        if state and hasattr(state, 'engine') and state.engine:
            state.engine._zotero_data_dir = data_dir
        return jsonify({"ok": True, "data_dir": data_dir})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@zotero_bp.route("/api/zotero/launch", methods=["POST"])
def zotero_launch():
    """启动 Zotero 桌面应用"""
    import subprocess
    exe_path = None
    if sys.platform == "win32":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Zotero", "zotero.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Zotero", "zotero.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Zotero", "zotero.exe"),
            "D:\\Program Files\\Zotero\\zotero.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                exe_path = c
                break
    elif sys.platform == "darwin":
        if os.path.isdir("/Applications/Zotero.app"):
            exe_path = "/Applications/Zotero.app"
    else:
        import shutil
        exe_path = shutil.which("zotero")
    if not exe_path:
        return jsonify({"ok": False, "error": "zotero_not_found",
                       "hint": "未找到 Zotero 安装路径，请手动启动"})
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", exe_path])
        else:
            subprocess.Popen([exe_path], shell=False)
        return jsonify({"ok": True, "path": exe_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
