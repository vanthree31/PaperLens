// ========== 图谱模块 — iOS Liquid Glass Style ==========
import { API, escapeHtml, debugLog } from './state.js';
import { t } from './i18n.js';

// ========== 配置常量 ==========
const COLOR_MAP = {
  center: "#2563eb",
  citing: "#10b981",
  referenced: "#f59e0b",
  network: "#8b5cf6",
};

const MAX_CITING = 20;
const MAX_REFERENCED = 20;
const CHARGE_STRENGTH = -800;
const CHARGE_DISTANCE_MAX = 500;
const LINK_STRENGTH = 0.5;
const CENTER_STRENGTH = 0.06;
const COLLIDE_PADDING = 30;
const ALPHA_DECAY = 0.018;
const ALPHA_TARGET_DRAG = 0.3;
const PAD = 40;

// ========== 工具函数 ==========

/**
 * 环形初始化：中心节点在中心，引用/被引分别在两侧半环
 */
function circularInit(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.42;

  const center = nodes.find(n => n.type === "center");
  if (center) {
    center.x = cx;
    center.y = cy;
  }

  const citing = nodes.filter(n => n.type === "citing");
  const refs = nodes.filter(n => n.type === "referenced");

  // 引用节点：左半圆 (π/2 → 3π/2)
  citing.forEach((n, i) => {
    const t = citing.length === 1 ? 0.5 : i / (citing.length - 1);
    const angle = Math.PI / 2 + t * Math.PI;
    n.x = cx + radius * Math.cos(angle);
    n.y = cy + radius * Math.sin(angle);
  });

  // 被引节点：右半圆 (-π/2 → π/2)
  refs.forEach((n, i) => {
    const t = refs.length === 1 ? 0.5 : i / (refs.length - 1);
    const angle = -Math.PI / 2 + t * Math.PI;
    n.x = cx + radius * Math.cos(angle);
    n.y = cy + radius * Math.sin(angle);
  });

  // fallback
  nodes.forEach(n => {
    if (n.x == null) {
      n.x = Math.random() * width;
      n.y = Math.random() * height;
    }
  });
}

/**
 * 计算节点半径
 * 注意：d3.scaleSqrt 在 domain 之外会「外推」（被引经典文献引用数可达数万，
 * 直接外推会得到半径 200+ 的巨圆铺满画布），故必须 clamp(true)。
 * 且按「同组内」归一，避免近期论文与经典文献直接对比导致尺寸失真。
 */
function computeRadius(citations, maxCitations, type) {
  if (type === "center") return 24;
  const scale = d3.scaleSqrt()
    .domain([0, Math.max(maxCitations, 1)])
    .range([11, 19])
    .clamp(true);
  return scale(Math.max(0, Number(citations) || 0));
}

/**
 * 缩放分级 —— 标签只在这些离散档位切换，避免每帧重排文本。
 * 0=缩略点 1=年份 2=标题(短) 3=标题(长)
 */
const LABEL_TOP_N = 4;

function labelLevel(k) {
  if (k < 0.3) return 0;
  if (k < 0.8) return 1;
  if (k < 1.5) return 2;
  return 3;
}

/**
 * 按档位决定标签文本。
 * 默认只给「中心 + 各组引用数前列」显示标题——否则每节点都挂长标题会互相重叠；
 * 最大档位（放大后）全部显示。
 */
function labelFor(d, level) {
  if (level === 0) return d.type === "center" ? "●" : "";
  if (level === 1) return d.year ? String(d.year) : "";
  if (d.type !== "center" && level < 3 && (d._rank ?? 99) >= LABEL_TOP_N) {
    return d.year ? String(d.year) : "";
  }
  return truncateLabel(d.fullTitle, level >= 3 ? 36 : 25);
}

/**
 * 按显示宽度安全截断（防止乱码 & 中英文长度不齐）
 * - 用 Array.from 按码点切分，避免 slice 劈开代理对产生孤立代理字符（乱码）
 * - CJK/全角/emoji 按宽度 2 计，英文按 1，避免中文标题被"腰斩"或英文过长
 */
function truncateLabel(title, maxLen = 20) {
  return safeSlice(title, maxLen);
}

function safeSlice(text, maxLen) {
  if (!text) return "";
  const chars = Array.from(String(text));
  if (chars.length <= maxLen) return text;
  const maxWidth = maxLen * 1.7;
  let width = 0;
  let cut = 0;
  for (let i = 0; i < chars.length; i++) {
    const cp = chars[i].codePointAt(0);
    const wide =
      (cp >= 0x1100 && cp <= 0x115f) ||
      (cp >= 0x2e80 && cp <= 0xa4cf) ||
      (cp >= 0xac00 && cp <= 0xd7a3) ||
      (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xfe30 && cp <= 0xfe6f) ||
      (cp >= 0xff00 && cp <= 0xff60) ||
      (cp >= 0xffe0 && cp <= 0xffe6) ||
      (cp >= 0x1f300 && cp <= 0x1faff);
    width += wide ? 2 : 1;
    if (width > maxWidth) break;
    cut = i + 1;
  }
  return cut > 0 && cut < chars.length ? chars.slice(0, cut).join("") + "…" : text;
}

// ========== CitationGraph 类 ==========

export class CitationGraph {
  constructor(svgEl, options = {}) {
    this.svgEl = svgEl;
    this.simulation = null;
    this.nodes = [];
    this.links = [];
    this.currentZoom = 1;
    this._lastLabelLevel = 2;
    this._linkSel = null;
    this._nodeSel = null;
    this._zoom = null;
    this._container = null;
    this.colorMap = options.colorMap || COLOR_MAP;
    this.onNodeClick = options.onNodeClick || null;
    this.onZoomChange = options.onZoomChange || null;
  }

  /**
   * 设置数据并渲染
   */
  setData(data) {
    if (data.nodes && !data.paper) {
      // 通用网络模式（关键词共现 / 作者合作）
      this._buildNetwork(data);
    } else {
      this._buildGraph(data);
    }
    this.render();
  }

  _buildNetwork(data) {
    const rect = this.svgEl.getBoundingClientRect();
    const width = rect.width || 800;
    const height = rect.height || 600;
    const maxCount = Math.max(1, ...data.nodes.map(n => n.count || 1));
    const nodeCount = data.nodes.length;
    const rMin = nodeCount > 50 ? 5 : 8;
    const rMax = nodeCount > 50 ? 22 : 28;

    this.nodes = data.nodes.map((n, i) => ({
      id: n.id,
      label: n.label,
      fullTitle: n.label,
      count: n.count || 1,
      type: "network",
      radius: rMin + (n.count / maxCount) * (rMax - rMin),
    }));
    // ID 映射
    const idMap = {};
    this.nodes.forEach(n => { idMap[n.id] = n; });
    this.links = (data.links || []).map(l => {
      const sId = (l.source && l.source.id) ? l.source.id : String(l.source || "");
      const tId = (l.target && l.target.id) ? l.target.id : String(l.target || "");
      return {
        source: idMap[sId],
        target: idMap[tId],
        type: "network",
        weight: l.weight || 1,
        __sourceId: sId,
        __targetId: tId,
      };
    }).filter(l => l.source && l.target);
    circularInit(this.nodes, width, height);
  }

  /**
   * 构建图数据
   */
  _buildGraph(data) {
    const rect = this.svgEl.getBoundingClientRect();
    const width = rect.width || 800;
    const height = rect.height || 600;

    this.nodes = [];
    this.links = [];

    // 分组归一化：引用侧 / 被引侧各自取组内最大引用数，
    // 避免被引经典文献（数万引用）与近期论文直接对比造成尺寸失真
    const citing = data.citing.slice(0, MAX_CITING);
    const referenced = data.referenced.slice(0, MAX_REFERENCED);
    const maxCiting = Math.max(1, ...citing.map(p => Number(p.citations) || 0));
    const maxReferenced = Math.max(1, ...referenced.map(p => Number(p.citations) || 0));

    // 中心节点
    const center = {
      id: "center",
      fullTitle: data.paper.title,
      doi: data.paper.doi || "",
      year: data.paper.year,
      citations: data.paper.citations,
      type: "center",
      radius: 24,
    };
    this.nodes.push(center);

    // 引用节点
    citing.forEach((p, i) => {
      const node = {
        id: `citing-${i}`,
        fullTitle: p.title,
        doi: p.doi || "",
        year: p.year,
        citations: p.citations,
        type: "citing",
        radius: computeRadius(p.citations, maxCiting, "citing"),
      };
      this.nodes.push(node);
      this.links.push({ source: node, target: center, type: "citing" });
    });

    // 被引节点
    referenced.forEach((p, i) => {
      const node = {
        id: `ref-${i}`,
        fullTitle: p.title,
        doi: p.doi || "",
        year: p.year,
        citations: p.citations,
        type: "referenced",
        radius: computeRadius(p.citations, maxReferenced, "referenced"),
      };
      this.nodes.push(node);
      this.links.push({ source: center, target: node, type: "referenced" });
    });

    // 组内重要度排名（用于决定默认显示哪些标题，避免标签重叠）
    ["citing", "referenced"].forEach(tp => {
      this.nodes
        .filter(n => n.type === tp)
        .sort((a, b) => (Number(b.citations) || 0) - (Number(a.citations) || 0))
        .forEach((n, i) => { n._rank = i; });
    });

    // 环形初始化
    circularInit(this.nodes, width, height);
  }

  /**
   * 渲染图谱
   */
  render() {
    const svgEl = this.svgEl;
    const rect = svgEl.getBoundingClientRect();
    const width = rect.width || 800;
    const height = rect.height || 600;

    // 清理
    if (this.simulation) {
      this.simulation.stop();
      this.simulation = null;
    }
    d3.select(svgEl).on(".zoom", null);
    svgEl.innerHTML = "";

    const svg = d3.select(svgEl);

    // 箭头定义
    const defs = svg.append("defs");
    if (this.colorMap.citing) this._createArrowDef(defs, "arrow-citing", this.colorMap.citing);
    if (this.colorMap.referenced) this._createArrowDef(defs, "arrow-ref", this.colorMap.referenced);

    const container = svg.append("g");
    this._container = container;

    // 缩放
    // - scaleExtent 收敛到 [0.4, 4]：布局本身就适配视口，没必要拉到 15% 或 500%
    // - translateExtent 限制平移范围，避免把图谱拖出屏幕后"找不到"
    // - 反向缩放让节点/标签在屏幕上尺寸大致稳定（见 _applyCounterScale）
    const zoomBehavior = d3.zoom()
      .scaleExtent([0.4, 4])
      .translateExtent([
        [-width * 0.5, -height * 0.5],
        [width * 1.5, height * 1.5],
      ])
      .on("zoom", (e) => {
        const k = e.transform.k;
        container.attr("transform", e.transform);
        this.currentZoom = k;
        this._applyCounterScale(k);
        // 标签文本只在档位切换时重排，避免每帧 setText 造成卡顿
        const lvl = labelLevel(k);
        if (lvl !== this._lastLabelLevel) {
          this._lastLabelLevel = lvl;
          this._updateLabels();
        }
        if (this.onZoomChange) this.onZoomChange(e.transform);
      });
    svg.call(zoomBehavior);
    this._zoom = zoomBehavior;

    // 连线
    const link = container.append("g").selectAll("line")
      .data(this.links, d => `${d.source.id || d.source}-${d.target.id || d.target}`)
      .join("line")
        .attr("class", "graph-link")
        .attr("stroke", d => this.colorMap[d.type])
        .attr("stroke-width", 1.5)
        .attr("marker-end", d => `url(#arrow-${d.type})`);

    // 节点
    const node = container.append("g").selectAll("g")
      .data(this.nodes, d => d.id)
      .join("g")
        .attr("class", d => `graph-node node-${d.type}`)
        .call(d3.drag()
          .on("start", (e, d) => {
            if (!e.active) this.simulation.alphaTarget(ALPHA_TARGET_DRAG).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (e, d) => {
            d.fx = e.x;
            d.fy = e.y;
          })
          .on("end", (e, d) => {
            if (!e.active) this.simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
        );

    // 节点圆形
    node.append("circle")
      .attr("r", d => d.radius)
      .attr("fill", d => this.colorMap[d.type])
      .attr("stroke", "#fff")
      .attr("stroke-width", d => d.type === "center" ? 3 : 2);

    // 标签
    node.append("text")
      .attr("class", "graph-label-text")
      .attr("text-anchor", "middle")
      .attr("dy", d => d.radius + 14)
      .attr("font-size", d => d.type === "center" ? 12 : 10)
      .attr("font-weight", d => d.type === "center" ? 600 : 400)
      .text(d => labelFor(d, 2));

    // 元信息
    node.append("text")
      .attr("class", "graph-meta-text")
      .attr("text-anchor", "middle")
      .attr("dy", d => d.radius + 26)
      .attr("font-size", 9)
      .attr("fill", "#94a3b8")
      .text(d => `${d.year} · ${t("cited")} ${d.citations}`);

    // tooltip
    node.append("title")
      .text(d => `${d.fullTitle}\n${d.year} | ${t("cited")} ${d.citations}`);

    // 点击事件
    node.on("click", (e, d) => {
      e.stopPropagation();
      if (this.onNodeClick) this.onNodeClick(d);
    });

    // hover 高亮
    node.on("mouseenter", (e, d) => {
      const adjacentIds = new Set([d.id]);
      this.links.forEach(l => {
        const sourceId = l.source.id || l.source;
        const targetId = l.target.id || l.target;
        if (sourceId === d.id) adjacentIds.add(targetId);
        if (targetId === d.id) adjacentIds.add(sourceId);
      });
      node.classed("dimmed", n => !adjacentIds.has(n.id));
      node.classed("highlighted", n => adjacentIds.has(n.id) && n.id !== d.id);
      link.classed("dimmed", l => {
        const sourceId = l.source.id || l.source;
        const targetId = l.target.id || l.target;
        return sourceId !== d.id && targetId !== d.id;
      });
    }).on("mouseleave", () => {
      node.classed("dimmed", false).classed("highlighted", false);
      link.classed("dimmed", false);
    });

    // 力模拟
    const linkDist = Math.min(250, Math.max(100, Math.sqrt(width * height / this.nodes.length) * 0.8));

    this.simulation = d3.forceSimulation(this.nodes)
      .force("link", d3.forceLink(this.links).id(d => d.id).distance(linkDist).strength(LINK_STRENGTH))
      .force("charge", d3.forceManyBody().strength(CHARGE_STRENGTH).distanceMax(CHARGE_DISTANCE_MAX))
      .force("x", d3.forceX(width / 2).strength(CENTER_STRENGTH))
      .force("y", d3.forceY(height / 2).strength(CENTER_STRENGTH))
      .force("collide", d3.forceCollide().radius(d => d.radius + COLLIDE_PADDING).strength(1).iterations(6))
      .alphaDecay(ALPHA_DECAY)
      .on("tick", () => {
        this.nodes.forEach(d => {
          d.x = Math.max(PAD, Math.min(width - PAD, d.x));
          d.y = Math.max(PAD, Math.min(height - PAD, d.y));
        });
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("transform", d => `translate(${d.x},${d.y})`);
      });

    // 入场动画
    this._entranceAnimation(node, link);

    // 保存引用
    this._linkSel = link;
    this._nodeSel = node;

    // 初始按 k=1 归一一次，保证与后续缩放后的尺寸口径一致
    this._lastLabelLevel = labelLevel(this.currentZoom);
    this._applyCounterScale(this.currentZoom);
  }

  /**
   * 创建箭头定义
   */
  _createArrowDef(defs, id, color) {
    defs.append("marker")
      .attr("id", id)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 22).attr("refY", 0)
      .attr("markerWidth", 8).attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
        .attr("d", "M0,-4L10,0L0,4")
        .attr("fill", color);
  }

  /**
   * 入场动画
   */
  _entranceAnimation(node, link) {
    // 节点：scale(0) -> scale(1)
    node
      .attr("transform", d => `translate(${d.x},${d.y}) scale(0)`)
      .style("opacity", 0)
      .transition()
      .delay((d, i) => {
        if (d.type === "center") return 0;
        if (d.type === "citing") return 80 + i * 30;
        return 200 + i * 30;
      })
      .duration(400)
      .ease(d3.easeBackOut.overshoot(1.5))
      .attr("transform", d => `translate(${d.x},${d.y}) scale(1)`)
      .style("opacity", 1);

    // 连线绘制动画
    link
      .attr("stroke-dasharray", 200)
      .attr("stroke-dashoffset", 200)
      .transition()
      .delay((d, i) => 200 + i * 20)
      .duration(600)
      .ease(d3.easeCubicOut)
      .attr("stroke-dashoffset", 0);
  }

  /**
   * 反向缩放：缩放时让节点/标签/连线在「屏幕上」的尺寸大致稳定。
   * 否则容器整体放大后节点变巨圆、文字超大，越放大反而看到的内容越少。
   * 用 0.65 次幂做半补偿：既保持可读，又不至于缩小时节点互相糊在一起。
   */
  _applyCounterScale(k) {
    const f = 1 / Math.pow(Math.max(k, 0.01), 0.65);
    const clampMin = (v, min) => Math.max(min, v);
    if (this._nodeSel) {
      this._nodeSel
        .selectAll("circle")
        .attr("r", d => clampMin(d.radius * f, 2.5))
        .attr("stroke-width", d => clampMin((d.type === "center" ? 3 : 2) * f, 0.5));
      const rOf = d => clampMin(d.radius * f, 2.5);
      const off = clampMin(13 * f, 5);
      this._nodeSel
        .selectAll(".graph-label-text")
        .attr("font-size", d => clampMin((d.type === "center" ? 12 : 10) * f, 6.5))
        .attr("dy", d => rOf(d) + off);
      this._nodeSel
        .selectAll(".graph-meta-text")
        .attr("font-size", clampMin(9 * f, 6))
        .attr("dy", d => rOf(d) + off + clampMin(11 * f, 4.5));
    }
    if (this._linkSel) {
      this._linkSel.attr("stroke-width", clampMin(1.5 * f, 0.35));
    }
  }

  /**
   * 更新标签（缩放时）
   */
  _updateLabels() {
    if (!this._nodeSel) return;
    const k = this.currentZoom;
    const lvl = labelLevel(k);
    this._nodeSel.selectAll(".graph-label-text")
      .text(d => labelFor(d, lvl))
      .style("opacity", d => {
        if (d.type === "center") return 1;
        if (this.nodes.length > 40 && k < 0.25) return 0;
        return 1;
      });

    const zoomEl = document.getElementById("graphZoomLevel");
    if (zoomEl) zoomEl.textContent = Math.round(k * 100) + "%";
  }

  /**
   * 获取邻接节点 ID
   */
  getAdjacentIds(nodeId) {
    const adjacent = new Set([nodeId]);
    this.links.forEach(l => {
      const sourceId = l.source.id || l.source;
      const targetId = l.target.id || l.target;
      if (sourceId === nodeId) adjacent.add(targetId);
      if (targetId === nodeId) adjacent.add(sourceId);
    });
    return adjacent;
  }

  /**
   * 重置缩放
   */
  resetZoom() {
    if (this._zoom) {
      d3.select(this.svgEl).transition()
        .duration(300)
        .call(this._zoom.transform, d3.zoomIdentity);
    }
  }

  /**
   * 销毁
   */
  destroy() {
    if (this.simulation) {
      this.simulation.stop();
      this.simulation = null;
    }
    d3.select(this.svgEl).on(".zoom", null);
    this.svgEl.innerHTML = "";
  }
}

// ========== 网络图谱类 ==========

export class NetworkGraph {
  constructor(svgEl, options = {}) {
    this.svgEl = svgEl;
    this.simulation = null;
    this.nodes = [];
    this.links = [];
    this.currentZoom = 1;
    this._linkSel = null;
    this._nodeSel = null;
    this._zoom = null;
    this.nodeColor = options.nodeColor || "#2563eb";
    this.linkColor = options.linkColor || "#94a3b8";
  }

  setData(data) {
    this.nodes = data.nodes || [];
    this.links = data.links || [];
    this.render();
  }

  render() {
    const svgEl = this.svgEl;
    const rect = svgEl.getBoundingClientRect();
    const width = rect.width || 800;
    const height = rect.height || 600;

    if (this.simulation) {
      this.simulation.stop();
      this.simulation = null;
    }
    d3.select(svgEl).on(".zoom", null);
    svgEl.innerHTML = "";

    const svg = d3.select(svgEl);
    const container = svg.append("g");

    const zoomBehavior = d3.zoom()
      .scaleExtent([0.4, 4])
      .wheelDelta((e) => -e.deltaY * 0.002)
      .filter((e) => !e.ctrlKey && e.type !== 'dblclick')
      .on("zoom", (e) => {
        container.attr("transform", e.transform);
        this.currentZoom = e.transform.k;
        this._applyCounterScale(e.transform.k);
        const zoomEl = document.getElementById("graphZoomLevel");
        if (zoomEl) zoomEl.textContent = Math.round(e.transform.k * 100) + "%";
      });
    svg.call(zoomBehavior);
    this._zoom = zoomBehavior;

    // 节点映射
    const nodeMap = {};
    this.nodes.forEach(n => {
      nodeMap[n.id] = n;
      if (n.x == null) n.x = Math.random() * width;
      if (n.y == null) n.y = Math.random() * height;
    });

    // 规范化 link 的 source/target 为字符串 ID（D3 force 会 mutate 为对象引用，需在每次 render 时还原）
    const normalizedLinks = this.links.map(l => {
      const srcId = (l.source && l.source.id) ? l.source.id : String(l.source || "");
      const tgtId = (l.target && l.target.id) ? l.target.id : String(l.target || "");
      return { ...l, source: srcId, target: tgtId, __sourceId: srcId, __targetId: tgtId };
    });
    const validLinks = normalizedLinks.filter(l => nodeMap[l.__sourceId] && nodeMap[l.__targetId]);

    // 半径缩放 — 大数据集时缩小节点范围避免拥挤
    const maxCount = Math.max(1, ...this.nodes.map(n => n.count || 1));
    const nodeCount = this.nodes.length;
    const rMin = nodeCount > 50 ? 5 : nodeCount > 30 ? 6 : 8;
    const rMax = nodeCount > 50 ? 18 : nodeCount > 30 ? 22 : 24;
    const radiusScale = d3.scaleSqrt().domain([1, maxCount]).range([rMin, rMax]);

    // 连线
    const maxWeight = Math.max(1, ...validLinks.map(l => l.weight || 1));
    const linkScale = d3.scaleLinear().domain([1, maxWeight]).range([0.8, 3]);
    const link = container.append("g").selectAll("line")
      .data(validLinks).join("line")
        .attr("stroke", this.linkColor)
        .attr("stroke-opacity", d => nodeCount > 30 ? 0.35 : 0.6)
        .attr("stroke-width", d => { d._w = linkScale(d.weight || 1); return d._w; });

    // 节点
    const maxLabelLen = width < 500 ? 8 : width < 800 ? 14 : 20;
    const node = container.append("g").selectAll("g")
      .data(this.nodes).join("g")
        .attr("class", "graph-node")
        .call(d3.drag()
          .on("start", (e, d) => {
            if (!e.active) this.simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (e, d) => {
            d.fx = e.x;
            d.fy = e.y;
          })
          .on("end", (e, d) => {
            if (!e.active) this.simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
        );

    node.append("circle")
      .attr("r", d => { d._r = radiusScale(d.count || 1); return d._r; })
      .attr("fill", this.nodeColor)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2);

    // 大数据集只显示前 25 个最重要节点的标签，避免拥挤
    const showAllLabels = nodeCount <= 25;
    if (!showAllLabels) {
      const topIds = new Set(this.nodes.slice().sort((a,b)=>(b.count||0)-(a.count||0)).slice(0,25).map(n=>n.id));
      this.nodes.forEach(n => { n._showLabel = topIds.has(n.id); });
    } else { this.nodes.forEach(n => { n._showLabel = true; }); }

    this._baseFont = nodeCount > 30 ? 9 : 11;
    this._baseMetaFont = nodeCount > 30 ? 8 : 9;

    node.append("text")
      .attr("class", "graph-label-text")
      .attr("text-anchor", "middle")
      .attr("dy", d => radiusScale(d.count || 1) + 16)
      .attr("font-size", this._baseFont)
      .attr("font-weight", 500)
      .attr("opacity", d => d._showLabel ? 1 : 0)
      .text(d => d._showLabel ? safeSlice(d.label, maxLabelLen) : "");

    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", d => radiusScale(d.count || 1) + 28)
      .attr("font-size", this._baseMetaFont)
      .attr("fill", "#94a3b8")
      .attr("opacity", d => d._showLabel ? 1 : 0)
      .text(d => d._showLabel ? `× ${d.count || 1}` : "");

    node.append("title").text(d => `${d.label}: ${d.count || 1}`);

    // hover
    node.on("mouseenter", (e, d) => {
      const adjacentIds = new Set([d.id]);
      validLinks.forEach(l => {
        if (l.__sourceId === d.id) adjacentIds.add(l.__targetId);
        if (l.__targetId === d.id) adjacentIds.add(l.__sourceId);
      });
      node.classed("dimmed", n => !adjacentIds.has(n.id));
      node.classed("highlighted", n => adjacentIds.has(n.id) && n.id !== d.id);
      link.classed("dimmed", l => l.__sourceId !== d.id && l.__targetId !== d.id);
    }).on("mouseleave", () => {
      node.classed("dimmed", false).classed("highlighted", false);
      link.classed("dimmed", false);
    });

    // 力模拟
    const netNodeCount = this.nodes.length;
    const netChargeStrength = Math.min(-900, -25 * netNodeCount);
    const netLinkDist = Math.min(240, Math.max(100, Math.sqrt(width * height / netNodeCount) * 0.7));
    const pad = 50;

    this.simulation = d3.forceSimulation(this.nodes)
      .force("link", d3.forceLink(validLinks).id(d => d.id).distance(netLinkDist).strength(0.5))
      .force("charge", d3.forceManyBody().strength(netChargeStrength))
      .force("x", d3.forceX(width / 2).strength(0.1))
      .force("y", d3.forceY(height / 2).strength(0.1))
      .force("collide", d3.forceCollide().radius(d => radiusScale(d.count || 1) + 50).strength(1).iterations(6))
      .alphaDecay(0.015)
      .on("tick", () => {
        this.nodes.forEach(d => {
          d.x = Math.max(pad, Math.min(width - pad, d.x));
          d.y = Math.max(pad, Math.min(height - pad, d.y));
        });
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("transform", d => `translate(${d.x},${d.y})`);
      });

    // 入场动画
    node
      .attr("transform", d => `translate(${d.x},${d.y}) scale(0)`)
      .style("opacity", 0)
      .transition()
      .delay((d, i) => i * 30)
      .duration(400)
      .ease(d3.easeBackOut.overshoot(1.5))
      .attr("transform", d => `translate(${d.x},${d.y}) scale(1)`)
      .style("opacity", 1);

    link
      .attr("stroke-dasharray", 200)
      .attr("stroke-dashoffset", 200)
      .transition()
      .delay((d, i) => 200 + i * 20)
      .duration(600)
      .ease(d3.easeCubicOut)
      .attr("stroke-dashoffset", 0);

    this._linkSel = link;
    this._nodeSel = node;
    this._applyCounterScale(this.currentZoom);
  }

  /**
   * 反向缩放：缩放时保持节点/标签/连线在屏幕上的视觉尺寸大致稳定，
   * 避免放大后节点变巨圆、文字超大（越放大越看不全）。
   */
  _applyCounterScale(k) {
    const f = 1 / Math.pow(Math.max(k, 0.01), 0.65);
    const mn = (v, m) => Math.max(m, v);
    if (this._nodeSel) {
      const rOf = d => mn((d._r || 8) * f, 2);
      this._nodeSel
        .selectAll("circle")
        .attr("r", rOf)
        .attr("stroke-width", mn(2 * f, 0.5));
      this._nodeSel
        .selectAll(".graph-label-text")
        .attr("font-size", mn((this._baseFont || 10) * f, 6.5))
        .attr("dy", d => rOf(d) + mn(16 * f, 6));
      this._nodeSel
        .selectAll("text:not(.graph-label-text)")
        .attr("font-size", mn((this._baseMetaFont || 9) * f, 6))
        .attr("dy", d => rOf(d) + mn(28 * f, 10));
    }
    if (this._linkSel) {
      this._linkSel.attr("stroke-width", d => mn((d._w || 1) * f, 0.3));
    }
  }

  resetZoom() {
    if (this._zoom) {
      d3.select(this.svgEl).transition()
        .duration(300)
        .call(this._zoom.transform, d3.zoomIdentity);
    }
  }

  destroy() {
    if (this.simulation) {
      this.simulation.stop();
      this.simulation = null;
    }
    d3.select(this.svgEl).on(".zoom", null);
    this.svgEl.innerHTML = "";
  }
}

// ========== 导出到 window ==========

window.CitationGraph = CitationGraph;
window.NetworkGraph = NetworkGraph;

// ========== 共现网络图 V2（关键词共现 / 作者合作）==========
// 设计原则与引用谱系图一致：
//   1) 确定性布局先算锚点（环形/同心/聚类），力导向只做微调 —— 静止时整洁可预测；
//   2) 锚定物理提供拖拽灵动感，松手弹回锚点；
//   3) 缩放为纯等比（像缩放 PDF），不做反向补偿 —— 越放大越看得清。

const NET_PALETTE = ["#007AFF", "#34C759", "#FF9F0A", "#AF52DE", "#FF3B30", "#5AC8FA", "#FF9500", "#5856D6"];
const NET_LABEL_BUDGET = 36;   // 最多同时显示的节点标签数（超出者悬停显示）

/**
 * 社区发现：加权标签传播（LPA）。
 * 为什么不用连通分量：真实学术合作网络几乎总是「全连通」—— 只要有一个跨机构的
 * 合作者，整个网络就会被串成一个连通分量，聚类永远只有 1 组，毫无信息量。
 * 加权 LPA 按「共现 / 合作紧密度」切分，才能还原出真正的主题簇 / 合作圈子。
 *
 * 确定性保证：节点遍历顺序固定（频次降序、同频按 id），偶数轮逆序；平局保留原标签。
 * 同一份数据每次得到完全相同的分组 —— 布局可预测，这是本图谱的设计底线。
 */
function detectNetCommunities(nodes, links, maxIter = 15) {
  // 先剪枝：只保留强度 ≥ 中位数的边。
  // 密集图（关键词共现尤甚）里几乎所有节点都互相连接，直接跑 LPA 每次投票都会
  // 被扁平化，最终退化成「1 组」——看似正确，实则零信息量。
  let use = links;
  if (links.length > 6) {
    const ws = links.map(l => l.w).sort((a, b) => a - b);
    const med = ws[Math.floor(ws.length / 2)];
    const kept = links.filter(l => l.w >= med);
    if (kept.length >= 3) use = kept;
  }

  const fill = (map, ls) => ls.forEach(l => {
    if (!map.has(l.s) || !map.has(l.t)) return;
    const a = map.get(l.s), b = map.get(l.t);
    a.set(l.t, (a.get(l.t) || 0) + l.w);
    b.set(l.s, (b.get(l.s) || 0) + l.w);
  });
  const adj = new Map(nodes.map(n => [n.id, new Map()]));
  fill(adj, use);
  // 未剪枝的完整邻接表。剪枝会把「每条边都低于中位数」的节点变成孤岛
  // （例：关键词 denoising，它的所有边全被判为弱边），此时必须回到完整图里
  // 找它真正的「最强邻居」并合并过去，否则图上会凭空多出一个单节点簇。
  const fullAdj = new Map(nodes.map(n => [n.id, new Map()]));
  fill(fullAdj, links);

  const label = new Map(nodes.map(n => [n.id, n.id]));
  const order = nodes.slice()
    .sort((a, b) => (b.count || 0) - (a.count || 0) || (a.id < b.id ? -1 : 1))
    .map(n => n.id);

  for (let it = 0; it < maxIter; it++) {
    let changed = false;
    const seq = (it % 2 === 1) ? order.slice().reverse() : order;
    for (const id of seq) {
      const score = new Map();
      for (const [nb, w] of adj.get(id)) {
        const lb = label.get(nb);
        score.set(lb, (score.get(lb) || 0) + w);
      }
      if (!score.size) continue;
      let best = label.get(id), bestV = -1;
      if (score.has(best)) bestV = score.get(best);
      for (const [lb, v] of score) {
        if (v > bestV) { best = lb; bestV = v; }
      }
      if (best !== label.get(id)) { label.set(id, best); changed = true; }
    }
    if (!changed) break;
  }

  // 后处理：把单元素组并入「连接最强」的邻居所在组（用完整邻接表）
  for (let guard = 0; guard < 20; guard++) {
    const size = new Map();
    label.forEach(lb => size.set(lb, (size.get(lb) || 0) + 1));
    let merged = false;
    for (const n of nodes) {
      const id = n.id, lb = label.get(id);
      if ((size.get(lb) || 0) > 1) continue;
      let best = null, bestW = 0;
      for (const [nb, w] of fullAdj.get(id)) {
        if (w > bestW) { bestW = w; best = label.get(nb); }
      }
      if (best && best !== lb) { label.set(id, best); merged = true; }
    }
    if (!merged) break;
  }

  // 重新编号：按组大小降序，组内按频次降序
  const buckets = new Map();
  nodes.forEach(n => {
    const lb = label.get(n.id);
    if (!buckets.has(lb)) buckets.set(lb, []);
    buckets.get(lb).push(n);
  });
  const groups = [...buckets.values()]
    .map(g => g.sort((a, b) => (b.count || 0) - (a.count || 0)).map(n => n.id))
    .sort((a, b) => b.length - a.length);
  const comp = new Map();
  groups.forEach((g, i) => g.forEach(id => comp.set(id, i)));
  return { comp, groups };
}

export class NetworkGraphV2 {
  /**
   * @param {SVGElement} svgEl
   * @param {Object} options { type: 'keyword'|'author', mode, top }
   */
  constructor(svgEl, options = {}) {
    this.svgEl = svgEl;
    this.type = options.type || "keyword";
    this.state = { mode: options.mode || "circular", top: options.top ?? 10, pinned: null };
    this.sim = null;
    this.zoom = null;
    this.nodes = [];
    this.links = [];
    this.overflow = 0;
    this.tipEl = null;
  }

  /** 后端格式：{nodes:[{id,label,count}], links:[{source,target,weight}]} */
  setData(data) {
    this.nodes = (data.nodes || []).map(n => ({ ...n }));
    this.links = (data.links || []).map(l => ({
      s: (l.source && l.source.id) ? l.source.id : String(l.source || ""),
      t: (l.target && l.target.id) ? l.target.id : String(l.target || ""),
      w: l.weight || 1,
    }));
    this.render();
  }

  setMode(mode) { this.state.mode = mode; this.render(); }
  setTop(n) { this.state.top = n; this.render(); }
  fit() {
    if (this.zoom) {
      d3.select(this.svgEl).transition().duration(320).call(this.zoom.transform, d3.zoomIdentity);
    }
  }

  destroy() {
    if (this.sim) { this.sim.stop(); this.sim = null; }
    d3.select(this.svgEl).on(".zoom", null);
    this.svgEl.innerHTML = "";
    if (this.tipEl) { this.tipEl.remove(); this.tipEl = null; }
  }

  /* ---- 数据切片：按 count 取 Top N ---- */
  _slice() {
    let nodes = this.nodes.slice().sort((a, b) => (b.count || 0) - (a.count || 0));
    this.overflow = 0;
    if (this.state.top > 0 && nodes.length > this.state.top) {
      this.overflow = nodes.length - this.state.top;
      nodes = nodes.slice(0, this.state.top);
    }
    const ids = new Set(nodes.map(n => n.id));
    const links = this.links.filter(l => ids.has(l.s) && ids.has(l.t) && l.s !== l.t);
    return { nodes: nodes.map(n => ({ ...n })), links };
  }

  /* ---- 锚点布局：三种排列，产出 (ax, ay) + 径向标签参考中心 (cx, cy) ---- */
  _layout(nodes, links, W, H) {
    const cx0 = W / 2, cy0 = H / 2;

    // 环形：同簇的节点排在一起 —— 否则同一主题的词被频次打散，看不出簇边界
    if (this.state.mode === "circular") {
      const maxR = Math.max(...nodes.map(n => n.r || 8));
      const R = Math.min(W / 2, H / 2) - maxR - 34;
      const order = nodes.slice().sort((a, b) =>
        (a.comp || 0) - (b.comp || 0) || (b.count || 0) - (a.count || 0));
      order.forEach((n, i) => {
        const a = -Math.PI / 2 + (i / order.length) * Math.PI * 2;
        n.ax = cx0 + Math.cos(a) * R;
        n.ay = cy0 + Math.sin(a) * R;
        n.cx = cx0; n.cy = cy0;
      });
      return { labels: [], ringRadii: [] };
    }

    // 同心：按 count 分 3 层，高频在内圈（同层内同簇相邻）
    if (this.state.mode === "concentric") {
      const sorted = nodes.slice().sort((a, b) =>
        (b.count || 0) - (a.count || 0) || (a.comp || 0) - (b.comp || 0));
      const span = Math.min(W / 2, H / 2) - Math.max(...nodes.map(n => n.r || 8)) - 30;
      const rings = [{ r: span * 0.42 }, { r: span * 0.72 }, { r: span }];
      // 按各层周长比例分配节点数，使密度均匀 —— 三层周长差 2.4 倍，若都放同样多的
      // 节点，内圈会挤成一团、外圈则稀稀拉拉。排序不变，「越靠内圈频次越高」仍成立。
      const csum = rings.reduce((a, r) => a + r.r, 0);
      let acc = 0, prev = 0;
      rings.forEach((ring, i) => {
        acc += ring.r;
        ring.from = prev;
        ring.to = (i === rings.length - 1) ? sorted.length
                                          : Math.max(prev, Math.round(sorted.length * acc / csum));
        prev = ring.to;
      });
      rings.forEach((ring, ri) => {
        const group = sorted.slice(ring.from, ring.to);
        // 层间角度错开。若每层都从正上方 -90° 起算，节点会沿径向对齐成一条竖线
        // （实测 2/4/4 分层时，三层的「正上方」全落在 x = 中心 的直线上）。
        const off = ri * (Math.PI * 2 / (rings.length * 2));
        group.forEach((nd, i) => {
          const a = -Math.PI / 2 + off + (i / Math.max(1, group.length)) * Math.PI * 2;
          nd.ax = cx0 + Math.cos(a) * ring.r;
          nd.ay = cy0 + Math.sin(a) * ring.r;
          nd.cx = cx0; nd.cy = cy0;
        });
      });
      // 把分层半径交出去画参考圆 —— 少了它，「同心」看起来只是一堆散点
      return { labels: [], ringRadii: rings.map(r => r.r) };
    }

    // 聚类：加权社区发现分组，每簇占一个网格单元，簇内自适应小圆环
    const { comp, groups } = detectNetCommunities(nodes, links);
    nodes.forEach(n => { n.comp = comp.get(n.id) || 0; });
    const cols = Math.ceil(Math.sqrt(groups.length));
    const rows = Math.ceil(groups.length / cols);
    const cellW = W / cols, cellH = H / rows;
    const labels = [];
    const byId = new Map(nodes.map(n => [n.id, n]));

    groups.forEach((ids, ci) => {
      const col = ci % cols, row = Math.floor(ci / cols);
      const ccx = cellW * (col + 0.5);
      const ccy = cellH * (row + 0.5);
      // 自适应半径：环上相邻节点不重叠。
      // n 个节点均布时最小弦长在角距 2π/n 处：2R·sin(π/n) ≥ r_i + r_j，
      // 取最坏情况（两个最大圆相邻）⇒ R ≥ maxR / sin(π/n)。
      const members = ids.map(id => byId.get(id)).filter(Boolean);
      const n = members.length;
      const maxR = members.reduce((m, x) => Math.max(m, x.r || 8), 0);
      const need = n > 1 ? (maxR / Math.sin(Math.PI / n)) * 1.08 : 0;
      const minCell = Math.min(cellW, cellH);
      const cap = minCell / 2 - 58;                 // 给径向朝外的标题/标签留位
      const R = n > 1 ? Math.min(Math.max(need, minCell * 0.26), Math.max(24, cap)) : 0;

      members.forEach((nd, i) => {
        const a = -Math.PI / 2 + (i / Math.max(1, n)) * Math.PI * 2;
        nd.ax = ccx + Math.cos(a) * R;
        nd.ay = ccy + Math.sin(a) * R;
        nd.cx = ccx; nd.cy = ccy;
      });

      const tag = this.type === "keyword" ? t("netTopic") : t("netGroup");
      const unit = this.type === "keyword" ? t("netWordUnit") : t("netPersonUnit");
      labels.push({
        // 贴格子顶部而不是相对节点圆 —— 否则 R 一变就可能压到朝外的节点标签上
        x: ccx, y: ccy - cellH / 2 + 14,
        text: `${tag} ${ci + 1} · ${n} ${unit}`,
        comp: ci,
      });
    });
    return { labels, ringRadii: [] };
  }

  render() {
    const svgEl = this.svgEl;
    const rect = svgEl.getBoundingClientRect();
    const W = Math.max(320, rect.width || 800);
    const H = Math.max(320, rect.height || 600);

    if (this.sim) { this.sim.stop(); this.sim = null; }
    d3.select(svgEl).on(".zoom", null);
    svgEl.innerHTML = "";
    if (this.tipEl) { this.tipEl.remove(); this.tipEl = null; }

    const { nodes, links } = this._slice();

    // 半径（clamp 防外推）
    const maxCount = Math.max(1, ...nodes.map(n => n.count || 1));
    const rScale = d3.scaleSqrt().domain([1, maxCount]).range([8, 24]).clamp(true);
    nodes.forEach(n => { n.r = rScale(n.count || 1); });

    // 无论何种排列，都按社区着色 —— 对作者图是「圈子」，对关键词图是「主题簇」
    const { comp } = detectNetCommunities(nodes, links);
    nodes.forEach(n => { n.comp = comp.get(n.id) || 0; });

    const { labels: clusterLabels, ringRadii } = this._layout(nodes, links, W, H);

    const maxW = Math.max(1, ...links.map(l => l.w));
    const wScale = d3.scaleLinear().domain([1, maxW]).range([0.8, 4]).clamp(true);
    const colorOf = n => NET_PALETTE[(n.comp || 0) % NET_PALETTE.length];

    const svg = d3.select(svgEl);
    const root = svg.append("g").attr("class", "net-root");
    const gR = root.append("g").attr("class", "g-rings");
    const gL = root.append("g").attr("class", "g-links");
    const gC = root.append("g").attr("class", "g-clusters");
    const gN = root.append("g").attr("class", "g-nodes");

    const zoom = d3.zoom()
      .scaleExtent([0.5, 3.5])
      .translateExtent([[-220, -160], [W + 220, H + 160]])
      .filter(ev => !ev.ctrlKey && ev.type !== "dblclick")
      .on("zoom", ev => {
        root.attr("transform", ev.transform);
        const z = document.getElementById("graphZoomLevel");
        if (z) z.textContent = Math.round(ev.transform.k * 100) + "%";
      });
    svg.call(zoom)
      .on("dblclick.zoom", null)
      .on("mousedown.netcursor", () => svgEl.classList.add("grabbing"))
      .on("mouseup.netcursor", () => svgEl.classList.remove("grabbing"));
    this.zoom = zoom;

    // 同心分层参考圆
    gR.selectAll("circle").data(ringRadii).join("circle")
      .attr("class", "net-ring")
      .attr("cx", W / 2).attr("cy", H / 2)
      .attr("r", d => d);

    // 聚类标题
    gC.selectAll("text").data(clusterLabels).join("text")
      .attr("class", "net-clab")
      .attr("text-anchor", "middle")
      .attr("x", d => d.x).attr("y", d => d.y)
      .text(d => this.state.mode === "cluster" ? d.text : "");

    // 连线。跨簇关系单独标记：共现网络里「跨主题/跨机构」的那几条边往往才是
    // 新发现，若和簇内边同样淡，等于把最有价值的信息藏了起来。
    const byId = new Map(nodes.map(n => [n.id, n]));
    const isCross = d => {
      const a = byId.get(d.s), b = byId.get(d.t);
      return a && b && (a.comp || 0) !== (b.comp || 0);
    };
    const baseOpacity = d => isCross(d) ? 0.45 : 0.13 + 0.34 * (d.w / maxW);
    const link = gL.selectAll("line")
      .data(links.filter(l => byId.has(l.s) && byId.has(l.t)))
      .join("line")
        .attr("class", d => isCross(d) ? "net-lnk cross" : "net-lnk")
        .attr("stroke", d => isCross(d) ? "#007AFF" : "var(--text-tertiary)")
        .attr("stroke-opacity", baseOpacity)
        .attr("stroke-width", d => isCross(d) ? 1.1 : wScale(d.w));

    // 节点 + 径向朝外标签（结构上不可能与同圈邻居重叠）
    const node = gN.selectAll("g.net-nd").data(nodes, d => d.id).join(
      enter => {
        const g = enter.append("g").attr("class", "net-nd")
          .attr("transform", d => `translate(${d.ax},${d.ay}) scale(0)`);
        g.append("circle").attr("class", "net-body");
        g.append("text").attr("class", "net-lbl");
        g.append("text").attr("class", "net-cnt");
        return g;
      }
    );

    node.select("circle.net-body")
      .attr("r", d => d.r)
      .attr("fill", d => colorOf(d))
      .attr("fill-opacity", d => 0.58 + 0.36 * ((d.count || 1) / maxCount))
      .attr("stroke", "var(--bg-elevated)").attr("stroke-width", 2);

    const radial = (d, dist) => {
      const dx = d.ax - d.cx, dy = d.ay - d.cy;
      const len = Math.hypot(dx, dy) || 1;
      return { x: (dx / len) * dist, y: (dy / len) * dist };
    };
    // 标签预算：节点多时外圈周长装不下所有标签（120 节点时约 72 个挤在最外层），
    // 只显示频次前 NET_LABEL_BUDGET 的标签，其余悬停该节点时临时显示。
    const labelOk = new Set(
      nodes.slice().sort((a, b) => (b.count || 0) - (a.count || 0))
        .slice(0, NET_LABEL_BUDGET).map(n => n.id)
    );
    node.select("text.net-lbl")
      .attr("text-anchor", d => (d.ax >= d.cx ? "start" : "end"))
      .attr("x", d => radial(d, d.r + 7).x)
      .attr("y", d => radial(d, d.r + 7).y + 4)
      .style("opacity", d => labelOk.has(d.id) ? 1 : 0)
      .text(d => safeSlice(d.label, 22));
    node.select("text.net-cnt")
      // 频次放在圆内居中（气泡图惯例）：径向朝外的第二行在大 r 时会算进圆内
      // （y = -(r+7)+16 = -15 < 0），与圆重叠。小圆放不下就不显示 —— tooltip 里有。
      .attr("text-anchor", "middle")
      .attr("x", 0)
      .attr("y", 4)
      .style("fill", "rgba(255,255,255,0.92)")
      .style("font-size", "10px")
      .text(d => (d.r >= 13) ? String(d.count || 1) : "");

    // Tooltip（挂在 graph-body 内）
    const bodyEl = svgEl.parentElement;
    const tip = document.createElement("div");
    tip.className = "net-tip";
    (bodyEl || document.body).appendChild(tip);
    this.tipEl = tip;

    // 拖拽：跟手，松手弹回锚点
    node.call(d3.drag()
      .on("start", (e, d) => { if (this.sim) this.sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => { if (this.sim) this.sim.alphaTarget(0); d.fx = null; d.fy = null; })
    );

    // 悬停高亮邻居 / 点击锁定
    const neighborsOf = id => {
      const s = new Set([id]);
      links.forEach(l => {
        if (l.s === id) s.add(l.t);
        if (l.t === id) s.add(l.s);
      });
      return s;
    };
    const highlight = id => {
      const nb = neighborsOf(id);
      node.attr("opacity", d => nb.has(d.id) ? 1 : 0.16);
      link.attr("stroke-opacity", d => (d.s === id || d.t === id) ? 0.9 : 0.06);
    };
    const clearHighlight = () => {
      node.attr("opacity", 1);
      link.attr("stroke-opacity", baseOpacity);
      node.select("text.net-lbl").style("opacity", d => labelOk.has(d.id) ? 1 : 0);
    };
    node.on("mouseenter", (e, d) => {
      highlight(d.id);
      // 预算外的节点悬停时临时显示自己的标签
      d3.select(e.currentTarget).select("text.net-lbl").style("opacity", 1);
    })
      .on("mousemove", (e, d) => this._showTip(e, d, bodyEl, tip))
      .on("mouseleave", () => { if (!this.state.pinned) clearHighlight(); tip.classList.remove("on"); })
      .on("click", (e, d) => {
        e.stopPropagation();
        this.state.pinned = (this.state.pinned === d.id) ? null : d.id;
        if (this.state.pinned) highlight(d.id); else clearHighlight();
      });
    svg.on("click.netpin", () => { this.state.pinned = null; clearHighlight(); });

    // 入场动画
    node.transition().delay((d, i) => i * 22).duration(420)
      .ease(d3.easeBackOut.overshoot(1.4))
      .attr("transform", d => `translate(${d.ax},${d.ay}) scale(1)`);

    // 锚定物理：弹簧拉向锚点 + 碰撞（半径按节点算，不能用标签宽 —— 会与锚点力打架）
    this.sim = d3.forceSimulation(nodes)
      .force("x", d3.forceX(d => d.ax).strength(0.4))
      .force("y", d3.forceY(d => d.ay).strength(0.4))
      .force("charge", d3.forceManyBody().strength(-45))
      .force("collide", d3.forceCollide(d => d.r + 9).strength(0.95).iterations(3))
      .alpha(0.9).alphaDecay(0.045)
      .on("tick", () => {
        link.attr("x1", d => byId.get(d.s).x).attr("y1", d => byId.get(d.s).y)
            .attr("x2", d => byId.get(d.t).x).attr("y2", d => byId.get(d.t).y);
        node.attr("transform", d => `translate(${d.x},${d.y})`);
      });

    this._updateLegend(nodes);
    this._updateMeta(nodes, links, clusterLabels.length);
  }

  _showTip(e, d, bodyEl, tip) {
    const rel = this.links
      .filter(l => l.s === d.id || l.t === d.id)
      .map(l => ({ o: l.s === d.id ? l.t : l.s, w: l.w }))
      .sort((a, b) => b.w - a.w).slice(0, 5);
    const cnt = t(this.type === "keyword" ? "netAppearCount" : "netPubCount")
      .replace("{n}", d.count || 1);
    const nbCount = this.links.filter(l => l.s === d.id || l.t === d.id).length;
    const nbTxt = t("netNeighborCount").replace("{n}", nbCount);
    const topTxt = t(this.type === "keyword" ? "netTopCooccur" : "netTopCoop");
    tip.innerHTML =
      `<div style="font-weight:600;margin-bottom:3px">${escapeHtml(d.label)}</div>` +
      `<div class="m">${cnt} · ${nbTxt}</div>` +
      (rel.length
        ? `<div class="m" style="margin-top:5px">${topTxt}：</div>` +
          rel.map(r => `<div class="m">· ${escapeHtml(safeSlice(r.o, 26))} × ${r.w}</div>`).join("")
        : "");
    const rect = this.svgEl.getBoundingClientRect();
    tip.style.left = (e.clientX - rect.left + 14) + "px";
    tip.style.top = (e.clientY - rect.top + 14) + "px";
    tip.classList.add("on");
  }

  _updateLegend(nodes) {
    const row = document.getElementById("legendClustersRow");
    if (!row) return;
    const n = new Set(nodes.map(d => d.comp || 0)).size;
    if (n <= 1) { row.style.display = "none"; row.innerHTML = ""; return; }
    const unit = this.type === "keyword" ? t("netTopic") : t("netGroup");
    row.style.display = "flex";
    row.innerHTML = Array.from({ length: Math.min(n, NET_PALETTE.length) }, (_, i) =>
      `<span class="lc-item"><span class="lc-dot" style="background:${NET_PALETTE[i]}"></span>${unit} ${i + 1}</span>`
    ).join("");
  }

  _updateMeta(nodes, links, nClusters) {
    const modeName = t({ circular: "netModeCircular", concentric: "netModeConcentric", cluster: "netModeCluster" }[this.state.mode]);
    let m = `${nodes.length} ${t("netNodeUnit")} · ${links.length} ${t("netLinkUnit")} · ${modeName}`;
    if (this.state.mode === "cluster") {
      m += ` · ${nClusters} ${this.type === "keyword" ? t("netTopic") : t("netGroup")}`;
    }
    if (this.overflow > 0) m += ` · ${t("netOverflow").replace("{n}", this.overflow)}`;
    const el = document.getElementById("legendCenter");
    if (el) el.textContent = m;
  }
}

window.NetworkGraphV2 = NetworkGraphV2;

// ========== 引用谱系图 V2（三栏谱系 + 数量/排列控件）==========
// 与原型 graph-hybrid.html 一致的设计：
//   左栏=被引文献（此论文引用的）/ 中心=当前论文 / 右栏=引用文献（引用此论文的）
//   - 确定性三栏布局产出锚点，锚定物理提供拖拽灵动感，松手弹回
//   - 缩放为纯等比（像缩放 PDF）——「看不清」交给缩放，「装不下」交给数量/排列
//   - 数量：Top 10 / Top 20 / 全部；排列：平铺 / 年份分段 / 聚类（年份气泡可展开）

const CIT_LABEL_BUDGET = 999;   // 三栏布局行距由 rowH 自适应，标签天然不重叠，无需预算

export class CitationGraphV2 {
  /**
   * @param {SVGElement} svgEl
   * @param {Object} options { onNodeClick(d), mode, limit }
   */
  constructor(svgEl, options = {}) {
    this.svgEl = svgEl;
    this.onNodeClick = options.onNodeClick || null;
    this.state = { limit: options.limit || "all", arrange: options.mode || "flat" };
    this.data = null;
    this.expandedYears = new Set();
    this.sim = null;
    this.zoom = null;
    this.tipEl = null;
    this.nodes = [];
    this.links = [];
    this.hiddenL = [];
    this.hiddenR = [];
  }

  /** 后端格式：{paper:{title,doi,year,citations}, citing:[], referenced:[]} */
  setData(data) {
    this.data = data;
    this.render(true);
  }

  setLimit(v) { this.state.limit = v; this.render(true); }
  setArrange(v) { this.state.arrange = v; this.expandedYears.clear(); this.render(true); }
  reset() { this.render(true); }          // 重排（重新播放入场动画）
  fit() {
    if (this.zoom) {
      d3.select(this.svgEl).transition().duration(320).call(this.zoom.transform, d3.zoomIdentity);
    }
  }
  resetZoom() { this.fit(); }

  destroy() {
    if (this.sim) { this.sim.stop(); this.sim = null; }
    d3.select(this.svgEl).on(".zoom", null).on("dblclick.cit", null);
    this.svgEl.innerHTML = "";
    if (this.tipEl) { this.tipEl.remove(); this.tipEl = null; }
  }

  /* ---- 数量策略：按被引降序取 Top N ---- */
  _pick(list) {
    const sorted = list.slice().sort((a, b) => (Number(b.citations) || 0) - (Number(a.citations) || 0));
    if (this.state.limit === "all") return { show: sorted, hidden: [] };
    const n = parseInt(this.state.limit, 10);
    return { show: sorted.slice(0, n), hidden: sorted.slice(n) };
  }

  /* ---- 排列策略：平铺 / 年份分段 / 聚类（聚类=年份折叠气泡） ---- */
  _entries(list) {
    if (this.state.arrange === "flat") {
      return list.slice().sort((a, b) => (Number(b.year) || 0) - (Number(a.year) || 0))
        .map(d => ({ type: "node", d }));
    }
    const groups = [];
    list.slice().sort((a, b) => (Number(b.year) || 0) - (Number(a.year) || 0)).forEach(d => {
      const y = d.year || 0;
      const g = groups.find(x => x.year === y);
      if (g) g.items.push(d); else groups.push({ year: y, items: [d] });
    });
    const entries = [];
    groups.forEach((g, gi) => {
      if (gi > 0) entries.push({ type: "gap" });
      const collapsed = this.state.arrange === "cluster" && g.items.length > 1
        && !this.expandedYears.has(g.year);
      if (collapsed) entries.push({ type: "cluster", year: g.year, items: g.items });
      else g.items.forEach(d => entries.push({ type: "node", d }));
    });
    return entries;
  }

  /* ---- 三栏定位（原型 metricsOf/layoutSide 的移植，尺寸动态） ---- */
  _layoutSide(list, side, W, H) {
    const PAD_T = 54, PAD_B = 40;
    const COL_L = W * 0.305, COL_R = W * 0.695;
    const LABEL_MAX = W * 0.235;
    const YEAR_GAP = 20;
    const entries = this._entries(list);
    const availH = H - PAD_T - PAD_B;
    const gaps = entries.filter(e => e.type === "gap").length;
    const rows = entries.length - gaps;
    const rowH = Math.min(46, Math.max(17, (availH - gaps * YEAR_GAP) / Math.max(rows, 1)));
    const totalH = rows * rowH + gaps * YEAR_GAP;
    const m = { availH, gaps, rows, rowH, totalH, startY: PAD_T + Math.max(0, (availH - totalH) / 2) };

    const fs = m.rowH < 26 ? 11 : 12;
    const maxC = Math.max(1, ...list.map(d => Number(d.citations) || 0));
    const maxR = Math.max(4.5, Math.min(15, m.rowH * 0.33));
    const colX = side === "left" ? COL_L : COL_R;
    const out = [];
    let y = m.startY;

    entries.forEach(e => {
      if (e.type === "gap") { y += YEAR_GAP; return; }
      const ay = y + m.rowH / 2; y += m.rowH;
      if (e.type === "node") {
        const d = e.d;
        d.r = Math.max(4.5, Math.min(maxR, 4.5 + Math.sqrt((Number(d.citations) || 0) / maxC) * (maxR - 4.5)));
        d.ax = colX; d.ay = ay; d.side = side; d.fs = fs;
        out.push(d);
      } else {
        out.push({
          isCluster: true, year: e.year, items: e.items, side, fs,
          r: Math.max(7, Math.min(maxR + 4, 6 + e.items.length * 1.9)),
          citations: e.items.reduce((s, x) => s + (Number(x.citations) || 0), 0),
          ax: colX, ay,
        });
      }
    });
    return { nodes: out, entries, m, colX, LABEL_MAX, PAD_T, PAD_B, YEAR_GAP, H };
  }

  render(animate = false) {
    const data = this.data;
    if (!data) return;
    const svgEl = this.svgEl;
    const rect = svgEl.getBoundingClientRect();
    const W = Math.max(480, rect.width || 900);
    const H = Math.max(360, rect.height || 620);
    const CX = W * 0.5, CY = (54 + H - 40) / 2;

    if (this.sim) { this.sim.stop(); this.sim = null; }
    d3.select(svgEl).on(".zoom", null).on("dblclick.cit", null);
    svgEl.innerHTML = "";
    if (this.tipEl) { this.tipEl.remove(); this.tipEl = null; }

    const center = {
      title: data.paper.title, doi: data.paper.doi || "",
      year: data.paper.year, citations: data.paper.citations,
      isCenter: true, side: "center", fs: 13,
      r: Math.max(15, Math.min(22, 12 + Math.sqrt((Number(data.paper.citations) || 0) / 200) * 9)),
      ax: CX, ay: CY,
    };

    const L = this._pick(data.referenced || []);
    const R = this._pick(data.citing || []);
    const leftInfo = { ...this._layoutSide(L.show, "left", W, H), hidden: L.hidden };
    const rightInfo = { ...this._layoutSide(R.show, "right", W, H), hidden: R.hidden };
    this.hiddenL = L.hidden; this.hiddenR = R.hidden;

    const nodes = [center, ...leftInfo.nodes, ...rightInfo.nodes];
    const links = [
      ...leftInfo.nodes.filter(n => !n.isCluster)
        .map(d => ({ source: d, target: center, kind: "ref" })),
      ...rightInfo.nodes.filter(n => !n.isCluster)
        .map(d => ({ source: center, target: d, kind: "cite" })),
    ];
    this.nodes = nodes; this.links = links;

    const svg = d3.select(svgEl);
    const root = svg.append("g").attr("class", "cit-root");
    const gS = root.append("g").attr("class", "g-static");
    const gL = root.append("g").attr("class", "g-links");
    const gN = root.append("g").attr("class", "g-nodes");

    const zoom = d3.zoom()
      .scaleExtent([0.5, 3.5])
      .translateExtent([[-280, -220], [W + 280, H + 220]])
      .filter(ev => !ev.ctrlKey && ev.type !== "dblclick")
      .on("zoom", ev => {
        root.attr("transform", ev.transform);
        const z = document.getElementById("graphZoomLevel");
        if (z) z.textContent = Math.round(ev.transform.k * 100) + "%";
        const z2 = document.getElementById("citZoomPct");
        if (z2) z2.textContent = Math.round(ev.transform.k * 100) + "%";
      });
    svg.call(zoom)
      .on("dblclick.zoom", null)
      .on("dblclick.cit", () => this.render(true))       // 双击 = 重排（原型交互）
      .on("mousedown.citcursor", () => svgEl.classList.add("grabbing"))
      .on("mouseup.citcursor", () => svgEl.classList.remove("grabbing"));
    this.zoom = zoom;

    // ---- 静态层：列标题 + 分隔线 + 年份分隔 + 「展开全部」 ----
    gS.append("text").attr("x", leftInfo.colX).attr("y", 24)
      .attr("text-anchor", "middle").attr("class", "cit-colhead")
      .text(`${t("citReferencedCol")} · ${leftInfo.nodes.filter(n => !n.isCluster).length} ${t("citItemsUnit")}`);
    gS.append("text").attr("x", rightInfo.colX).attr("y", 24)
      .attr("text-anchor", "middle").attr("class", "cit-colhead")
      .text(`${t("citCitingCol")} · ${rightInfo.nodes.filter(n => !n.isCluster).length} ${t("citItemsUnit")}`);
    [leftInfo.colX, rightInfo.colX].forEach(x => gS.append("line")
      .attr("x1", x).attr("y1", 54 - 16).attr("x2", x).attr("y2", H - 40 + 16)
      .attr("class", "cit-colline"));

    if (this.state.arrange !== "flat") {
      [[leftInfo, "left"], [rightInfo, "right"]].forEach(([info]) => {
        let cy = info.m.startY;
        info.entries.forEach(e => {
          if (e.type === "gap") {
            cy += info.m.rowH ? 0 : 0;
            cy += 10;
            gS.append("line").attr("x1", info.colX - 16).attr("x2", info.colX + 16)
              .attr("y1", cy).attr("y2", cy).attr("class", "cit-yrgap");
            cy += 10;
          } else cy += info.m.rowH;
        });
      });
    }

    [[leftInfo, "left"], [rightInfo, "right"]].forEach(([info]) => {
      if (!info.hidden.length) return;
      const last = info.nodes.slice(-1)[0];
      gS.append("text").attr("class", "cit-more")
        .attr("x", info.colX)
        .attr("y", Math.min((last ? last.ay : CY) + 32, H - 40 + 24))
        .attr("text-anchor", "middle")
        .text(t("citMore").replace("{n}", info.hidden.length))
        .on("click", () => {
          this.state.limit = "all";
          // 「展开全部」后同步 index.html 里控件条的选中态（模块内不直接依赖 DOM 之外的 inline 函数）
          if (typeof window._syncCitationToolbar === "function") window._syncCitationToolbar();
          this.render(true);
        });
    });

    // ---- 连线（贝塞尔） ----
    const curve = (x1, y1, x2, y2) => {
      const dx = (x2 - x1) * 0.42;
      return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
    };
    const link = gL.selectAll("path").data(links).join("path")
      .attr("class", "cit-lnk")
      .attr("stroke", d => d.kind === "ref" ? COLOR_MAP.referenced : COLOR_MAP.citing)
      .attr("stroke-opacity", 0.34).attr("stroke-width", 1.4);

    // ---- 节点 ----
    const keyOf = d => d.isCenter ? "@c" : (d.isCluster ? "@k" + d.year : "@n" + (d.title || "") + d.doi);
    const node = gN.selectAll("g.cit-nd").data(nodes, keyOf).join("g")
      .attr("class", "cit-nd");

    node.each((d, i, arr) => {
      const g = d3.select(arr[i]);
      g.selectAll("*").remove();
      const color = d.isCenter ? COLOR_MAP.center
        : (d.side === "left" ? COLOR_MAP.referenced : COLOR_MAP.citing);
      if (d.isCenter) {
        g.append("circle").attr("r", d.r + 7).attr("fill", "none")
          .attr("stroke", COLOR_MAP.center).attr("stroke-opacity", 0.16).attr("stroke-width", 7);
      }
      g.append("circle").attr("class", "cit-body").attr("r", d.r).attr("fill", color)
        .attr("stroke", "var(--bg-elevated)").attr("stroke-width", d.isCenter ? 3 : (d.isCluster ? 2.5 : 2));
      if (d.isCluster) {
        g.append("text").attr("text-anchor", "middle").attr("y", 4)
          .attr("font-size", 11).attr("font-weight", 600)
          .style("fill", "#fff").style("pointer-events", "none").text(d.items.length);
      }
      const isLeft = d.side === "left";
      // 直接按字符数截断 —— safeSlice 内部有 ×1.7 的宽度系数（为 CJK 混排设计），
      // 纯英文标题会超预算 70%，导致中心标题越过右栏、侧栏标签贴出画布
      const cut = (s, n) => {
        const c = Array.from(String(s || ""));
        return c.length <= n ? c.join("") : c.slice(0, Math.max(1, n - 1)).join("") + "…";
      };
      if (d.isCenter) {
        // text-anchor=middle → 标题向两侧各延伸预算一半，右端不能越过右栏
        // (COL_R - CX = 0.195W)，故全预算取 0.39W（原型 486px/1180W ≈ 同比例）
        g.append("text").attr("class", "cit-lbl").attr("text-anchor", "middle")
          .attr("y", -d.r - 14).attr("font-size", d.fs).attr("font-weight", 600)
          .text(cut(d.title, Math.max(6, Math.floor(W * 0.39 / (d.fs * 0.62)))));
        g.append("text").attr("text-anchor", "middle").attr("y", d.r + 18)
          .attr("font-size", 11).attr("class", "cit-yr")
          .text(`${d.year ?? ""} · ${t("citCitedBy").replace("{n}", d.citations || 0)}`);
      } else {
        const label = d.isCluster
          ? t("citYearPapers").replace("{y}", d.year).replace("{n}", d.items.length)
          : d.title;
        g.append("text").attr("class", "cit-lbl")
          .attr("x", isLeft ? -(d.r + 9) : (d.r + 9))
          .attr("text-anchor", isLeft ? "end" : "start").attr("y", 4)
          .attr("font-size", d.fs).attr("font-weight", d.isCluster ? 500 : 400)
          .text(cut(label, Math.max(6, Math.floor(leftInfo.LABEL_MAX / (d.fs * 0.62)))));
        g.append("text")
          .attr("class", d.isCluster ? "cit-yrtag" : "cit-yr")
          .attr("x", isLeft ? (d.r + 8) : -(d.r + 8))
          .attr("text-anchor", isLeft ? "start" : "end").attr("y", 4)
          .text(d.isCluster ? t("citExpandHint") : (d.year ?? ""));
      }
    });

    // ---- Tooltip ----
    const bodyEl = svgEl.parentElement;
    const tip = document.createElement("div");
    tip.className = "net-tip";
    (bodyEl || document.body).appendChild(tip);
    this.tipEl = tip;
    const showTip = (e, d) => {
      if (d.isCenter) {
        tip.innerHTML = `<b>${escapeHtml(safeSlice(d.title, 60))}</b><br><span class="m">${d.year ?? ""} · ${t("citCitedBy").replace("{n}", d.citations || 0)}</span>`;
      } else if (d.isCluster) {
        const top = d.items.slice().sort((a, b) => (Number(b.citations) || 0) - (Number(a.citations) || 0))
          .slice(0, 5).map(x => `· ${escapeHtml(safeSlice(x.title, 28))}`).join("<br>");
        tip.innerHTML = `<b>${t("citYearPapers").replace("{y}", d.year).replace("{n}", d.items.length)}</b><br><span class="m">${t("citExpandHint")}</span><br>${top}`;
      } else {
        tip.innerHTML = `<b>${escapeHtml(safeSlice(d.title, 60))}</b><br><span class="m">${d.year ?? ""} · ${t("citCitedBy").replace("{n}", Number(d.citations) || 0)}</span>`;
      }
      tip.classList.add("on");
      const brect = bodyEl.getBoundingClientRect();
      let x = e.clientX - brect.left + 14, y = e.clientY - brect.top - 10;
      if (x + 330 > brect.width) x -= 350;
      tip.style.left = x + "px"; tip.style.top = y + "px";
    };
    const hideTip = () => tip.classList.remove("on");

    // ---- 交互 ----
    node.on("mouseenter", function (e, d) {
      node.selectAll("circle.cit-body").attr("opacity", n => (n === d || n.isCenter) ? 1 : 0.16);
      node.selectAll("text").attr("opacity", n => (n === d || n.isCenter) ? 1 : 0.16);
      link.attr("stroke-opacity", l => (l.source === d || l.target === d) ? 0.95 : 0.05)
          .attr("stroke-width", l => (l.source === d || l.target === d) ? 2.6 : 1.4);
      showTip(e, d);
    }).on("mouseleave", function () {
      node.selectAll("circle.cit-body").attr("opacity", 1);
      node.selectAll("text").attr("opacity", 1);
      link.attr("stroke-opacity", 0.34).attr("stroke-width", 1.4);
      hideTip();
    }).on("click", (e, d) => {
      if (d.isCluster) {
        e.stopPropagation();
        this.expandedYears.has(d.year)
          ? this.expandedYears.delete(d.year)
          : this.expandedYears.add(d.year);
        this.render(true);
        return;
      }
      if (!d.isCenter && this.onNodeClick) this.onNodeClick(d);
    });

    // ---- 锚定物理（原型参数） ----
    this.sim = d3.forceSimulation(nodes)
      .force("x", d3.forceX(d => d.ax).strength(0.34))
      .force("y", d3.forceY(d => d.ay).strength(0.34))
      .force("collide", d3.forceCollide(d => d.r + 6).strength(0.6).iterations(2))
      .force("link", d3.forceLink(links).id(keyOf)
        .distance(l => Math.abs(l.target.ax - l.source.ax) * 0.72).strength(0.05))
      .alphaDecay(0.035).velocityDecay(0.36);

    nodes.forEach(d => {
      if (animate) { d.x = CX + (Math.random() - 0.5) * 70; d.y = CY + (Math.random() - 0.5) * 70; }
      else { d.x = d.ax; d.y = d.ay; }
      d.vx = 0; d.vy = 0; d.fx = null; d.fy = null;
    });
    this.sim.alpha(1).restart()
      .on("tick", () => {
        node.attr("transform", d => `translate(${d.x},${d.y})`);
        link.attr("d", l => curve(l.source.x, l.source.y, l.target.x, l.target.y));
      });

    node.call(d3.drag()
      .on("start", (e, d) => {
        if (!e.active) this.sim.alphaTarget(0.28).restart();
        d.fx = d.x; d.fy = d.y;
        if (!d.isCluster) d3.select(e.currentTarget).raise();
        svgEl.classList.add("grabbing");
      })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => {
        if (!e.active) this.sim.alphaTarget(0);
        d.fx = null; d.fy = null;
        svgEl.classList.remove("grabbing");
      }));
  }
}

window.CitationGraphV2 = CitationGraphV2;
