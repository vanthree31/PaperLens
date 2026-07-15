"""Wanfang login routes"""

import queue
import threading
from flask import Blueprint, request, jsonify, current_app
from core.config import load_config, save_config
from search_engine import SearchEngine

wanfang_bp = Blueprint('wanfang', __name__)

# Playwright worker thread
_wf_cmd = queue.Queue()
_wf_result = queue.Queue()
_worker_started = False


def _state():
    return current_app.config["APP_STATE"]


def _wf_worker():
    from playwright.sync_api import sync_playwright
    from access_proxy import _setup_playwright_browsers_path
    _setup_playwright_browsers_path()
    pw = None
    browser = None
    while True:
        cmd = _wf_cmd.get()
        try:
            if cmd == "open":
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=False, channel="chrome")
                cfg = load_config()
                verify_ssl = cfg.get("access_proxy", {}).get("verify_ssl", True)
                ctx = browser.new_context(ignore_https_errors=not verify_ssl)
                page = ctx.new_page()
                page.goto("https://www.wanfangdata.com.cn", timeout=30000)
                _wf_result.put({"ok": True})
            elif cmd == "extract":
                if not browser:
                    _wf_result.put({"ok": False, "error": "no_browser"})
                    continue
                cookies = browser.contexts[0].cookies() if browser.contexts else []
                # 按域名分组，保留每个 cookie 的 domain 和 path 信息
                # 格式: {domain: {name: {value: ..., path: ...}}}
                cookies_by_domain = {}
                for c in cookies:
                    domain = c.get('domain', '')
                    if 'wanfangdata' in domain:
                        cookies_by_domain.setdefault(domain, {})[c['name']] = {
                            "value": c['value'],
                            "path": c.get('path', '/')
                        }
                browser.close()
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                pw = None
                browser = None
                if cookies_by_domain:
                    # 扁平字符串用于前端显示和向后兼容
                    flat = "; ".join(
                        f"{n}={info['value']}"
                        for dc in cookies_by_domain.values()
                        for n, info in dc.items()
                    )
                    _wf_result.put({"ok": True, "cookies": cookies_by_domain, "cookie": flat})
                else:
                    _wf_result.put({"ok": False, "error": "wanfang_no_cookie"})
            elif cmd == "stop":
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                break
        except Exception as e:
            # [Fix #9] 异常后重置 worker 状态，避免残留导致后续操作失败
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            browser = None
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass
            pw = None
            _wf_result.put({"ok": False, "error": str(e)})


_worker_lock = threading.Lock()

def _start_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            _worker_started = True
            threading.Thread(target=_wf_worker, daemon=True).start()


@wanfang_bp.route("/api/wanfang/open-browser", methods=["POST"])
def wanfang_open_browser():
    """打开万方浏览器，用户手动登录"""
    _start_worker()
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "local_only"}), 403
    try:
        _wf_cmd.put("open")
        return jsonify(_wf_result.get(timeout=60))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@wanfang_bp.route("/api/wanfang/extract-cookie", methods=["POST"])
def wanfang_extract_cookie():
    """从已打开的万方浏览器提取 Cookie"""
    _start_worker()
    state = _state()
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "local_only"}), 403
    try:
        _wf_cmd.put("extract")
        result = _wf_result.get(timeout=30)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    if result.get("ok") and result.get("cookies"):
        # 保存结构化 cookies（保留域名和路径信息）
        cfg = load_config()
        cfg.setdefault("sources", {}).setdefault("wanfang", {})
        cfg["sources"]["wanfang"]["cookies"] = result["cookies"]
        # 扁平字符串用于前端显示和向后兼容
        cfg["sources"]["wanfang"]["cookie"] = result.get("cookie", "")
        cfg["sources"]["wanfang"]["enabled"] = True
        # 在锁外创建新引擎（避免长时间持有 cache_lock）
        new_engine = SearchEngine(cfg)
        with state.cache_lock:
            save_config(cfg)
            state.config = cfg
            old_engine = state.engine
            state.engine = new_engine
        state._setup_translator_ai()
        # 锁外关闭旧引擎
        if old_engine:
            try:
                old_engine.close()
            except Exception:
                pass
    return jsonify(result)
