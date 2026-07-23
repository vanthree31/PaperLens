"""数据迁移框架 - JSON 文件 schema 版本管理

每个 JSON 文件通过顶层 _schema_version 字段追踪版本。
版本号从 0（无版本号）开始递增。
启动时自动检测并升级，升级前备份原文件。

用法:
    from schema_migrate import migrate_all
    migrate_all(data_dir)
"""

import os
import json
import shutil
from datetime import datetime


# ============ collections.json 迁移函数 ============


def _migrate_collections_v0_to_v1(data: dict) -> dict:
    """collections.json v0 -> v1: 新增阅读状态、标签、笔记、学术元数据、分组"""
    data.setdefault("groups", [{"id": "default", "name": "默认收藏夹"}])
    for item in data.get("items", []):
        item.setdefault("group_id", "default")
        item.setdefault("reading_status", "")
        item.setdefault("tags", [])
        item.setdefault("notes", "")
        item.setdefault("sources", [])
        item.setdefault("orcid", "")
        item.setdefault("article_type", "")
        item.setdefault("conference", "")
        item.setdefault("funding", [])
    return data


def _migrate_collections_v1_to_v2(data: dict) -> dict:
    """collections.json v1 -> v2: 修补缺失 group_id 的旧收藏项"""
    for item in data.get("items", []):
        item.setdefault("group_id", "default")
    return data


def _migrate_collections_v2_to_v3(data: dict) -> dict:
    """collections.json v2 -> v3: 再次确保所有收藏项有 group_id（防御性修补）"""
    data.setdefault("groups", [{"id": "default", "name": "默认收藏夹"}])
    for item in data.get("items", []):
        if not item.get("group_id"):
            item["group_id"] = "default"
    return data


# ============ 迁移注册表 ============

# 每个文件对应一个迁移函数列表，索引 i 对应 v(i) -> v(i+1) 的迁移
_MIGRATIONS = {
    "collections.json": [
        _migrate_collections_v0_to_v1,
        _migrate_collections_v1_to_v2,
        _migrate_collections_v2_to_v3,
    ],
    "reading_history.json": [],
    "preferences.json": [],
    "history.json": [],
}


def _get_schema_version(data: dict) -> int:
    """获取数据的 schema 版本号，无版本号返回 0"""
    if isinstance(data, dict) and "_schema_version" in data:
        try:
            return int(data["_schema_version"])
        except (ValueError, TypeError):
            return 0
    return 0


def migrate_file(filepath: str, filename: str, dry_run: bool = False) -> bool:
    """
    自动升级单个 JSON 文件。
    返回 True 表示发生了迁移，False 表示无需迁移。

    Args:
        filepath: JSON 文件完整路径
        filename: 文件名（用于查找对应的迁移函数）
        dry_run: 仅计算目标版本，不实际写入
    """
    if not os.path.exists(filepath):
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] schema_migrate: 无法读取 {filename}: {e}")
        return False

    if not isinstance(data, dict):
        if filename in ("history.json", "reading_history.json"):
            return False  # 数组格式文件，无需迁移，静默跳过
        print(f"[INFO] schema_migrate: {filename} 非 dict 格式，跳过迁移")
        return False

    current_ver = _get_schema_version(data)
    migrations = _MIGRATIONS.get(filename, [])
    target_ver = len(migrations)

    if current_ver >= target_ver:
        return False

    # 备份原文件
    if not dry_run:
        backup_path = filepath + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            shutil.copy2(filepath, backup_path)
            print(
                f"[INFO] schema_migrate: 备份 {filename} -> {os.path.basename(backup_path)}"
            )
        except IOError as e:
            print(f"[WARN] schema_migrate: 备份失败 {filename}: {e}")

    # 逐版本迁移
    for i in range(current_ver, target_ver):
        if i < len(migrations):
            try:
                data = migrations[i](data)
            except Exception as e:
                print(
                    f"[ERROR] schema_migrate: {filename} v{i}->v{i + 1} 迁移失败: {e}"
                )
                return False

    data["_schema_version"] = target_ver

    if not dry_run:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(
                f"[INFO] schema_migrate: {filename} v{current_ver} -> v{target_ver} 完成"
            )
        except IOError as e:
            print(f"[ERROR] schema_migrate: 写入 {filename} 失败: {e}")
            return False

    return True


def migrate_all(data_dir: str, dry_run: bool = False) -> None:
    """
    对 data_dir 下所有已知 JSON 文件执行迁移。
    在 server.py 的 create_app() 中调用一次。
    """
    for filename in _MIGRATIONS:
        filepath = os.path.join(data_dir, filename)
        try:
            migrate_file(filepath, filename, dry_run=dry_run)
        except Exception as e:
            print(f"[ERROR] schema_migrate: {filename} 迁移异常: {e}")
