"""Cache management for PaperLens"""

import os
import json
from core.utils import _get_user_data_path


def _load_ai_analysis_cache() -> dict:
    """从磁盘加载收藏夹论文的 AI 分析缓存"""
    path = _get_user_data_path("ai_analysis_cache.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_ai_analysis_cache(cache: dict):
    """保存 AI 分析缓存到磁盘"""
    path = _get_user_data_path("ai_analysis_cache.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save AI analysis cache: {e}")


def _is_paper_in_collections(doi: str, collections_lock) -> bool:
    """检查论文是否在收藏夹中"""
    if not doi:
        return False
    path = _get_user_data_path("collections.json")
    if not os.path.exists(path):
        return False
    try:
        with collections_lock:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
        doi_lower = doi.lower()
        for item in collections.get("items", []):
            if item.get("doi", "").lower() == doi_lower:
                return True
    except Exception:
        pass
    return False
