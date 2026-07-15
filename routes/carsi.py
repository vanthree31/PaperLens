"""CARSI campus access routes"""

import copy
import os
from flask import Blueprint, request, jsonify, current_app
from core.config import load_config, save_config
from access_proxy import CARSIAuth, get_supported_institutions
from search_engine import SearchEngine

carsi_bp = Blueprint('carsi', __name__)


def _state():
    return current_app.config["APP_STATE"]


@carsi_bp.route("/api/carsi/institutions", methods=["GET"])
def carsi_institutions():
    """获取 CARSI 支持的学校列表"""
    try:
        institutions = get_supported_institutions()
        return jsonify({"institutions": institutions})
    except Exception as e:
        print(f"[ERROR] Failed to get institutions: {e}")
        return jsonify({"institutions": [], "error": str(e)})


@carsi_bp.route("/api/carsi/status", methods=["GET"])
def carsi_status():
    """检查 CARSI cookies 是否有效"""
    import requests as req
    cfg = load_config()
    cookies = cfg.get("access_proxy", {}).get("carsi_cookies", {})
    if not cookies:
        return jsonify({"authenticated": False, "error": "no_cookies"})

    # 测试 CNKI cookies 是否有效（CNKI 是最常见的 CARSI 数据源）
    cnki_cookies = cookies.get("fsso.cnki.net", {})
    if cnki_cookies:
        try:
            r = req.get("https://fsso.cnki.net/", cookies=cnki_cookies, timeout=10, allow_redirects=False)
            # 200/302 都算有效，401/403 算过期
            if r.status_code in (200, 302, 303):
                return jsonify({"authenticated": True, "source": "cnki"})
        except Exception:
            pass

    # 测试 Cambridge cookies
    cam_cookies = cookies.get("www.cambridge.org", {})
    if cam_cookies:
        try:
            r = req.get("https://www.cambridge.org/core", cookies=cam_cookies, timeout=10, allow_redirects=False)
            if r.status_code in (200, 302, 303):
                return jsonify({"authenticated": True, "source": "cambridge"})
        except Exception:
            pass

    return jsonify({"authenticated": False, "error": "cookies_expired"})


@carsi_bp.route("/api/carsi/authenticate", methods=["POST"])
def carsi_authenticate():
    """执行 CARSI 认证"""
    state = _state()
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "local_only"}), 403
    data = request.json or {}
    idp_url = data.get("idp_url", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    # 脱敏值回退到存储的真实值
    if not password or "****" in password:
        cfg = load_config()
        password = cfg.get("access_proxy", {}).get("carsi_password", "")
    if not idp_url or not username or not password:
        return jsonify({"error": "missing_credentials"}), 400
    try:
        auth = CARSIAuth()
        # 加载已有 cookies，在 re-auth 时保留之前有效的 SP cookies
        cfg = load_config()
        existing_cookies = cfg.get("access_proxy", {}).get("carsi_cookies", {})
        result = auth.authenticate(idp_url, username, password,
                                   existing_cookies=existing_cookies)
        # 关闭 CARSI 认证过程中创建的 requests.Session
        try:
            if hasattr(auth, 'session'):
                auth.session.close()
        except Exception:
            pass
        # 认证成功后保存 cookies 到配置，供搜索引擎使用
        if result.get("ok") and result.get("cookies"):
            # 准备配置（锁外读取）— cfg 已在上面读取
            # 深度合并 cookies：保留之前有效的 cookies，只覆盖本次成功获取的
            merged_cookies = copy.deepcopy(existing_cookies)
            for domain, domain_cookies in result["cookies"].items():
                if domain in merged_cookies:
                    merged_cookies[domain].update(domain_cookies)
                else:
                    merged_cookies[domain] = dict(domain_cookies)
            cfg.setdefault("access_proxy", {})["carsi_cookies"] = merged_cookies
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
        if result.get("ok"):
            _start_carsi_keepalive()
        return jsonify(result)
    except Exception as e:
        print(f"[ERROR] CARSI auth failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# CARSI cookies 后台保活
_carsi_keepalive_thread = None
_carsi_keepalive_stop = None


def _start_carsi_keepalive():
    """启动 CARSI cookies 保活线程（每 15 分钟心跳一次）"""
    global _carsi_keepalive_thread, _carsi_keepalive_stop
    import threading as _th
    import time as _time
    if _carsi_keepalive_thread and _carsi_keepalive_thread.is_alive():
        return  # 已经运行
    _carsi_keepalive_stop = _th.Event()

    def _run():
        import requests as _req
        while not _carsi_keepalive_stop.wait(900):  # 15 分钟
            try:
                cfg = load_config()
                cookies = cfg.get("access_proxy", {}).get("carsi_cookies", {})
                if not cookies:
                    continue
                # 向每个 SP 域名发送心跳
                for domain, domain_cookies in cookies.items():
                    if not isinstance(domain_cookies, dict):
                        continue
                    try:
                        sess = _req.Session()
                        sess.cookies.update(domain_cookies)
                        r = sess.get(f"https://{domain}/", timeout=10, allow_redirects=False)
                        if r.status_code in (200, 302, 303):
                            # 200=OK, 302/303=重定向（SP 正常），但 302→login 则过期
                            if r.status_code in (302, 303) and "login" in r.headers.get("Location", "").lower():
                                print(f"[CARSI Keepalive] {domain} cookies may have expired (redirect to login)")
                            else:
                                print(f"[CARSI Keepalive] {domain} OK ({r.status_code})")
                        else:
                            print(f"[CARSI Keepalive] {domain} unexpected {r.status_code}")
                    except Exception as e:
                        print(f"[CARSI Keepalive] {domain} error: {e}")
            except Exception as e:
                print(f"[CARSI Keepalive] error: {e}")
    _carsi_keepalive_thread = _th.Thread(target=_run, daemon=True)
    _carsi_keepalive_thread.start()
    print("[CARSI Keepalive] Started")


@carsi_bp.route("/api/carsi/keepalive/start", methods=["POST"])
def start_carsi_keepalive():
    _start_carsi_keepalive()
    return jsonify({"ok": True, "message": "CARSI keepalive started"})


@carsi_bp.route("/api/carsi/keepalive/stop", methods=["POST"])
def stop_carsi_keepalive():
    global _carsi_keepalive_stop
    if _carsi_keepalive_stop:
        _carsi_keepalive_stop.set()
    return jsonify({"ok": True, "message": "CARSI keepalive stopped"})
