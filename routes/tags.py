"""Tags management routes for PaperLens"""

import os
import json
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from core.utils import _get_user_data_path

tags_bp = Blueprint("tags", __name__)

# 预设颜色池（8 色）
TAG_COLORS = [
    "#007AFF",  # Blue
    "#34C759",  # Green
    "#FF9500",  # Orange
    "#FF3B30",  # Red
    "#AF52DE",  # Purple
    "#5856D6",  # Indigo
    "#FF2D55",  # Pink
    "#00C7BE",  # Teal
]


def _state():
    return current_app.config["APP_STATE"]


def _read_tags():
    """读取标签数据"""
    path = _get_user_data_path("tags.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tags", [])
        except Exception:
            return []
    return []


def _write_tags(tags):
    """写入标签数据"""
    path = _get_user_data_path("tags.json")
    data = {"tags": tags, "_schema_version": 1}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_collections():
    """读取收藏数据"""
    path = _get_user_data_path("collections.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"groups": [], "items": []}
    return {"groups": [], "items": []}


def _write_collections(collections):
    """写入收藏数据"""
    path = _get_user_data_path("collections.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(collections, f, ensure_ascii=False, indent=2)


def _count_tag_usage(tag_id):
    """统计标签在收藏中的使用次数"""
    collections = _read_collections()
    count = 0
    for item in collections.get("items", []):
        tags = item.get("tags", [])
        # 支持旧格式（字符串列表）和新格式（ID 列表）
        if tag_id in tags:
            count += 1
    return count


@tags_bp.route("/api/tags", methods=["GET"])
def get_tags():
    """获取所有标签（含使用计数）"""
    state = _state()
    with state.collections_lock:
        tags = _read_tags()
        # 为每个标签附加使用计数
        collections = _read_collections()
        usage_map = {}
        for item in collections.get("items", []):
            for tid in item.get("tags", []):
                usage_map[tid] = usage_map.get(tid, 0) + 1
        for tag in tags:
            tag["count"] = usage_map.get(tag["id"], 0)
        return jsonify({"tags": tags})


@tags_bp.route("/api/tags", methods=["POST"])
def create_tag():
    """创建标签 {name, color}"""
    state = _state()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or TAG_COLORS[0]).strip()

    if not name:
        return jsonify({"error": "missing_name"}), 400
    if len(name) > 50:
        return jsonify({"error": "name_too_long"}), 400
    if not _is_valid_hex_color(color):
        return jsonify({"error": "invalid_color"}), 400

    with state.collections_lock:
        tags = _read_tags()
        # 检查重名
        for t in tags:
            if t["name"].lower() == name.lower():
                return jsonify({"error": "duplicate_name"}), 409

        tag_id = "tag_" + uuid.uuid4().hex[:8]
        tag = {
            "id": tag_id,
            "name": name,
            "color": color,
            "created_at": datetime.now().isoformat(),
        }
        tags.append(tag)
        _write_tags(tags)
        tag["count"] = 0
        return jsonify({"ok": True, "tag": tag})


@tags_bp.route("/api/tags/<tag_id>", methods=["PUT"])
def update_tag(tag_id):
    """更新标签 {name?, color?}"""
    state = _state()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip()

    if not name and not color:
        return jsonify({"error": "no_updatable_fields"}), 400

    with state.collections_lock:
        tags = _read_tags()
        tag = None
        for t in tags:
            if t["id"] == tag_id:
                tag = t
                break
        if not tag:
            return jsonify({"error": "tag_not_found"}), 404

        if name:
            if len(name) > 50:
                return jsonify({"error": "name_too_long"}), 400
            # 检查重名（排除自身）
            for t in tags:
                if t["id"] != tag_id and t["name"].lower() == name.lower():
                    return jsonify({"error": "duplicate_name"}), 409
            tag["name"] = name

        if color and _is_valid_hex_color(color):
            tag["color"] = color

        _write_tags(tags)
        tag["count"] = _count_tag_usage(tag_id)
        return jsonify({"ok": True, "tag": tag})


@tags_bp.route("/api/tags/<tag_id>", methods=["DELETE"])
def delete_tag(tag_id):
    """删除标签（级联清理收藏中的标签引用）"""
    state = _state()
    with state.collections_lock:
        tags = _read_tags()
        original_len = len(tags)
        tags = [t for t in tags if t["id"] != tag_id]
        if len(tags) == original_len:
            return jsonify({"error": "tag_not_found"}), 404

        _write_tags(tags)

        # 级联清理：从所有收藏 item 中移除该 tag_id
        collections = _read_collections()
        changed = False
        for item in collections.get("items", []):
            item_tags = item.get("tags", [])
            if tag_id in item_tags:
                item["tags"] = [t for t in item_tags if t != tag_id]
                changed = True
        if changed:
            _write_collections(collections)

        return jsonify({"ok": True})


def _is_valid_hex_color(c: str) -> bool:
    """验证 hex 颜色格式（支持 #RGB, #RRGGBB, #RRGGBBAA）"""
    import re

    return bool(re.match(r"^#[0-9A-Fa-f]{3,8}$", c))


def _get_mcp_client():
    """获取可用的 Zotero 后端客户端（原生 API > MCP）"""
    try:
        from search_engine import ZoteroNativeClient, ZoteroMCPClient

        # Zotero 9 原生 API 优先
        native = ZoteroNativeClient()
        if native.ping():
            return native
        # MCP 兜底
        from core.config import load_config

        cfg = load_config()
        mcp_cfg = cfg.get("sources", {}).get("zotero_mcp", {})
        mcp_url = mcp_cfg.get("zotero_mcp_url", "http://127.0.0.1:23120")
        if mcp_url and not mcp_url.startswith("http"):
            mcp_url = f"http://127.0.0.1:{mcp_url}"
        c = ZoteroMCPClient(base_url=mcp_url)
        return c if c.ping() else None
    except Exception:
        return None


def _find_zotero_item_key(doi: str, title: str) -> str | None:
    """通过 DOI 或 title 在 Zotero 中查找条目 key"""
    mcp = _get_mcp_client()
    if not mcp:
        return None
    try:
        # 优先 DOI 查找
        if doi:
            results = mcp.search(doi, limit=1)
            if results:
                return results[0].get("key", "")
        # 回退 title 查找
        if title:
            results = mcp.search(title, limit=3)
            for r in results:
                if r.get("title", "").lower().strip() == title.lower().strip():
                    return r.get("key", "")
    except Exception:
        pass
    return None


@tags_bp.route("/api/tags/import-zotero", methods=["POST"])
def import_zotero_tags():
    """从 Zotero 导入所有标签（MCP 优先，SQLite 回退）"""
    imported = []
    try:
        # 优先 MCP
        mcp = _get_mcp_client()
        if mcp:
            # 搜索全部条目收集标签
            all_tags = set()
            offset = 0
            while offset < 500:
                results = mcp.search("", limit=50) if offset == 0 else []
                # MCP search 不支持 offset，改用分页多次搜索
                for item in results:
                    for tag_name in item.get("matchedTags", []):
                        all_tags.add(str(tag_name))
                if len(results) < 50:
                    break
                offset += 50
        else:
            # SQLite 回退
            from search_engine import ZoteroSQLiteReader

            sqlite = ZoteroSQLiteReader()
            if not sqlite.available:
                return jsonify({"ok": False, "error": "zotero_not_found"})
            all_tags = set()
            cur = sqlite._conn.execute("SELECT name FROM tags")
            for row in cur.fetchall():
                all_tags.add(row["name"])

        # 合并到 PaperLens tags.json
        existing_tags = _read_tags()
        existing_names = {t["name"].lower() for t in existing_tags}
        colors = [
            "#007AFF",
            "#34C759",
            "#FF9500",
            "#FF3B30",
            "#AF52DE",
            "#5856D6",
            "#FF2D55",
            "#00C7BE",
            "#8E44AD",
            "#2ECC71",
            "#E74C3C",
            "#3498DB",
            "#F39C12",
            "#1ABC9C",
            "#E91E63",
            "#00BCD4",
        ]
        for tag_name in all_tags:
            if not tag_name or not tag_name.strip():
                continue
            if tag_name.lower() in existing_names:
                continue
            tag_id = "tag_" + uuid.uuid4().hex[:8]
            tag = {
                "id": tag_id,
                "name": tag_name.strip()[:50],
                "color": colors[len(existing_tags) % len(colors)],
                "created_at": datetime.now().isoformat(),
            }
            existing_tags.append(tag)
            existing_names.add(tag_name.lower())
            imported.append(tag)

        if imported:
            _write_tags(existing_tags)
        return jsonify({"ok": True, "imported": len(imported), "tags": imported})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@tags_bp.route("/api/tags/push-to-zotero", methods=["POST"])
def push_tags_to_zotero():
    """将 PaperLens 标签推送到 Zotero 条目"""
    data = request.json or {}
    doi = (data.get("doi") or "").strip()
    title = (data.get("title") or "").strip()
    tag_names = data.get("tags") or []
    if (not doi and not title) or not tag_names:
        return jsonify({"ok": False, "error": "missing_params"}), 400

    item_key = _find_zotero_item_key(doi, title)
    if not item_key:
        return jsonify(
            {
                "ok": False,
                "error": "item_not_in_zotero",
                "hint": "该论文不在 Zotero 库中，请先同步到 Zotero",
            }
        )

    mcp = _get_mcp_client()
    if not mcp:
        return jsonify({"ok": False, "error": "mcp_not_available"})

    try:
        mcp.call_tool(
            "write_tag", {"action": "add", "itemKey": item_key, "tags": tag_names}
        )
        return jsonify({"ok": True, "itemKey": item_key})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@tags_bp.route("/api/tags/colors", methods=["GET"])
def get_colors():
    """获取颜色列表（预设 + 用户自定义）"""
    return jsonify({"colors": TAG_COLORS, "custom_allowed": True})
