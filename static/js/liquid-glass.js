/**
 * Liquid Glass — 原生 JS 实现（每元素独立滤镜）
 *
 * 技法参考 liquid-glass-react：
 *  1. canvas 生成「圆角矩形边缘法线」位移图：R=X 位移、B=Y 位移（128 为基准）、A=边缘强度
 *  2. SVG 滤镜：feDisplacementMap 边缘折射 + RGB 三通道错位色散（screen 混合），
 *     再按位移图 alpha 只保留边缘折射，中心用原图保证内容清晰
 *  3. CSS 层：backdrop-filter 磨砂 + 高光边框（见 liquid-glass.css）
 *
 * 用法：给元素加 class="lg-surface" 并放入 .lg-warp / .lg-content 子层，
 *       页面初始化调用 initLiquidGlass()。可用 data-lg-scale 调整折射强度。
 *
 * 性能：每个表面一个独立滤镜（尺寸各自匹配）。滤镜只在元素「无动画运行」时启用
 *      （.lg-refract），过渡期间只保留 backdrop-filter。
 *      大面板上折射会显脏，建议只用于小控件/弹窗。
 */

let _seq = 0;

function roundedRectSDF(x, y, hw, hh, r) {
  const qx = Math.abs(x) - hw + r;
  const qy = Math.abs(y) - hh + r;
  return (
    Math.min(Math.max(qx, qy), 0) +
    Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) -
    r
  );
}

/**
 * 生成圆角矩形边缘折射位移图（PNG data URL）。
 */
export function generateDisplacementMap(w, h, radius = 20) {
  const W = Math.max(2, Math.round(w));
  const H = Math.max(2, Math.round(h));
  const R = Math.max(0, Math.min(radius, Math.min(W, H) / 2));
  const band = Math.max(10, Math.min(56, Math.min(W, H) * 0.09));

  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(W, H);
  const data = image.data;

  const cx = W / 2;
  const cy = H / 2;
  const eps = 1;

  let p = 0;
  for (let y = 0; y < H; y++) {
    const py = y + 0.5 - cy;
    for (let x = 0; x < W; x++) {
      const px = x + 0.5 - cx;
      const depth = -roundedRectSDF(px, py, cx, cy, R);
      const edge = 1 - Math.max(0, Math.min(1, depth / band));

      const gx =
        roundedRectSDF(px + eps, py, cx, cy, R) -
        roundedRectSDF(px - eps, py, cx, cy, R);
      const gy =
        roundedRectSDF(px, py + eps, cx, cy, R) -
        roundedRectSDF(px, py - eps, cx, cy, R);
      const len = Math.hypot(gx, gy) || 1;

      data[p] = Math.max(0, Math.min(255, 128 + (gx / len) * edge * 127));
      data[p + 1] = 128;
      data[p + 2] = Math.max(0, Math.min(255, 128 + (gy / len) * edge * 127));
      data[p + 3] = Math.max(0, Math.min(255, edge * 255));
      p += 4;
    }
  }

  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png");
}

/**
 * 为一个表面构建专属 SVG 滤镜，返回 { uid, feImage }。
 */
function createFilterFor(el, scale) {
  const uid = `lgf-${++_seq}`;
  const s = Math.round(Math.abs(scale) || 24);
  const markup = `<svg width="0" height="0" aria-hidden="true" style="position:absolute;pointer-events:none"><defs><filter id="${uid}" x="-25%" y="-25%" width="150%" height="150%" color-interpolation-filters="sRGB"><feImage x="0" y="0" width="100%" height="100%" result="MAP" preserveAspectRatio="none"/><feDisplacementMap in="SourceGraphic" in2="MAP" scale="-${s}" xChannelSelector="R" yChannelSelector="B" result="D_R"/><feColorMatrix in="D_R" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="C_R"/><feDisplacementMap in="SourceGraphic" in2="MAP" scale="-${Math.max(1, s - 2)}" xChannelSelector="R" yChannelSelector="B" result="D_G"/><feColorMatrix in="D_G" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="C_G"/><feDisplacementMap in="SourceGraphic" in2="MAP" scale="-${Math.max(1, s - 4)}" xChannelSelector="R" yChannelSelector="B" result="D_B"/><feColorMatrix in="D_B" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="C_B"/><feBlend in="C_G" in2="C_B" mode="screen" result="C_GB"/><feBlend in="C_R" in2="C_GB" mode="screen" result="C_ALL"/><feComposite in="C_ALL" in2="MAP" operator="in" result="EDGE"/><feComponentTransfer in="MAP" result="MAP_INV"><feFuncA type="table" tableValues="1 0"/></feComponentTransfer><feComposite in="SourceGraphic" in2="MAP_INV" operator="in" result="CENTER"/><feComposite in="EDGE" in2="CENTER" operator="over"/></filter></defs></svg>`;
  el.insertAdjacentHTML("afterbegin", markup);
  return { uid, feImage: el.querySelector(`filter[id="${uid}"] feImage`) };
}

/**
 * 注入玻璃层（warp / border / highlight）。插到最前面，
 * 保持原有子节点相对顺序不变，避免破坏 :first-child 之类选择器。
 */
function ensureLayers(el) {
  if (el.querySelector(":scope > .lg-warp")) return;
  const tmp = document.createElement("div");
  tmp.innerHTML =
    '<span class="lg-warp"></span><span class="lg-border"></span><span class="lg-border2"></span><span class="lg-highlight"></span>';
  const layers = [...tmp.children].reverse();
  layers.forEach(n => el.insertBefore(n, el.firstChild));
}

/**
 * 挂载单个 .lg-surface：注入玻璃层、创建专属滤镜、跟随尺寸刷新位移图、
 * 仅在无动画运行时启用折射。
 */
export function mountGlassSurface(el) {
  if (!el || el.__lgMounted) return;
  el.__lgMounted = true;

  ensureLayers(el);

  const radius = parseFloat(getComputedStyle(el).borderRadius) || 20;
  const rect0 = el.getBoundingClientRect();
  // 小控件折射幅度按尺寸收敛，避免"糊掉"
  const autoScale = Math.max(
    10,
    Math.min(30, Math.min(rect0.width || 60, rect0.height || 40) * 0.45)
  );
  const scale = parseFloat(el.dataset.lgScale || "0") || autoScale;

  const { uid, feImage } = createFilterFor(el, scale);
  const warp = el.querySelector(".lg-warp");
  const enableRefract = () => {
    if (warp) warp.style.filter = `url(#${uid})`;
  };
  const disableRefract = () => {
    if (warp) warp.style.filter = "none";
  };

  const sync = () => {
    const r = el.getBoundingClientRect();
    if (r.width >= 4 && r.height >= 4 && feImage) {
      try {
        feImage.setAttribute(
          "href",
          generateDisplacementMap(r.width, r.height, radius)
        );
      } catch (e) {
        console.warn("[LiquidGlass] 位移图生成失败，退化为普通磨砂:", e);
      }
    }
  };

  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    el.__lgRO = ro;
  }
  sync();

  const enableWhenIdle = () => {
    const running =
      typeof el.getAnimations === "function" &&
      el.getAnimations().some(a => a.playState === "running");
    if (running) return;
    enableRefract();
    el.classList.add("lg-refract");
  };
  el.addEventListener("transitionend", enableWhenIdle);
  el.addEventListener("transitioncancel", () => {
    disableRefract();
    el.classList.remove("lg-refract");
  });
  requestAnimationFrame(enableWhenIdle);
}

export function initLiquidGlass(root = document) {
  root.querySelectorAll(".lg-surface").forEach(mountGlassSurface);
}

if (typeof window !== "undefined") {
  window.LiquidGlass = { init: initLiquidGlass, mount: mountGlassSurface };
}
