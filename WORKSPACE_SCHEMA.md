# Workspace 数据模型设计（Schema Design）

> 状态：设计稿（2026-09-27）· 对应 `ROADMAP.md` Phase 4a「Workspace schema 设计文档」
> 原则：**先定义数据模型，再开发 UI**。本文件只定义数据层，不含 UI 设计。

---

## 1. 现状（collections.json v3）

- **存储位置**：`<用户数据目录>/collections.json`（路径由 `core/config.py:_get_app_data_dir()` 决定）
- **版本管理**：顶层 `_schema_version`，迁移逻辑见 `schema_migrate.py`
- **写入方**：`routes/collections.py`

```json
{
  "_schema_version": 3,
  "groups": [
    { "id": "default", "name": "默认收藏夹" }
  ],
  "items": [
    {
      "title": "", "authors": [], "doi": "", "journal": "", "year": 0,
      "citation_count": 0, "oa_url": "", "pmid": "", "abstract": "",
      "keywords": [], "source": "", "volume": "", "issue": "", "pages": "", "issn": "",
      "orcid": "", "article_type": "", "conference": "", "funding": [], "sources": [],
      "reading_status": "unread",
      "tags": [], "notes": "",
      "group_id": "default",
      "added_at": "2026-09-27T19:00:00"
    }
  ]
}
```

**现状要点：**

| 能力 | 状态 |
|------|------|
| 分组 `groups: [{id, name}]` + item 的 `group_id` | ✅ 已具备 |
| 阅读状态 `reading_status`（`unread` / `reading` / `read`） | ✅ 已具备（PATCH `/api/collections/item`） |
| 标签 `tags` | ✅ 已具备 |
| 笔记 `notes` | ⚠️ **内嵌在 item 里**，只对「已收藏」论文存在 |

**核心缺口**：笔记与「是否收藏」绑死；想给一篇没收藏的论文记笔记做不到；每次改笔记都要重写整个 `collections.json`。

---

## 2. 目标模型

### 2.1 论文标识 `paper_id`（新增，统一关联键）

```
paper_id = "doi:"   + doi.lower()          # 有 DOI（优先）
         | "pmid:"  + pmid                 # 无 DOI、有 PMID
         | "title:" + _normalize_title(t)   # 都没有（复用 dedup.py 的归一化规则）
```

复用 `dedup.py:_normalize_title()`，保证与去重逻辑一致。

### 2.2 `collections.json` v4（保留，纯收藏）

```json
{
  "_schema_version": 4,
  "groups": [ { "id": "default", "name": "默认收藏夹", "order": 0 } ],
  "items": [ { "...原有字段...": "", "paper_id": "doi:10.xxxx/yyyy" } ]
}
```

相对 v3 的变化：
- item 新增 `paper_id`（迁移时补全）
- `groups` 新增 `order`（分组排序用）
- `notes` 字段**保留但冻结**（迁移后不再写入；读取时回退兼容，供回滚）

### 2.3 `notes.json` v1（新增，笔记独立存储）

```json
{
  "_schema_version": 1,
  "notes": {
    "doi:10.xxxx/yyyy": {
      "text": "笔记正文",
      "updated_at": "2026-09-27T19:00:00"
    }
  }
}
```

**收益：**
- 笔记可挂到**任何论文**（不止已收藏）
- 编辑笔记不再重写整个 `collections.json`（并发/性能更稳）
- 从收藏夹删除论文**不丢笔记**

### 2.4 派生指标（不落盘）

`citations_per_year`（引用速度）等派生值**不存储**，序列化时计算，见 `core/utils.py:_calc_citations_per_year()`。避免冗余与不一致。

---

## 3. 迁移策略（collections v3 → v4 + 新建 notes.json）

**铁律：先备份 → 再迁移 → 可回滚。**

1. 启动时 `migrate_all()` 检测 `_schema_version`（已有框架）
2. v3 → v4：
   - 为每个 item 计算并写入 `paper_id`
   - 把非空的 `item.notes` 写进 `notes.json`（key = `paper_id`）
   - **`item.notes` 原值保留不动** → 回滚安全
   - `groups` 补 `order`
3. 若 `notes.json` 不存在则创建（v1）
4. 迁移前自动备份（`migrate_file()` 已有 `.bak.<时间戳>` 机制）
5. 过渡期前端读笔记：**优先 `notes.json`，回退 `item.notes`**

**回滚方式**：恢复 `.bak` 文件 + 删除 `notes.json` 即可回到 v3 行为。

---

## 4. 明确不做（边界）

- ❌ 不引入数据库，继续用 JSON 文件
- ❌ 不做笔记富文本 / PDF 标注（Phase 6 议题）
- ❌ 不做分组嵌套（保持单层）
- ❌ 不新增第三方依赖

---

## 5. 待确认（需产品决策，再进入实现）

1. **分组是否需要 `type`**（项目 / 主题 / 状态）？当前只有 `name`。若要，加 `type` 字段。
2. **笔记是否需要保留历史版本**？当前设计只存最新一条。
3. **`notes.json` 是否需要导出/备份入口**？（用户数据安全考虑）

---

## 6. 相关文件

| 关注点 | 文件 |
|--------|------|
| 迁移框架 | `schema_migrate.py` |
| 收藏 CRUD | `routes/collections.py` |
| 标题归一化 | `dedup.py:_normalize_title` |
| 派生指标 | `core/utils.py:_calc_citations_per_year` |
| 数据目录 | `core/config.py:_get_app_data_dir` |
