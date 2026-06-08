<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">中文</a>
</p>

<p align="center">
  <h1 align="center">🔬 PaperLens</h1>
  <p align="center">智能学术论文检索平台 — 一眼看穿海量论文</p>
</p>

---

## 为什么需要 PaperLens？

每个科研人员都经历过这些痛点：

- **信息过载** — 每年发表数百万篇论文，人工浏览不现实
- **关键词不匹配** — 不知道精确术语时，传统搜索很难找到相关文献
- **平台分散** — 在 PubMed、Google Scholar、Web of Science 之间反复切换
- **缺乏上下文** — 搜索结果没有引用数、OA 链接和快速分析
- **手动操作繁琐** — 逐个复制 DOI 到文献管理软件

**PaperLens** 用一个智能界面解决了这些问题：多数据源聚合、AI 自然语言检索、一键论文分析。

## 功能特性

| 功能 | 说明 |
|------|------|
| **AI 智能检索** | 用中文或英文描述你的研究兴趣，AI 自动构建最优 PubMed 检索式 |
| **双数据源聚合** | PubMed + OpenAlex，自动去重、补充引用数和 OA 链接 |
| **AI 论文分析** | 选中论文后一键总结、详细分析或多篇对比 |
| **批量 DOI 导入** | 粘贴多个 DOI，一键查询 |
| **高级筛选** | 按期刊、字段标签、年份范围、文献类型过滤 |
| **结果内排序** | 按被引数、时间、标题即时排序，无需重新搜索 |
| **多格式导出** | RIS（EndNote）、BibTeX（LaTeX）、CSV |
| **搜索历史** | 持久化保存，支持快速重执行 |
| **双 AI 模型** | 检索用快速模型，分析用高质量模型，分别配置 |
| **引用关系图谱** | D3.js 力导向交互图谱 — 缩放、平移、拖拽节点、点击展开引用关系 |

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
git clone https://github.com/yourusername/PaperLens.git
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

### 基础检索
输入英文关键词，获取 PubMed + OpenAlex 结果，附带引用数据。

```
super-resolution microscopy[ti]
```

### AI 智能检索
用自然语言描述你的研究兴趣：

```
搜索关于定量相位成像的最新综述
Find recent papers on light-sheet microscopy for live cell imaging
```

AI 分析你的意图，构建最优 PubMed 检索式并执行。

### 论文分析
选中论文 → 点击 **AI 总结** / **AI 详析** / **AI 对比** → 即时获得分析结果。

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
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## 路线图（计划中，尚未实现）

以下是未来开发方向，欢迎贡献！

- [ ] OA 论文 PDF 集成下载（目前在浏览器中打开）
- [ ] 引用关系图谱可视化
- [ ] 基于阅读历史的论文推荐
- [ ] RAG 集成，辅助文献综述撰写
- [ ] Zotero / Mendeley 直接同步
- [ ] 多语言界面
- [ ] 协作论文收藏
- [ ] Chrome 扩展：DOI 快速查询

## 参与贡献

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)

---

<p align="center">
  <b>PaperLens</b> — 看穿噪音，找到关键。<br>
  为科研人员而生，由科研人员打造。
</p>
