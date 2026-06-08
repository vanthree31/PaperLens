<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">中文</a>
</p>

<p align="center">
  <h1 align="center">🔬 PaperLens</h1>
  <p align="center"><b>AI 驱动的学术科研助手</b> — 论文发现、智能分析、引用图谱探索</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/powered%20by-PubMed%20%2B%20OpenAlex-orange" alt="Data Sources">
    <img src="https://img.shields.io/badge/AI-RAG%20Architecture-purple" alt="AI RAG">
  </p>
</p>

---

## PaperLens 是什么？

PaperLens 不只是一个论文搜索工具 — 它是一个 **AI 驱动的科研助手**，帮你发现、分析、理解学术文献，通过统一的智能界面完成从检索到分析的全流程。

```
研究问题 → AI 理解意图 → 多源检索 → 引用网络 → AI 深度分析
```

**核心能力：**

- **AI 智能检索** — 用自然语言描述研究兴趣，AI 自动构建最优检索式
- **引用图谱探索** — 交互式图谱展示论文间的引用关系，点击展开发现关联
- **AI 论文分析** — 即时总结、详细分析、多篇对比
- **相关论文发现** — 通过共同引用模式发现相关论文
- **创新点检测** — AI 识别研究空白和未探索方向

## 为什么需要 PaperLens？

每个科研人员都经历过这些痛点：

- **信息过载** — 每年发表数百万篇论文，人工浏览不现实
- **关键词不匹配** — 不知道精确术语时，传统搜索很难找到相关文献
- **平台分散** — 在 PubMed、Google Scholar、Web of Science 之间反复切换
- **缺乏上下文** — 搜索结果没有引用数、OA 链接和快速分析
- **手动操作繁琐** — 逐个复制 DOI 到文献管理软件

PaperLens 用一个界面解决所有这些问题。

## 功能特性

### 检索与发现

| 功能 | 说明 |
|------|------|
| **AI 智能检索** | 用中文或英文描述研究兴趣，AI 自动构建最优 PubMed 检索式 |
| **双数据源聚合** | PubMed + OpenAlex，自动去重、补充引用数和 OA 链接 |
| **批量 DOI 导入** | 粘贴多个 DOI，一键查询 |
| **高级筛选** | 按期刊、字段标签、年份范围、文献类型过滤 |
| **结果内排序** | 按被引数、时间、标题即时排序，无需重新搜索 |

### AI 分析

| 功能 | 说明 |
|------|------|
| **AI 总结** | 每篇论文一段话概括 — 做了什么、怎么做的、为什么重要 |
| **AI 详析** | 7 个维度深度分析：核心贡献、研究动机、技术路线、关键结果、学术价值与局限、与本领域关系、未来方向 |
| **AI 对比** | 多篇论文系统对比：技术路线、创新点、互补性、研究空白 |
| **创新点检测** | AI 识别文献中未充分探索的领域、矛盾之处和有前景的研究方向 |

### 引用智能

| 功能 | 说明 |
|------|------|
| **引用关系图谱** | D3.js 力导向交互图谱 — 缩放、平移、拖拽节点、点击展开引用关系 |
| **相关论文发现** | 通过共同引用模式发现相关论文 — 找到搜索发现不了的关联 |
| **引用展开** | 点击图谱中任意节点加载其引用和被引论文 |

### 导出与集成

| 功能 | 说明 |
|------|------|
| **多格式导出** | RIS（EndNote）、BibTeX（LaTeX）、CSV |
| **PDF 下载** | 直接下载 OA 论文 PDF，带链接验证 |
| **搜索历史** | 持久化保存，支持智能建议 |
| **双 AI 模型** | 检索用快速模型，分析用高质量模型，分别配置 |

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                     PaperLens 前端                           │
│         单文件 HTML/CSS/JS + D3.js 引用图谱                  │
├─────────────────────────────────────────────────────────────┤
│                      Flask API 服务                          │
├──────────┬──────────┬───────────┬───────────┬───────────────┤
│  检索引擎 │ 引用网络  │   AI 助手  │  导出模块  │   配置管理    │
├──────────┴──────────┴───────────┴───────────┴───────────────┤
│              PubMed API  ·  OpenAlex API                     │
├─────────────────────────────────────────────────────────────┤
│       LLM 服务商 (DeepSeek / OpenAI / Claude / Ollama)      │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python, Flask |
| 前端 | HTML/CSS/JS（单文件，引用图谱用 D3.js） |
| 数据源 | PubMed E-utilities API, OpenAlex API |
| AI | 兼容 OpenAI / DeepSeek / Anthropic / Ollama API |
| 打包 | PyInstaller |

## 安装

```bash
# 克隆
git clone https://github.com/vanthree31/PaperLens.git
cd PaperLens

# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

应用会打开一个原生窗口（PyWebView），或在浏览器中打开。

### 打包为可执行文件

```bash
build.bat
# 输出: dist/PaperLens.exe（Windows，无需 Python 环境）
```

## 使用方法

### AI 智能检索
用自然语言描述研究兴趣：

```
搜索关于定量相位成像的最新综述
Find recent papers on light-sheet microscopy for live cell imaging
```

AI 分析你的意图，构建最优 PubMed 检索式并执行。

### 引用图谱探索
点击任意论文的 **引用关系图谱** 按钮 → 在交互式图谱中查看引用关系 → 点击节点展开 → 发现相关论文。

### AI 论文分析
选中论文 → 点击 **AI 总结** / **AI 详析** / **AI 对比** / **创新点检测** → 即时获得分析结果。

### 批量 DOI 导入
点击 📋 → 粘贴 DOI（每行一个）→ 一键查询。

## 配置

在应用内点击 **设置 (⚙)**：

| 配置项 | 说明 |
|--------|------|
| PubMed Email | 可选，提高 API 速率限制 |
| PubMed API Key | 可选，从 NCBI 获取 |
| AI 检索模型 | 快速模型，用于解析自然语言（如 deepseek-chat） |
| AI 分析模型 | 高质量模型，用于论文分析（如 deepseek-reasoner） |
| HTTP/HTTPS 代理 | 网络受限时使用 |

配置文件存储在 `%APPDATA%/PaperLens/`（Windows）。

## 项目结构

```
PaperLens/
├── main.py              # 入口（Flask + PyWebView）
├── server.py            # 后端 API 路由
├── search_engine.py     # PubMed + OpenAlex 检索引擎
├── ai_assistant.py      # AI 模块（双模型支持）
├── exporters.py         # RIS / BibTeX / CSV 导出
├── config.yaml          # 默认配置模板
├── requirements.txt     # Python 依赖
├── build.bat            # 一键打包脚本（Windows）
├── static/
│   └── index.html       # 前端界面（单文件应用）
├── README.md
├── README.zh-CN.md
├── LICENSE
└── CONTRIBUTING.md
```

## 路线图

### 已实现
- [x] AI 智能检索（自然语言 → PubMed 检索式）
- [x] 双数据源聚合（PubMed + OpenAlex）
- [x] AI 论文分析（总结 / 详析 / 对比 / 创新点）
- [x] 引用关系图谱（D3.js 交互式可视化）
- [x] 悬浮图谱窗口（可拖动，完整 AI 工具栏）
- [x] 相关论文发现（通过引用模式发现关联论文）
- [x] 创新点检测（AI 识别研究空白）
- [x] 批量 DOI 导入
- [x] 多格式导出（RIS / BibTeX / CSV）
- [x] 双 AI 模型配置
- [x] AI 分析流式输出
- [x] 用户偏好持久化（年份范围、排序、筛选条件）
- [x] 搜索历史智能建议
- [x] 引用图谱全屏切换（保留缩放状态）
- [x] 图谱缩放控制（重置、百分比显示）
- [x] 导出路径配置（直接保存到磁盘）
- [x] 数据目录管理
- [x] 设置重置为默认值
- [x] 本地论文收藏（支持自定义分组）

### 计划中
- [ ] 基于阅读历史的论文推荐
- [ ] RAG 集成，辅助文献综述撰写
- [ ] Zotero / Mendeley 直接同步
- [ ] 协作论文收藏
- [ ] Chrome 扩展：DOI 快速查询

## 参与贡献

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)

---

<p align="center">
  <b>PaperLens</b> — AI 驱动的科研助手<br>
  看穿噪音，找到关键，发现未来。<br>
  为科研人员而生，由科研人员打造。
</p>
