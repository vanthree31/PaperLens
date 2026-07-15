"""Collections management routes for PaperLens"""

import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from core.utils import _get_user_data_path

collections_bp = Blueprint('collections', __name__)


def _state():
    return current_app.config["APP_STATE"]


@collections_bp.route("/api/collections", methods=["GET"])
def get_collections():
    """获取所有收藏，支持 tag_id 查询参数过滤"""
    state = _state()
    tag_id = request.args.get("tag_id", "").strip()
    path = _get_user_data_path("collections.json")
    with state.collections_lock:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if tag_id:
                    data["items"] = [
                        item for item in data.get("items", [])
                        if tag_id in item.get("tags", [])
                    ]
                return jsonify(data)
            except Exception as e:
                print(f"[WARN] Failed to read collections.json: {e}")
                # [Fix #25] 返回错误信息通知前端文件损坏
                return jsonify({
                    "groups": [{"id": "default", "name": "默认收藏夹"}],
                    "items": [],
                    "error": "corrupted",
                    "message": str(e),
                })
    return jsonify({"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []})


@collections_bp.route("/api/collections", methods=["POST"])
def add_collection():
    """添加收藏（支持无 DOI 论文，使用 title 作为备选标识）"""
    state = _state()
    data = request.json or {}
    paper = data.get("paper")
    group_id = data.get("group_id", "default")
    if not paper:
        return jsonify({"error": "missing_paper_info"}), 400
    if not paper.get("doi") and not paper.get("title"):
        return jsonify({"error": "missing_paper_info"}), 400

    path = _get_user_data_path("collections.json")
    with state.collections_lock:
        collections = {"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    collections = json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to read collections.json for add: {e}")
                return jsonify({"error": "collection_read_failed"}), 500

        # 验证 group_id 是否存在，不存在则回退为 'default'
        group_ids = [g.get("id") for g in collections.get("groups", [])]
        if group_id and group_id not in group_ids:
            group_id = "default"

        # 检查是否已收藏（支持 DOI 或 title 去重）
        doi = (paper.get("doi") or "").lower()
        title = paper.get("title") or ""
        group_id_lower = group_id.lower()  # [Fix #16] 统一小写比较
        for item in collections.get("items", []):
            if (item.get("group_id") or "default").lower() != group_id_lower:
                continue
            # DOI 匹配（有 DOI 时优先用 DOI）
            if doi and item.get("doi", "").lower() == doi:
                return jsonify({"ok": True, "message": "已收藏"})
            # 无 DOI 时用 title 匹配
            if not doi and title and item.get("title") == title:
                return jsonify({"ok": True, "message": "已收藏"})

        collections.setdefault("items", []).append({
            "doi": paper.get("doi", ""),
            "title": paper.get("title", ""),
            "authors": paper.get("authors", []),
            "journal": paper.get("journal", ""),
            "year": paper.get("year", 0),
            "citation_count": paper.get("citation_count", 0),
            "oa_url": paper.get("oa_url", ""),
            "pmid": paper.get("pmid", ""),
            "abstract": paper.get("abstract", ""),
            "keywords": paper.get("keywords", []),
            "source": paper.get("source", ""),
            "volume": paper.get("volume", ""),
            "issue": paper.get("issue", ""),
            "pages": paper.get("pages", ""),
            "issn": paper.get("issn", ""),
            # Phase 5a: 学术元数据
            "orcid": paper.get("orcid", ""),
            "article_type": paper.get("article_type", ""),
            "conference": paper.get("conference", ""),
            "funding": paper.get("funding", []),
            "sources": paper.get("sources", []),
            # Phase 5a: 阅读管理
            "reading_status": paper.get("reading_status", "unread"),
            "tags": paper.get("tags", []),
            "notes": paper.get("notes", ""),
            "group_id": group_id,
            "added_at": datetime.now().isoformat(),
        })

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@collections_bp.route("/api/collections", methods=["DELETE"])
def remove_collection():
    """删除收藏"""
    state = _state()
    data = request.json or {}
    doi = (data.get("doi") or "").lower()
    title = data.get("title") or ""
    group_id = data.get("group_id", "default")
    if not doi and not title:
        return jsonify({"error": "no_identifier"}), 400

    path = _get_user_data_path("collections.json")
    if not os.path.exists(path):
        return jsonify({"ok": True})

    with state.collections_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
            collections["items"] = [
                item for item in collections.get("items", [])
                if not (
                    ((doi and item.get("doi", "").lower() == doi) or
                     (not doi and title and item.get("title") == title))
                    and (item.get("group_id") or "default").lower() == group_id.lower()  # [Fix #16]
                )
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


# Phase 5a: PATCH /api/collections/item — 更新收藏 item 字段
@collections_bp.route("/api/collections/item", methods=["PATCH"])
def update_collection_item():
    """更新收藏 item 的字段（reading_status/tags/notes）"""
    state = _state()
    data = request.json or {}
    doi = (data.get("doi") or "").lower()
    title = data.get("title") or ""
    group_id = data.get("group_id", "default")
    if not doi and not title:
        return jsonify({"error": "no_identifier"}), 400

    # 允许更新的字段及类型校验
    updatable_fields = {
        "reading_status": str,
        "tags": list,
        "notes": str,
    }
    updates = {}
    for field, ftype in updatable_fields.items():
        if field in data:
            val = data[field]
            if isinstance(val, ftype):
                # reading_status 枚举校验
                if field == "reading_status" and val not in ("", "unread", "reading", "read"):
                    return jsonify({"error": "invalid_status"}), 400
                updates[field] = val

    if not updates:
        return jsonify({"error": "no_updatable_fields"}), 400

    path = _get_user_data_path("collections.json")
    if not os.path.exists(path):
        return jsonify({"error": "not_found"}), 404

    with state.collections_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
            found = False
            for item in collections.get("items", []):
                item_doi = (item.get("doi") or "").lower()
                item_group = (item.get("group_id") or "default").lower()
                item_title = item.get("title") or ""
                match = False
                if doi and item_doi == doi and item_group == group_id.lower():
                    match = True
                elif not doi and title and item_title == title and item_group == group_id.lower():
                    match = True
                if match:
                    for field, val in updates.items():
                        item[field] = val
                    found = True
                    break

            if not found:
                return jsonify({"error": "item_not_found"}), 404

            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True, "updated": updates})
        except Exception as e:
            print(f"[ERROR] Failed to update collection item: {e}")
            return jsonify({"error": "operation_failed"}), 500


@collections_bp.route("/api/collections/groups", methods=["POST"])
def save_collection_groups():
    """保存收藏夹分组"""
    state = _state()
    data = request.json or {}
    groups = data.get("groups", [])
    path = _get_user_data_path("collections.json")
    with state.collections_lock:
        collections = {"groups": [{"id": "default", "name": "默认收藏夹"}], "items": []}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    collections = json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to read collections.json for group save: {e}")
                return jsonify({"error": "collection_read_failed"}), 500
        collections["groups"] = groups
        if not any(g.get("id") == "default" for g in collections["groups"]):
            collections["groups"].insert(0, {"id": "default", "name": "默认收藏夹"})
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@collections_bp.route("/api/collections/groups", methods=["DELETE"])
def delete_collection_group():
    """删除收藏夹及其所有收藏"""
    state = _state()
    data = request.json or {}
    group_id = data.get("group_id", "")
    if not group_id or group_id == "default":
        return jsonify({"error": "cannot_delete_default"}), 400

    path = _get_user_data_path("collections.json")
    if not os.path.exists(path):
        return jsonify({"ok": True})

    with state.collections_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)

            # 删除该收藏夹
            collections["groups"] = [
                g for g in collections.get("groups", [])
                if g.get("id") != group_id
            ]

            # 删除该收藏夹下的所有收藏
            collections["items"] = [
                item for item in collections.get("items", [])
                if (item.get("group_id") or "default") != group_id
            ]

            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            print(f"[ERROR] Operation failed: {e}")
            return jsonify({"error": "operation_failed"}), 500


@collections_bp.route("/api/collections/import-from-zotero", methods=["POST"])
def import_from_zotero():
    """从 Zotero 导入所有文献到「Zotero」收藏夹"""
    import uuid as _uuid
    try:
        from search_engine import ZoteroNativeClient, ZoteroSQLiteReader
        from core.config import load_config

        papers = []
        diag = {"native_api": "not_tried", "sqlite": "not_tried", "zotero_version": "unknown"}

        # Tier 1: Zotero 9 原生 API
        try:
            native = ZoteroNativeClient()
            if native.ping():
                diag["native_api"] = "connected"
                papers = native.search("", limit=200)
                diag["native_count"] = len(papers)
                if papers:
                    diag["zotero_version"] = "9+"
            else:
                diag["native_api"] = "ping_failed"
        except Exception as e:
            diag["native_api"] = f"error: {e}"

        # Tier 2: SQLite 直读
        if not papers:
            try:
                cfg = load_config()
                custom_dir = (cfg.get("sources", {}).get("zotero_mcp", {}).get("data_dir") or "").strip()
                profile = ZoteroSQLiteReader.find_profile_dir(custom_dir=custom_dir)
                diag["profile_path"] = profile
                diag["custom_dir_used"] = bool(custom_dir)
                if not profile:
                    diag["sqlite"] = "profile_not_found"
                else:
                    sqlite = ZoteroSQLiteReader(profile_dir=profile)
                    if not sqlite.available:
                        diag["sqlite"] = "db_not_available"
                    else:
                        stats = sqlite.stats
                        diag["sqlite"] = f"connected ({stats.get('items',0)} items)"
                        papers = sqlite.search("", limit=200)
                        diag["sqlite_count"] = len(papers)
            except Exception as e:
                diag["sqlite"] = f"error: {e}"

        if not papers:
            return jsonify({"ok": False, "error": "no_zotero_papers",
                           "hint": "未检测到 Zotero 文献",
                           "diagnosis": diag})

        state = current_app.config["APP_STATE"]
        path = _get_user_data_path("collections.json")
        with state.collections_lock:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
            groups = collections.get("groups", [])
            zotero_group = None
            for g in groups:
                if g.get("name") == "Zotero":
                    zotero_group = g
                    break
            if not zotero_group:
                zotero_group = {"id": str(_uuid.uuid4()), "name": "Zotero", "color": "#E34F33"}
                groups.insert(0, zotero_group)

            existing_dois = set()
            existing_titles = set()
            for item in collections.get("items", []):
                doi = (item.get("doi") or "").lower()
                title = (item.get("title") or "").strip().lower()
                if doi: existing_dois.add(doi)
                if title: existing_titles.add(title)

            added = 0
            for p in papers:
                doi = (getattr(p, 'doi', '') or '').lower()
                title = (getattr(p, 'title', '') or '').strip().lower()
                if (doi and doi in existing_dois) or (title and title in existing_titles):
                    continue
                item = {
                    "id": str(_uuid.uuid4()),
                    "group_id": zotero_group["id"],
                    "title": getattr(p, 'title', '') or '',
                    "authors": getattr(p, 'authors', []) or [],
                    "year": getattr(p, 'year', 0) or 0,
                    "journal": getattr(p, 'journal', '') or '',
                    "doi": getattr(p, 'doi', '') or '',
                    "abstract": getattr(p, 'abstract', '') or '',
                    "source": "zotero",
                    "reading_status": "unread",
                    "added_at": datetime.now().isoformat(),
                }
                collections.setdefault("items", []).append(item)
                if doi: existing_dois.add(doi)
                if title: existing_titles.add(title)
                added += 1

            collections["groups"] = groups
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True, "added": added, "total": len(papers),
                       "group_name": zotero_group["name"]})
    except Exception as e:
        print(f"[ERROR] Zotero import failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@collections_bp.route("/api/import-file", methods=["POST"])
def import_file():
    """通用文献文件导入 — EndNote XML / RIS / BibTeX / CSV"""
    import uuid as _uuid
    import base64
    try:
        data = request.get_json(silent=True) or {}
        files_data = data.get("files", [])
        target_gid = data.get("group_id", "default")
        if not files_data:
            return jsonify({"ok": False, "error": "no_files", "hint": "未提供文件内容"})

        from import_parser import parse_file

        all_papers = []
        for fd in files_data:
            content = fd.get("content", "") or ""
            if not content:
                try:
                    content = base64.b64decode(fd.get("b64", "")).decode("utf-8", errors="replace")
                except Exception:
                    continue
            parsed = parse_file(content)
            all_papers.extend(parsed)

        if not all_papers:
            return jsonify({"ok": False, "error": "no_papers_parsed",
                           "hint": "未能从文件中解析出文献，请确认文件格式为 EndNote XML / RIS / BibTeX / CSV"})

        state = current_app.config["APP_STATE"]
        path = _get_user_data_path("collections.json")

        with state.collections_lock:
            with open(path, "r", encoding="utf-8") as f:
                collections = json.load(f)
            groups = collections.get("groups", [])
            # 查找目标分组或使用第一个
            target_group = None
            for g in groups:
                if g.get("id") == target_gid:
                    target_group = g
                    break
            if not target_group:
                target_group = groups[0] if groups else {"id": "default", "name": "默认收藏夹"}
                target_gid = target_group["id"]
            if not any(g.get("id") == target_gid for g in groups):
                groups.insert(0, target_group)

            existing_dois = set()
            existing_titles = set()
            for item in collections.get("items", []):
                doi = (item.get("doi") or "").lower()
                title = (item.get("title") or "").strip().lower()
                if doi: existing_dois.add(doi)
                if title: existing_titles.add(title)

            added = 0
            skipped = 0
            for p in all_papers:
                doi = (p.get("doi") or "").lower()
                title = (p.get("title") or "").strip().lower()
                if not title:
                    skipped += 1
                    continue
                if (doi and doi in existing_dois) or (title and title in existing_titles):
                    skipped += 1
                    continue
                item = {
                    "id": str(_uuid.uuid4()),
                    "group_id": target_group["id"],
                    "title": title,
                    "authors": p.get("authors", []) or [],
                    "year": p.get("year", 0) or 0,
                    "journal": p.get("journal", "") or p.get("journal", "") or "",
                    "doi": doi,
                    "abstract": p.get("abstract", "") or "",
                    "source": "file_import",
                    "reading_status": "unread",
                    "added_at": datetime.now().isoformat(),
                }
                collections.setdefault("items", []).append(item)
                if doi: existing_dois.add(doi)
                if title: existing_titles.add(title)
                added += 1

            collections["groups"] = groups
            with open(path, "w", encoding="utf-8") as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True, "added": added, "skipped": skipped, "total": len(all_papers)})
    except Exception as e:
        print(f"[ERROR] File import failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
