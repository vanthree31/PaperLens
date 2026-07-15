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
const COLLIDE_PADDING = 18;
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
  const radius = Math.min(width, height) * 0.35;

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
 */
function computeRadius(citations, maxCitations, type) {
  if (type === "center") return 24;
  const scale = d3.scaleSqrt().domain([0, Math.max(maxCitations, 1)]).range([12, 20]);
  return scale(citations);
}

/**
 * 截断标签
 */
function truncateLabel(title, maxLen = 20) {
  if (!title) return "";
  return title.length > maxLen ? title.slice(0, maxLen) + "…" : title;
}

// ========== CitationGraph 类 ==========

export class CitationGraph {
  constructor(svgEl, options = {}) {
    this.svgEl = svgEl;
    this.simulation = null;
    this.nodes = [];
    this.links = [];
    this.currentZoom = 1;
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

    const maxCitations = Math.max(data.paper.citations, 1);

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
    data.citing.slice(0, MAX_CITING).forEach((p, i) => {
      const node = {
        id: `citing-${i}`,
        fullTitle: p.title,
        doi: p.doi || "",
        year: p.year,
        citations: p.citations,
        type: "citing",
        radius: computeRadius(p.citations, maxCitations, "citing"),
      };
      this.nodes.push(node);
      this.links.push({ source: node, target: center, type: "citing" });
    });

    // 被引节点
    data.referenced.slice(0, MAX_REFERENCED).forEach((p, i) => {
      const node = {
        id: `ref-${i}`,
        fullTitle: p.title,
        doi: p.doi || "",
        year: p.year,
        citations: p.citations,
        type: "referenced",
        radius: computeRadius(p.citations, maxCitations, "referenced"),
      };
      this.nodes.push(node);
      this.links.push({ source: center, target: node, type: "referenced" });
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
    const zoomBehavior = d3.zoom()
      .scaleExtent([0.15, 5])
      .on("zoom", (e) => {
        container.attr("transform", e.transform);
        this.currentZoom = e.transform.k;
        this._updateLabels();
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
      .text(d => truncateLabel(d.fullTitle));

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
   * 更新标签（缩放时）
   */
  _updateLabels() {
    if (!this._nodeSel) return;
    const k = this.currentZoom;
    this._nodeSel.selectAll(".graph-label-text")
      .text(d => {
        if (k < 0.3) return d.type === "center" ? "●" : "";
        if (k < 0.8) return `${d.year}`;
        const maxLen = k >= 1.5 ? 50 : Math.floor(10 + k * 15);
        return truncateLabel(d.fullTitle, maxLen);
      })
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
      .scaleExtent([0.2, 4])
      .wheelDelta((e) => -e.deltaY * 0.002)
      .filter((e) => !e.ctrlKey && e.type !== 'dblclick')
      .on("zoom", (e) => {
        container.attr("transform", e.transform);
        this.currentZoom = e.transform.k;
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
        .attr("stroke-width", d => linkScale(d.weight || 1));

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
      .attr("r", d => radiusScale(d.count || 1))
      .attr("fill", this.nodeColor)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2);

    // 大数据集只显示前 25 个最重要节点的标签，避免拥挤
    const showAllLabels = nodeCount <= 25;
    if (!showAllLabels) {
      const topIds = new Set(this.nodes.slice().sort((a,b)=>(b.count||0)-(a.count||0)).slice(0,25).map(n=>n.id));
      this.nodes.forEach(n => { n._showLabel = topIds.has(n.id); });
    } else { this.nodes.forEach(n => { n._showLabel = true; }); }

    node.append("text")
      .attr("class", "graph-label-text")
      .attr("text-anchor", "middle")
      .attr("dy", d => radiusScale(d.count || 1) + 16)
      .attr("font-size", nodeCount > 30 ? 9 : 11)
      .attr("font-weight", 500)
      .attr("opacity", d => d._showLabel ? 1 : 0)
      .text(d => d._showLabel ? (d.label && d.label.length > maxLabelLen ? d.label.substring(0, maxLabelLen) + "..." : d.label) : "");

    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", d => radiusScale(d.count || 1) + 28)
      .attr("font-size", nodeCount > 30 ? 8 : 9)
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
