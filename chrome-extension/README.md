# PaperLens Chrome 扩展

快速查询和收藏学术论文的 Chrome 扩展，与 PaperLens 本地应用配合使用。

## 功能特性

- 🔍 **DOI 自动检测** - 在任何网页上自动检测 DOI
- 📄 **论文详情查询** - 一键查询论文摘要、作者、期刊、引用数
- ⭐ **快速收藏** - 将论文收藏到 PaperLens
- 🔗 **全文链接** - 直接访问开放获取论文

## 安装步骤

### 1. 确保 PaperLens 正在运行

```bash
cd PaperLens
python main.py
```

PaperLens 会在 `http://127.0.0.1:51234` 启动。

### 2. 安装 Chrome 扩展

1. 打开 Chrome，访问 `chrome://extensions/`
2. 启用右上角的 **"开发者模式"**
3. 点击 **"加载已解压的扩展程序"**
4. 选择 `chrome-extension` 文件夹

### 3. 生成图标（可选）

如果图标显示不正常，可以运行：

```bash
cd chrome-extension
pip install Pillow
python generate_icons.py
```

或者使用在线工具将 `icons/icon.svg` 转换为 PNG 格式：
- `icons/icon16.png` (16x16)
- `icons/icon48.png` (48x48)
- `icons/icon128.png` (128x128)

## 使用方法

### 自动检测 DOI

访问任何学术论文页面，扩展会自动检测页面上的 DOI：

- **PubMed** - 自动检测 `citation_doi` meta 标签
- **Google Scholar** - 从链接中提取 DOI
- **期刊官网** - 检测 meta 标签和页面内容
- **DOI 链接** - 访问 `doi.org` 链接时自动识别

### 查询论文

1. 点击扩展图标
2. 查看检测到的 DOI 列表
3. 点击 **"查询"** 按钮
4. 查看论文详情（摘要、作者、引用数等）

### 收藏论文

1. 查询论文详情后
2. 点击 **"收藏到 PaperLens"** 按钮
3. 论文将添加到 PaperLens 的默认收藏夹

## 支持的网站

扩展在所有网站上运行，特别优化了以下学术网站：

- PubMed (pubmed.ncbi.nlm.nih.gov)
- Google Scholar (scholar.google.com)
- Nature (nature.com)
- Science (science.org)
- Cell (cell.com)
- IEEE (ieeexplore.ieee.org)
- arXiv (arxiv.org)
- bioRxiv (biorxiv.org)
- 以及其他所有包含 DOI 的学术网站

## 故障排除

### 扩展显示"未连接"

确保 PaperLens 正在运行：

```bash
python main.py
```

### 未检测到 DOI

1. 确认页面包含 DOI（通常在论文详情页）
2. 尝试刷新页面
3. 检查页面是否有 `citation_doi` meta 标签

### 查询失败

1. 检查网络连接
2. 确认 PaperLens 服务器正常运行
3. 查看 PaperLens 控制台是否有错误信息

## 技术细节

- **Manifest V3** - 使用最新的 Chrome 扩展标准
- **DOI 检测** - 优先级：meta 标签 > URL > 正则匹配
- **API 通信** - 通过 `http://127.0.0.1:51234` 与 PaperLens 通信

## 开发

### 文件结构

```
chrome-extension/
├── manifest.json      # 扩展配置
├── popup.html         # 弹出窗口 UI
├── popup.js           # 弹出窗口逻辑
├── content.js         # 内容脚本（DOI 检测）
├── background.js      # 后台服务
├── styles.css         # 样式文件
├── generate_icons.py  # 图标生成脚本
└── icons/             # 扩展图标
```

### 修改和调试

1. 修改代码后，访问 `chrome://extensions/`
2. 点击扩展的刷新按钮
3. 重新加载测试页面

## 许可证

MIT License
