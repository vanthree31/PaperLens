"""System and configuration routes for PaperLens"""

import os
import sys
from flask import Blueprint, request, jsonify, current_app
from core.config import (
    _get_app_data_dir,
    _get_default_data_dir,
    load_config,
    save_config,
    _mask_keys,
    _deep_update,
)

system_bp = Blueprint("system", __name__)


def _state():
    return current_app.config["APP_STATE"]


def _is_masked(value):
    """检查值是否是脱敏值"""
    return isinstance(value, str) and "****" in value


def _restore_masked_config(update_data, current_config):
    """递归处理配置，将脱敏值替换为当前配置中的真实值"""
    if not isinstance(update_data, dict):
        return update_data
    result = {}
    for k, v in update_data.items():
        if isinstance(v, dict):
            # 递归处理嵌套 dict，无论 current_config 中是否存在该 key
            sub_cfg = current_config.get(k) if isinstance(current_config, dict) else {}
            result[k] = _restore_masked_config(
                v, sub_cfg if isinstance(sub_cfg, dict) else {}
            )
        elif _is_masked(v):
            # 脱敏值：从当前配置中恢复真实值
            if k in current_config:
                cur_val = current_config[k]
                if _is_masked(cur_val):
                    # 当前配置也是脱敏值（配置文件已损坏），跳过以防止覆盖
                    print(
                        f"[WARN] Skipping masked value for '{k}' (current config also masked)"
                    )
                    continue
                result[k] = cur_val
                print(f"[INFO] Restored masked value for '{k}'")
            else:
                print(f"[WARN] Skipping masked value for '{k}' (no existing value)")
                continue
        else:
            result[k] = v
    return result


@system_bp.route("/api/log", methods=["POST"])
def frontend_log():
    """前端日志回传到后端控制台"""
    data = request.json or {}
    msg = data.get("msg", "")
    print(f"[FRONTEND] {msg}")
    return jsonify({"ok": True})


@system_bp.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(_mask_keys(load_config()))


@system_bp.route("/api/config", methods=["POST"])
def update_config():
    state = _state()
    data = request.json or {}
    try:
        cfg = load_config()
        # 将脱敏值替换为当前配置中的真实值，防止丢失
        safe_data = _restore_masked_config(data, cfg)
        _deep_update(cfg, safe_data)
        save_config(cfg)
        # 使用 AppState 替代 nonlocal 模式
        state.replace_instances(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] Config update failed: {e}")
        return jsonify({"error": "config_save_failed"}), 500


@system_bp.route("/api/provider-config", methods=["GET"])
def get_provider_config():
    """获取指定提供商的历史配置（脱敏）"""
    section = request.args.get("section", "").lower()
    provider = request.args.get("provider", "")
    if not section or not provider:
        return jsonify({"config": None})
    cfg = load_config()
    key = f"{section}_{provider}"
    return jsonify({"config": _mask_keys(cfg.get("ai_providers", {}).get(key, None))})


@system_bp.route("/api/provider-config", methods=["POST"])
def save_provider_config():
    """保存指定提供商的配置"""
    data = request.json or {}
    section = data.get("section", "").lower()
    provider = data.get("provider", "")
    provider_cfg = data.get("config", {})
    if not section or not provider:
        return jsonify({"error": "missing_params"}), 400
    try:
        cfg = load_config()
        if "ai_providers" not in cfg:
            cfg["ai_providers"] = {}
        key = f"{section}_{provider}"
        if key not in cfg["ai_providers"]:
            cfg["ai_providers"][key] = {}
        # 将脱敏值替换为当前配置中的真实值，防止丢失
        safe_provider_cfg = _restore_masked_config(
            provider_cfg, cfg["ai_providers"][key]
        )
        cfg["ai_providers"][key].update(safe_provider_cfg)
        save_config(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@system_bp.route("/api/data-dir", methods=["GET"])
def get_data_dir():
    return jsonify({"path": _get_app_data_dir(), "default": _get_default_data_dir()})


@system_bp.route("/api/set-data-dir", methods=["POST"])
def set_data_dir():
    """设置自定义数据目录"""
    data = request.json or {}
    new_path = data.get("path", "").strip()
    if not new_path:
        return jsonify({"error": "no_path"}), 400

    # 验证路径
    real_path = os.path.realpath(new_path)
    if not os.path.isdir(real_path):
        try:
            os.makedirs(real_path, exist_ok=True)
        except Exception as e:
            return jsonify({"error": "create_dir_failed", "detail": str(e)}), 400

    # 保存到配置
    cfg = load_config()
    cfg["custom_data_dir"] = real_path
    save_config(cfg)

    return jsonify({"ok": True, "path": real_path})


@system_bp.route("/api/open-data-dir", methods=["POST"])
def open_data_dir():
    data_dir = _get_app_data_dir()
    try:
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        os.startfile(data_dir)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] Failed to open data dir: {e}")
        return jsonify({"error": "open_dir_failed"}), 500


@system_bp.route("/api/open-export-dir", methods=["POST"])
def open_export_dir():
    """打开导出文件夹"""
    data = request.json or {}
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"error": "no_path"}), 400
    try:
        # 路径安全验证：只允许打开导出路径或其子目录
        export_dir = load_config().get("export_path", "")
        real_path = os.path.realpath(path)
        if export_dir:
            real_export = os.path.realpath(export_dir)
            if not (
                real_path.startswith(real_export + os.sep) or real_path == real_export
            ):
                return jsonify({"error": "invalid_path"}), 400
        else:
            # 未配置导出路径时，只允许打开应用数据目录下的路径
            app_data = os.path.realpath(_get_app_data_dir())
            if not real_path.startswith(app_data):
                return jsonify({"error": "invalid_path"}), 400
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        os.startfile(path)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[ERROR] Failed to open export dir: {e}")
        return jsonify({"error": "open_dir_failed"}), 500


@system_bp.route("/api/choose-folder", methods=["POST"])
def choose_folder():
    """打开系统原生文件夹选择对话框"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(parent=root, title="选择导出文件夹")
        root.destroy()
        if folder:
            return jsonify({"path": folder})
        return jsonify({"path": ""})
    except Exception as e:
        print(f"[ERROR] Folder dialog failed: {e}")
        return jsonify({"error": "dialog_failed"}), 500


@system_bp.route("/api/playwright/status", methods=["GET"])
def playwright_status():
    """检查 Playwright 是否已安装（通过 Python import 检测）"""
    # 1. 检测 playwright Python 包是否可 import
    try:
        import playwright as pw_pkg

        # Playwright 版本存在 _repo_version 中，不在 __version__
        try:
            from playwright._repo_version import version as pw_version
        except ImportError:
            pw_version = getattr(pw_pkg, "__version__", "")
    except ImportError:
        return jsonify({"installed": False, "browser_ready": False, "version": ""})

    # 2. 检测 chromium 浏览器是否已安装（验证可执行文件存在，不只看目录）
    browser_ready = False
    try:
        from access_proxy import _find_chromium_executable

        if sys.platform == "win32":
            cache_base = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "ms-playwright"
            )
        elif sys.platform == "darwin":
            cache_base = os.path.expanduser("~/Library/Caches/ms-playwright")
        else:
            cache_base = os.path.expanduser("~/.cache/ms-playwright")
        browser_ready = _find_chromium_executable(cache_base) is not None
    except Exception:
        browser_ready = False

    return jsonify(
        {"installed": True, "browser_ready": browser_ready, "version": pw_version}
    )


@system_bp.route("/api/playwright/install", methods=["POST"])
def playwright_install():
    """安装 Playwright 浏览器（仅允许本地请求）"""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "local_only"}), 403
    import subprocess

    output = []
    try:
        # Step 1: pip install playwright
        output.append("[1/3] 安装 playwright Python 包...")
        r1 = subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r1.returncode != 0:
            return jsonify(
                {"ok": False, "error": r1.stderr or r1.stdout, "output": output}
            ), 500
        output.append("  ✓ playwright 包已安装")
        # Step 2: playwright install chromium
        output.append("[2/3] 下载 Chromium 浏览器 (~150MB)...")
        r2 = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        output.append(r2.stdout[-200:] if r2.stdout else "")
        if r2.returncode != 0:
            return jsonify(
                {
                    "ok": False,
                    "error": r2.stderr or "chromium install failed",
                    "output": output,
                }
            ), 500
        output.append("  ✓ Chromium 已下载")
        # Step 3: 验证安装
        output.append("[3/3] 验证安装...")
        if sys.platform == "win32":
            cache = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        else:
            cache = os.path.expanduser("~/.cache/ms-playwright")
        from access_proxy import _find_chromium_executable

        exe = _find_chromium_executable(cache)
        if not exe:
            output.append(f"  ⚠ 缓存目录未找到 chromium 可执行文件: {cache}")
            output.append("  尝试安装系统依赖...")
            r3 = subprocess.run(
                [sys.executable, "-m", "playwright", "install-deps", "chromium"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output.append(r3.stdout[-200:] if r3.stdout else "")
        exe2 = _find_chromium_executable(cache)
        if exe2:
            output.append(f"  ✓ 浏览器就绪: {exe2}")
            # 快速冒烟测试
            try:
                from playwright.sync_api import sync_playwright

                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=True)
                browser.close()
                pw.stop()
                output.append("  ✓ 冒烟测试通过")
            except Exception as e:
                output.append(f"  ⚠ 冒烟测试失败: {e}")
        return jsonify({"ok": True, "output": output, "browser_path": exe2 or ""})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "output": output}), 500
