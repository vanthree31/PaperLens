# PaperLens 发展路线图

> **PaperLens = AI 驱动的文献管理与分析工作台（Research Workbench）**
>
> 一个面向科研人员的本地化学术文献搜索、管理与分析工具。

## 设计原则

1. **Paper First** — 论文始终是界面的主角
2. **Progressive Disclosure** — 默认界面只展示高频功能
3. **AI On Demand** — AI 分析必须保持按需触发，同时支持上下文感知的主动建议
4. **Workspace Driven** — 搜索只是入口，真正的目标是建立研究工作区
5. **Focus Mode** — 第一视觉焦点必须是搜索框或论文列表
6. **Calm Interface** — 减少边框、颜色和视觉噪音

## 目标架构

```
┌────────────────────────────────────────────────────────────┐
│ Sidebar        Results              Inspector             │
│ ──────────     ───────────────      ───────────────────── │
│ Search         Paper List           Details               │
│ Workspace      (compact 100px)      Abstract              │
│ History                            Authors / ORCID        │
│ Settings                           Journal/DOI/PDF        │
│                                    ✨ AI Context Panel    │
│                                    ⭐ Save / Status       │
│                                    📝 Notes               │
│                                    Export (formatted)     │
└────────────────────────────────────────────────────────────┘
```

---

## Phase 1：UI 精简 + 引用导出 + 搜索稳定性 ✅

**目标**：立竿见影的 UI 改进 + 低成本高收益的导出增强 + 搜索功能稳定

- [x] iOS 风格 UI（毛玻璃、圆角、系统色）
- [x] 开关控件改为 iOS 风格
- [x] 搜索模式切换改为显式按钮
- [x] 搜索结果改为紧凑列表（~100px/项）
- [x] 默认隐藏筛选器，加「高级筛选」折叠按钮
- [x] 卡片操作简化（Save + Analyze + ⋯ 菜单）
- [x] 设置面板各组折叠
- [x] 动画时间统一 150-220ms ease-out
- [x] 颜色统一为 iOS 系统色
- [x] 字体统一 SF Pro
- [x] 数据来源标识美化（彩色色条）
- [x] 液态玻璃效果（CSS backdrop-filter）
- [x] 搜索功能全面修复（10个bug：pub_type丢失、作者搜索、年份过滤等）
- [x] CNKI搜索浏览器复用（避免重复验证）
- [x] AI搜索期刊提取后备机制
- [x] 期刊过滤支持逗号分隔（nature,cell,science）
- [x] 年份默认值统一10年范围
- [x] Zotero同步状态检测修复
- [x] 历史记录UX优化（动态高度、点击只填入不自动搜索）
- [x] 引用格式化导出：APA / MLA / GB/T 7714 / Chicago / Vancouver
  - citation_formatter.py 模块（30/30 测试通过）
  - 前端下拉菜单 + 下载文件
- [x] **阅读状态跟踪**（已读 / 未读 / 阅读中）
  - 后端 PATCH /api/collections/item 端点
  - 前端三态切换（灰色/黄色/绿色圆点）
- [x] **批量导出**：勾选多篇论文后一键导出 BibTeX / RIS / CSV
  - 前端复选框 + 全选 + 批量操作栏
- [x] 新手引导：3 步叠加层引导（搜索框 → 结果列表 → 收藏按钮）
  - 半透明遮罩 + 高亮框 + 简短文字，支持跳过和不再显示
  - localStorage 标记 onboarding_done，首次启动弹出
- [x] 搜索模式切换增加 Tooltip 说明（data-i18n-title 中英文）

## Phase 2：前后端架构拆分 ✅

**目标**：解决前端 8405 行 + 后端 2895 行单文件技术债务，为后续所有 Phase 提供可维护的代码基础

**前置条件**：Phase 1 完成

### 2.0 架构设计阶段

- [x] **pywebview ES Modules 兼容性 POC**
  - pywebview 6.2.1 + WebView2 原生支持 ES Modules
  - 验证通过：import 路径、MIME type、CORS 策略
- [x] **定义模块通信架构**：集中状态 + 直接引用模式
  - window.PaperLens 共享状态对象（getter/setter）
  - Object.defineProperty 桥接 inline 代码和模块
- [x] 输出模块拆分方案文档

### 2.1 前端拆分

- [x] CSS 拆分为 9 个独立文件（1556 行）
  - reset.css / header.css / search.css / paper.css / settings.css / ai.css / graph.css / collections.css / misc.css
- [x] JS 拆分为 6 个模块 + app.js 入口
  - state.js（共享状态）/ i18n.js（翻译）/ utils.js（工具）/ search.js（搜索）/ collection.js（收藏）/ zotero.js（Zotero 同步）
- [x] app.js 入口模块：导入所有模块，映射 152 个 window 函数
- [x] index.html 行数：8405 → 4384 行（-48%）
- [x] 保持 pywebview 兼容性（ES Module 加载）

### 2.2 后端拆分

- [x] server.py（2895 行）拆分为 core/ + routes/ 模式
  - core/config.py — 配置管理
  - core/utils.py — 工具函数
  - core/state.py — AppState 共享状态（替代闭包 nonlocal）
  - core/ai.py — AI 助手管理
  - routes/search.py — 搜索路由
  - routes/ai.py — AI 分析路由
  - routes/collection.py — 收藏路由
  - routes/system.py — 系统配置路由
  - ... 共 14 个模块
- [x] 53 个路由全部正确注册
- [x] 14 个模块无循环依赖

### 2.3 验证

- [x] **回归测试**：5 条关键路径全部通过
- [x] **路由一致性**：前端 40 个 API 端点与后端一致
- [x] **脱敏规则**：7 个测试用例通过
- [ ] **性能基准测试**：记录拆分前后页面加载时间（待做）

**为什么单独一个 Phase**：单文件架构是 Phase 3-6 所有工作的技术瓶颈。拆分后每个文件 500-1000 行，修改成本和回归风险大幅降低。

## Phase 3：三栏布局 + AI Inspector

**目标**：Sidebar + List + Inspector 三栏布局，Inspector 成为论文详情和 AI 分析的主战场

**前置条件**：Phase 2 完成

### 3.1 三栏布局

- [ ] 左侧 Sidebar：搜索 / Workspace / 历史 / 设置
- [ ] 中间 Results：紧凑论文列表
- [ ] 右侧 Inspector：论文详情 + AI 分析
- [ ] 响应式布局：
  - \>900px 三栏
  - 600-900px 双栏（Sidebar 折叠为图标栏 48px）
  - <600px 单栏钻取模式（默认列表 → 点击滑入 Inspector → 顶部返回按钮，底部 FAB 浮动操作栏）
- [ ] Inspector 底部操作区：Save + Export + Notes + Status

### 3.2 AI Context Panel

- [ ] AI Context Panel：用户选中论文时展示（渐进式展开设计）
  - **默认显示**：关键发现摘要 + 阅读优先级（2 项）
  - **展开显示**（Tab 切换）：研究方法分类、与 Workspace 其他论文的关系
- [ ] **AI Context Panel 完整状态设计**：
  - 加载态：骨架屏 + 流式文本
  - 成功态：置信度标签 + 分析结果
  - 失败态：网络错误 / 限流 / 超时的具体提示 + 重试按钮
  - 空态：引导用户保存论文到 Workspace
- [ ] **AI 缓存策略**：选中论文时先检查本地缓存，未命中再触发 AI 分析
  - 定义缓存过期策略和存储上限
- [ ] 流式 AI 输出在 Inspector 中显示
- [ ] 多论文对比视图（结构化表格，非纯文本）

### 3.3 笔记基础功能

- [ ] 纯文本笔记和摘要文本高亮（基于 DOM Selection API）
  - Phase 6 再考虑 PDF 内标注（需 PDF.js 集成，复杂度极高）
- [ ] 笔记数据独立存储为 notes.json（paper_id → notes），不嵌入 collections.json

### 3.4 AI 模型分层策略

- [ ] 定义三级模型策略：
  - **Tier 1**（轻量快速，Haiku/Mini）：自动标签、简单分类
  - **Tier 2**（中等，Sonnet/GPT-4o）：摘要生成、对比分析
  - **Tier 3**（强力推理）：文献综述、深度分析
- [ ] 每层对应不同 token 消耗和延迟预期
- [ ] 允许用户高级设置覆盖模型选择

## Phase 4a：Workspace 基础框架

**目标**：从收藏夹升级为结构化研究工作区

**前置条件**：Phase 3 完成

- [ ] 收藏夹改名为 Workspace
- [ ] 支持分组（项目 / 主题 / 状态）
- [x] **批量导出**：已在 Phase 1 完成（复选框 + 全选 + 批量操作栏）
- [ ] **Workspace schema 设计文档**（先定义数据模型，再开发 UI）
- [ ] **引用速度指标**（citations/year，本地零 API 调用计算）
- [ ] **笔记数据独立存储**：notes.json（paper_id → notes），不嵌入 collections.json

**Definition of Done**：所有勾选项完成 + 5 条回归测试通过 + 无 P0/P1 bug + 文档更新

---

## Phase 4b：Workspace AI 增强

**目标**：在 Workspace 基础上叠加 AI 能力

**前置条件**：Phase 4a 完成

### AI 成本控制系统（基础设施）

- [ ] **Workspace 级 token 预算设置**：用户可设置每月/每项目的 token 上限
- [ ] **自动标签默认关闭**：用户首次保存论文时弹出确认，明确告知 token 消耗
- [ ] **批量操作前显示预估消耗**：预估 token 数量和费用，用户确认后执行
- [ ] **分析结果缓存复用**：已有分析结果不重复调用

### AI 功能

- [ ] **AI 自动标签**：论文保存后 AI 读摘要自动打标签（研究方法、创新类型、学科子领域）
  - 改为批量异步处理：积累到 5 篇或用户手动触发，减少 API 调用次数
  - 使用 Tier 1 模型（轻量快速）
- [ ] **阅读优先级排序**：AI 根据质量/相关性/新颖性综合评分（Tier 2 模型）
- [ ] **批量 AI 操作**：勾选多篇论文后
  - 一键 AI 对比分析（输出结构化表格，Tier 2 模型）
  - 一键 AI 综述摘要
  - 操作前确认弹窗 + 操作中进度条 + 支持暂停/继续/取消
- [ ] **AI 分析历史**：保存所有 AI 分析结果，可回溯查看
  - 整合现有 ai_analysis_cache.json 机制（内存 50 条 + 持久化 100 条）
  - 定义上限 + 清理策略 + 导出功能

**Definition of Done**：所有勾选项完成 + AI 操作正确性测试通过 + token 成本控制验证 + 无 P0/P1 bug

## Phase 5：数据模型扩展 + 数据源补充

**目标**：扩展 Paper 数据模型，补充高价值数据源

**前置条件**：Phase 2 完成（数据模型扩展可与 Phase 3/4 并行，但 reading_status/tags 字段是 Phase 4b 的前置依赖）

### 5a. 数据模型扩展（优先）

- [x] **数据迁移策略**：
  - schema_migrate.py 模块，schema 版本号追踪
  - 自动升级逻辑，启动时检测并迁移旧数据
  - 旧数据默认值处理（reading_status 默认 unread）
- [x] Paper 数据模型增加字段：
  - `orcid`（作者消歧，OpenAlex/CrossRef 已返回但未存储）
  - `article_type`（区分 review / meta-analysis / original research）
  - `conference`（CS 领域核心需求）
  - `funding`（基金信息，Dimensions/OpenAlex 提供）
  - `reading_status`（已读 / 未读 / 阅读中）
  - `tags`（AI 自动标签 + 手动标签）
  - `notes`（用户批注）
  - `sources`（来源源列表，支撑去重标记）
- [x] **跨源 DOI 去重**：
  - dedup.py 模块，以 DOI 为主键
  - 元数据合并规则：摘要取最长、引用数取最新、作者格式统一为 full name
  - 合并后标记来源（sources 字段）
- [x] 存储 OpenAlex 扩展数据（学科分类 concepts/topics、机构归属）

### 5b. 数据源补充（按用户反馈驱动）

**已接入（43 源）**：
- [x] PubMed + OpenAlex（核心）
- [x] CrossRef + arXiv（免费）
- [x] ScienceDirect + Scopus + JSTOR（CARSI）
- [x] CNKI + Wanfang + VIP（中文，Playwright 模式）
- [x] Semantic Scholar + Google Scholar + Bing Academic
- [x] DBLP（CS 会议论文，免费 API）
- [x] bioRxiv + medRxiv（生物医学预印本，免费 API）
- [x] AGRIS（农业/环境，FAO 免费 API）
- [x] ACS Publications（化学/材料，CrossRef 过滤）
- [x] Optica（光学/光子学，CrossRef 过滤）
- [x] IOP Publishing（物理学，CrossRef 过滤）
- [x] AIP Publishing（物理学，CrossRef 过滤）
- [x] RSC Publishing（化学，Royal Society of Chemistry，CrossRef 过滤）
- [x] Europe PMC（生物医学 OA，免费 REST API）
- [x] Springer Nature（综合性，CrossRef 过滤）
- [x] Wiley（综合性，CrossRef 过滤）
- [x] IEEE（工程/计算机科学，CrossRef 过滤）
- [x] Project MUSE（人文艺术，CrossRef 过滤）
- [x] CORE（OA 论文聚合，3 亿+ 记录）
- [x] Lens.org（学术文献 + 专利，2.5 亿+ 记录，含专利检索）
- [x] Zenodo（CERN OA 仓储，数据集/软件/预印本/报告）
- [x] DataCite（全球 DOI 注册，4700 万+ DOI，含 citation/usage 统计）
- [x] Zotero Local（本地 Zotero 库搜索，SQLite 直读 + MCP 双层 + Zotero 9 原生 API）
- [x] Frontiers（开放获取期刊，免费 API + CrossRef 过滤）
- [x] ACM Digital Library（CS 会议论文，CrossRef 过滤）
- [x] Oxford Academic（Oxford University Press，CrossRef 过滤）
- [x] Cambridge Core（Cambridge University Press，CrossRef 过滤）
- [x] SAGE Publications（社科期刊，CrossRef 过滤）
- [x] Taylor & Francis（综合期刊，CrossRef 过滤）
- [x] EBSCO（综合学术数据库，CrossRef 过滤）
- [x] Web of Science（CARSI 认证 + Playwright 爬虫）
- [x] ProQuest（学位论文，CARSI 认证 + Playwright 爬虫）
- [x] J-STAGE（日本学术论文，JST 免费 API）
- [x] Cochrane Library（循证医学系统综述，PubMed 解析）

**暂缓接入**：
- [ ] SSRN（社科预印本，无官方 API）— 按用户反馈决定
- [ ] Dimensions（需 SRAD 申请）— 按用户反馈决定

### 5c. 2026-07 搜索基础设施大规模升级 ✅

**目标**：34 源全字段覆盖 + 搜索稳定性 + 智能排序

- [x] **跨源合并去重**：`deduplicate_papers()` 字段级非空覆盖空，替换先到先得
- [x] **DOI 直查快速通道**：检测 DOI 格式直接调 CrossRef `/works/{doi}`
- [x] **元数据完整性评分**：0-100 分，前端百分比徽章
- [x] **RRF 加权排序**：源质量权重 + 多源收录加分 + BM25 混合
- [x] **分赛道线程池**：快源 8w/12s，慢源 3w/40s，Playwright 隔离
- [x] **错峰启动 + 自动重试**：50ms 间隔 + 429/5xx 退避，34 源全覆盖
- [x] **SSE 心跳保活**：15s heartbeat 防代理超时
- [x] **缓存增强**：journal/field/pub_type key + query 规范化 + 年份超集
- [x] **中文数据库增强**：CNKI JS 注入模式 + 万方/维普详情页摘要抓取
- [x] **Zotero 集成**：SQLite 直读零配置 + MCP 一键安装 + 标签双向同步 + PDF 全文
- [x] **CARSI 保活**：后台 15 分钟心跳线程
- [x] **搜索结果源感知**：Chip 栏 + 搜索诊断面板
- [x] **液态玻璃 UI**：Apple HIG 2025 三层 Design Token + 光斑背景
- [x] **导出管理**：默认 ~/PaperLens_Exports/ + 自动子文件夹 PDF/RIS/BibTeX/CSV/Citations

## Phase 6：高级功能（验证需求后启动）

**目标**：聚焦可落地的高级功能，而非四个并列的重量级产品

**前置条件**：Phase 4b 完成 + 用户需求验证

**验证框架**：
- 验证方法：用户访谈 n≥5 或 GitHub Issue 需求统计
- 验证标准：至少 N 个用户明确表示需要
- 决策门槛：达到标准则启动，否则继续延后
- 可用功能开关 + 使用数据分析来验证

### 6a. 智能引用图谱增强（优先）

- [ ] 增强现有 D3.js 引用图谱：节点叠加 AI 分析标签
- [ ] 关键词共现网络可视化
- [ ] 作者合作网络可视化
- [ ] 先做基于 OpenAlex 的英文论文图谱（已有基础）
- [ ] 中文论文图谱（需 CNKI/Wanfang 引用数据，技术难度高，按需推进）

**启动条件**：Phase 4b 完成后，用户反馈中 ≥20% 提及图谱需求

### 6b. AI 文献综述（Workspace 子功能）

- [ ] 输入 Workspace 中 10-30 篇论文
- [ ] 输出结构化文献综述草稿（背景 / 方法 / 发现 / 研究空白）
- [ ] 作为 Workspace 的批量 AI 操作之一，而非独立产品
- [ ] **质量控制机制**（学术诚信保障）：
  - 输出中标注每个论断的来源论文（可追溯）
  - 关键结论高亮标注提示验证
  - 提供标记错误按钮
  - 考虑综述模板降低 AI 输出不确定性
  - 使用 Tier 3 模型（强力推理）
- [ ] **分块处理方案**：对超过上下文窗口的论文集，先按主题聚类分块，每块生成子综述，再合并

**启动条件**：Phase 4b 完成后，用户反馈中 ≥15% 提及综述需求

### 延后（验证用户需求后再启动）

每个延后功能需明确启动条件和退出标准，防止无限期搁置：

- [ ] **Research Notebook** — 竞品众多（Obsidian/Notion），需明确定位差异化
  - 启动条件：用户访谈中 ≥30% 提及笔记功能不足
  - 退出标准：Phase 4b 笔记功能满足 80% 用户需求
- [ ] **Writing Assistant** — 偏离核心定位，需评估用户需求
  - 启动条件：GitHub Issue 中 ≥10 个提及写作辅助
  - 退出标准：用户明确表示不需要
- [ ] **Proactive Literature Monitoring** — 定期自动检索新论文并推送，从工具升级为服务
  - 启动条件：用户反馈中 ≥20% 提及追踪需求
  - 退出标准：Phase 4b AI 功能满足 80% 用户需求
- [ ] **Semantic Search** — 基于向量嵌入的语义搜索，对跨语言检索价值高
  - 启动条件：用户反馈中 ≥15% 提及搜索质量问题
  - 退出标准：当前搜索功能满足 90% 用户需求
- [ ] **PDF 标注/高亮/批注** — 需 PDF.js 集成、跨平台兼容性挑战
  - 启动条件：用户反馈中 ≥25% 提及 PDF 标注需求
  - 退出标准：Phase 3 文本标注满足 80% 用户需求
  - 替代方案：链接到外部 PDF 阅读器 + 保存阅读笔记

---

## 技术约束

- 框架：pywebview（Web 技术，非原生 UI）
- 前端：ES Modules（Phase 2 拆分后），零构建步骤
- 后端：Python Flask + RESTful API
- 数据存储：本地 JSON/YAML 文件
- AI 模型分层：Tier 1（轻量）/ Tier 2（中等）/ Tier 3（强力推理）

## AI 触发层级

明确 AI 触发方式，让用户建立稳定心理模型：

| 触发级别 | 说明 | 示例 |
|----------|------|------|
| 自动触发 | 零交互，后台静默执行 | AI 自动标签（批量异步） |
| 半自动触发 | 一次点击，用户主动发起 | AI Context Panel 分析、阅读优先级 |
| 手动触发 | 显式操作，用户明确请求 | 批量对比分析、文献综述 |

## 风险登记册

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| pywebview + ES Modules 兼容性不可行 | 中 | 致命 | Phase 2 POC 验证（1-2 天），备选 esbuild 单文件打包 |
| Phase 4 范围膨胀导致交付周期失控 | 高 | 高 | 拆分 4a/4b，每子 Phase ≤5 个功能点 |
| AI API 调用无成本控制导致用户账单惊吓 | 高 | 高 | token 预算系统、自动标签默认关闭、批量操作预估消耗 |
| 数据模型扩展导致旧数据丢失或功能异常 | 中 | 高 | schema 版本号 + 自动升级逻辑 + 迁移脚本模板 |
| AI 文献综述产生幻觉引用/编造数据 | 中 | 致命 | grounding 机制（标注来源论文）+ 用户审核流程 + 强模型 |
| CARSI 数据源稳定性 | 中 | 中 | 独立稳定性测试，不一次新增多个 |
| Playwright 线程冲突 | 低 | 高 | 专用线程 + Queue 通信（已验证模式） |

## 时间线与里程碑

采用相对估算（T-shirt sizing），每个 Phase 的 Definition of Done：

| Phase | 规模估算 | DoD |
|-------|----------|-----|
| Phase 1 | S（1-2 周） | 所有勾选项完成 + 5 条回归测试通过 + 无 P0/P1 bug |
| Phase 2 | L（3-4 周） | POC 验证通过 + 前后端拆分完成 + 性能基准不回退 + 5 条回归测试通过 |
| Phase 3 | L（3-4 周） | 三栏布局 + AI Context Panel 状态完整 + 缓存策略生效 + 响应式交互验证 |
| Phase 4a | M（2-3 周） | Workspace 基础功能 + schema 设计文档 + 批量导出 + 5 条回归测试通过 |
| Phase 4b | L（3-4 周） | AI 成本控制 + 自动标签 + 批量 AI 操作 + token 预算验证 + AI 正确性测试 |
| Phase 5 | M（2-3 周） | 数据迁移脚本 + DOI 去重 + 新字段存储 + 旧数据兼容验证 |
| Phase 6 | XL（4-6 周） | 需求验证通过后启动，图谱增强 + 综述质量控制验证 |

**Phase 间依赖关系**：
- Phase 1 → Phase 2（技术前置）
- Phase 2 → Phase 3（架构拆分后才能做三栏布局）
- Phase 3 → Phase 4a → Phase 4b（顺序依赖）
- Phase 2 → Phase 5（可与 Phase 3/4 并行，但 reading_status/tags 字段是 Phase 4b 前置依赖）
- Phase 4b → Phase 6（需用户需求验证）

## 用户旅程映射表

| 用户动作 | 触发的 Phase 功能 | 涉及的 UI 区域 | 数据流向 |
|----------|-------------------|----------------|----------|
| 输入关键词搜索 | Phase 1：搜索框 + 数据源切换 | Sidebar + Results | → server.py → 各数据源 API |
| 浏览搜索结果 | Phase 3：紧凑论文列表 | Results 面板 | 本地缓存 |
| 点击查看论文详情 | Phase 3：Inspector 面板 | 右侧 Inspector | 本地 → Inspector |
| 选中论文触发 AI 分析 | Phase 3：AI Context Panel | Inspector 底部 | → AI API → 流式返回 |
| 保存论文到 Workspace | Phase 4a：Workspace 分组 | Inspector 底部 | → collections.json |
| 批量导出引用 | Phase 1/4a：批量导出 | 底部操作栏 | → exporters.py → 下载 |
| AI 自动标签 | Phase 4b：异步标签 | 后台 + Workspace | → AI API → tags.json |
| 批量 AI 对比分析 | Phase 4b：批量操作 | 底部操作栏 | → AI API → 结构化表格 |

## 贡献指南

欢迎贡献！请参考 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 修订记录

### 2026-07-07（v2.4）UI 全面美化 + Bug 修复

**主要修订**：

**UI 美化**：
1. 液态玻璃效果全面增强（3 级：elevated/base/suppressed）
2. 所有组件添加折射边缘（refraction edge）
3. 圆角统一为 Apple 标准 4 级（8/12/16/20px）
4. 间距对齐 8pt 网格系统
5. 知识图谱页面全面美化（节点渐变、连线动画、液态玻璃面板）
6. 设置面板改为点击外部关闭（移除关闭按钮）
7. 批量操作栏添加弹簧动画（translateY + scale + opacity）
8. 历史记录下拉移除动画（改为简单 display 切换）

**Bug 修复**：
9. 修复引用图谱/PDF 下载按钮无响应（导出函数到 window）
10. 修复 Playwright 安装按钮无响应（导出函数到 window）
11. 修复图谱面板 opacity:0 阻止 SVG 渲染
12. 修复图谱 AI 面板绿色背景（替换为液态玻璃）
13. 修复图谱 AI 全屏遮挡问题（改为面板内展开）
14. 修复图谱 AI 标题固定（动态显示：AI 总结/详析/创新点）
15. 修复搜索模式不切换（setSearchMode 更新 window.PaperLens._searchMode）
16. 修复数据源 checkbox 状态未持久化
17. 修复 _historyCache 遮蔽问题（使用 window bridge）
18. 修复 selectedJournals 遮蔽问题（使用 getter 函数）
19. 修复 savePreferences/updateDataSourceDisplay ReferenceError
20. 修复 CNKI search 缩进 bug（page.close() 在 for 循环内）
21. 修复 Flask debug=True 安全风险（改为环境变量控制）

**架构改进**：
22. 统一状态管理：所有模块通过 window.PaperLens 访问可变状态
23. 提取 buildSearchBody() 公共函数，消除代码重复
24. 移除 setTimeout(0) monkey-patch，直接在模块中实现

---

### 2026-07-06（v2.3）Phase 2 架构拆分完成

**主要修订**：

**Phase 2 完成**：
1. pywebview ES Modules 兼容性 POC 验证通过
2. 模块通信架构：集中状态 + 直接引用模式（window.PaperLens）
3. CSS 拆分为 9 个独立文件（1556 行）
4. JS 拆分为 6 个模块 + app.js 入口（state/i18n/utils/search/collection/zotero）
5. server.py 拆分为 core/ + routes/ 模式（14 个模块）
6. index.html 行数：8405 → 4384 行（-48%）
7. 53 个路由全部正确注册，14 个模块无循环依赖

**Phase 1 补充完成**：
8. 引用格式化导出（APA/MLA/GB/T 7714/Chicago/Vancouver）
9. 阅读状态跟踪（已读/未读/阅读中）
10. 批量导出（复选框 + 批量操作栏）
11. 键盘快捷键体系
12. 新手引导（3 步叠加层）
13. 搜索模式 Tooltip

**Phase 5a 完成**：
14. 数据迁移策略（schema_migrate.py）
15. Paper 新增 8 字段
16. 跨源 DOI 去重（dedup.py）

---

### 2026-07-06（v2.2）行业专家评审修订

**评审团队**：多维度评审（功能优先级 / AI 产品 / 技术架构 / 用户体验 / 项目管理）

**主要修订**：

**P0（必须解决）**：
1. Phase 4 拆分为 4a（Workspace 基础框架）和 4b（AI 增强），每子 Phase ≤5 个功能点
2. 阅读状态跟踪从 Phase 4 提前到 Phase 1
3. 批量导出从 Phase 4 提前到 Phase 1
4. Phase 2 补充：pywebview ES Modules 兼容性 POC、架构设计阶段（模块通信架构）、server.py 拆分、性能基准测试、回归测试最小集合
5. Phase 2 模块拆分目标从 300-500 行调整为 500-1000 行
6. Phase 3 AI Context Panel 增加完整状态设计（加载/成功/失败/空态）、缓存策略、渐进式展开
7. Phase 3 增加 AI 模型分层策略（Tier 1/2/3）
8. Phase 3 增加笔记基础功能（纯文本笔记 + 摘要高亮 + 独立存储）
9. Phase 4b 增加 AI 成本控制系统（token 预算、自动标签默认关闭、批量操作预估消耗）
10. Phase 4b AI 自动标签改为批量异步处理
11. Phase 5a 增加数据迁移策略（schema 版本号 + 自动升级逻辑）
12. Phase 5a 跨源 DOI 去重提升为最高优先级子任务，定义元数据合并规则

**P1（重要改进）**：
13. 新增键盘快捷键体系（Phase 1）
14. Phase 3 响应式布局补充单栏钻取模式交互方案
15. Phase 4a 增加批量操作交互设计（复选框 + 全选 + 进度条）
16. Phase 6 增加验证框架（验证方法/标准/决策门槛）
17. Phase 6 AI 文献综述增加质量控制机制（来源追溯 + 标记错误 + 分块处理）
18. 新增风险登记册章节（7 项关键风险）
19. 新增时间线与里程碑章节（T-shirt sizing + DoD）
20. 新增 AI 触发层级分类（自动/半自动/手动）
21. 新增用户旅程映射表（8 条核心路径）

**P2（优化建议）**：
22. Phase 6 延后功能增加启动条件和退出标准
23. 笔记标注分阶段实现（Phase 3 文本标注，Phase 6+ PDF 标注）
24. 引用格式化导出明确实现路径（citation_formatter.py 模块）


---

### 2026-07-06（v2.1）搜索稳定性 + UI 优化

**主要修订**：
1. Phase 1 更新：新增搜索稳定性相关完成项（10个bug修复）
2. 搜索功能全面修复：
   - AI搜索期刊提取后备机制
   - 期刊过滤支持逗号分隔（nature,cell,science）
   - 作者搜索修复（OR查询、PubMed格式转换、OpenAlex过滤器）
   - pub_type参数传递修复
   - 年份默认值统一10年范围
   - AI搜索优先使用前端年份参数
3. CNKI搜索浏览器复用（避免重复验证）
4. Zotero同步状态检测修复
5. 液态玻璃效果优化（移除SVG滤镜，保留CSS backdrop-filter）
6. 历史记录UX优化（动态高度、点击只填入不自动搜索）

### 2026-07-06（v2.0）

**评审团队**：5 位行业专家（科研工作流 / AI 产品 / 学术软件架构 / 学术数据 / 用户体验）

**主要修订**：
1. 产品定位从「科研操作系统」收窄为「AI 驱动的文献管理与分析工作台」
2. 新增 Phase 2：前端架构拆分（ES Modules，技术前置条件）
3. Phase 4 合并原 History 增强 + Workspace，加入 AI 自动标签/批量操作
4. Phase 5 拆分为 5a 数据模型扩展 + 5b 数据源补充，优先级重排
5. Phase 6 精简为 6a 图谱增强 + 6b 文献综述，延后验证需求的功能
6. 更新已实现的数据源列表（26+ 源）
7. 新增共识功能：引用格式化导出、批量操作、论文标注笔记、阅读状态跟踪
