"""Configuration management for PaperLens"""

import os
import sys
import yaml


def _get_default_data_dir() -> str:
    """默认数据目录：%APPDATA%/PaperLens/（Windows 标准位置）"""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        data_dir = os.path.join(appdata, "PaperLens")
        # 迁移旧目录 LitSearch → PaperLens
        old_dir = os.path.join(appdata, "LitSearch")
        if not os.path.exists(data_dir) and os.path.exists(old_dir):
            try:
                os.rename(old_dir, data_dir)
                print(f"[INFO] Migrated data directory: {old_dir} → {data_dir}")
            except Exception as e:
                print(f"[WARN] Failed to migrate {old_dir}: {e}")
                os.makedirs(data_dir, exist_ok=True)
    else:
        # 非 Windows 或 APPDATA 未设置时回退到 exe 同目录
        if getattr(sys, 'frozen', False):
            data_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
        else:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _get_app_data_dir() -> str:
    """应用数据目录：优先使用用户自定义路径，否则用默认路径"""
    default_dir = _get_default_data_dir()

    # 检查是否有自定义数据目录
    config_path = os.path.join(default_dir, "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            custom_dir = cfg.get("custom_data_dir", "")
            if custom_dir and os.path.isdir(custom_dir):
                return custom_dir
        except Exception:
            pass

    return default_dir


def get_config_path():
    """配置文件路径"""
    return os.path.join(_get_app_data_dir(), "config.yaml")


def load_config():
    """加载配置：优先 data/config.yaml，否则用打包内置默认"""
    user_path = get_config_path()
    if os.path.exists(user_path):
        try:
            with open(user_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ERROR] Failed to load config from {user_path}: {e}")
    # 打包模式：从内置默认加载
    if getattr(sys, 'frozen', False):
        bundled = os.path.join(getattr(sys, '_MEIPASS', ''), "config.yaml")
        if os.path.exists(bundled):
            try:
                with open(bundled, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[ERROR] Failed to load bundled config: {e}")
    return {}


def _sanitize_config_for_save(config):
    """保存前清理配置，防止保存脱敏值"""
    SENSITIVE_KEYS = {"api_key", "apikey", "api_secret", "secret", "password",
                      "access_token", "secret_key", "token", "carsi_password"}

    def _clean_dict(d):
        if not isinstance(d, dict):
            return d
        result = {}
        for k, v in d.items():
            k_lower = k.lower()
            # 检查是否是敏感字段
            is_sensitive = k_lower in SENSITIVE_KEYS or any(
                sub in k_lower for sub in ["api_key", "api_secret", "password", "access_token", "secret_key", "cookie"]
            )
            if is_sensitive and isinstance(v, str) and "****" in v:
                # 跳过脱敏值，不保存到配置文件
                print(f"[WARN] Skipping masked value for '{k}'")
                continue
            elif isinstance(v, dict):
                result[k] = _clean_dict(v)
            elif isinstance(v, list):
                result[k] = [_clean_dict(i) if isinstance(i, dict) else i for i in v]
            else:
                result[k] = v
        return result

    return _clean_dict(config)


def save_config(config):
    path = get_config_path()
    try:
        # 保存前清理脱敏值
        clean_config = _sanitize_config_for_save(config)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(clean_config, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        print(f"[ERROR] Failed to save config to {path}: {e}")
        raise


def _mask_keys(obj):
    """递归隐藏敏感字段"""
    SENSITIVE_EXACT = {"api_key", "apikey", "api_secret", "secret", "password", "access_token", "secret_key", "token"}
    # 包含这些子串的 key 也需要脱敏（覆盖 carsi_password 等变体）
    SENSITIVE_SUBSTR = {"api_key", "api_secret", "password", "access_token", "secret_key", "cookie"}

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            k_lower = k.lower()
            is_sensitive = k_lower in SENSITIVE_EXACT or any(sub in k_lower for sub in SENSITIVE_SUBSTR)
            if is_sensitive:
                if isinstance(v, dict):
                    # 嵌套字典（如 cookies {domain: {name: value}}）递归脱敏叶子节点
                    result[k] = _mask_keys(v)
                elif isinstance(v, str) and len(v) > 4:
                    result[k] = v[:4] + "****" + v[-4:]
                else:
                    result[k] = "****"
            else:
                result[k] = _mask_keys(v)
        return result
    elif isinstance(obj, list):
        return [_mask_keys(i) for i in obj]
    return obj


def _deep_update(base, update):
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
