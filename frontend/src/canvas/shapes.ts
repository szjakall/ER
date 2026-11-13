import { Ellipse, Group, Line, Polygon, Rect, Text } from "fabric";
import type { AttrShape, Connection, Element } from "../protocol/types";
import type { ShapeStyle } from "./appearance";
import { borderPoint, clamp } from "./geometry";
import { layoutText, measureTextWidth, textBlockStyle, type TextLayout } from "./text";
import { FONT, GEO, SCALE, STROKE, WEIGHT } from "./theme";

const TITLE: Record<string, string> = { rectangle: "实体", ellipse: "属性", diamond: "联系" };

export interface ElementVisual {
  group: Group;
  body: Rect | Ellipse | Polygon;
  /** 弱实体的内框 / 标识联系的内菱形 */
  innerBody?: Rect | Ellipse | Polygon;
  w: number;
  h: number;
  shape: Element["shape"];
  fingerprint: string;
}

type AttrKind = "normal" | "pk" | "partial";

/** 一个属性椭圆节点：椭圆（+ 双椭圆内圈）+ 归属直线 + 属性名（+ 下划线） */
export interface AttrNode {
  ellipse: Ellipse;
  inner?: Ellipse;
  link: Line;
  label: Text;
  /** 主键 / 部分键的每条文字行各一条下划线 */
  underlines: Line[];
  name: string;
  kind: AttrKind;
  shape: AttrShape;
  ox: number;
  oy: number;
  w: number;
  h: number;
  lines: string[];
  lineHeight: number;
}

export interface AttrNodeVisual {
  parts: Array<Ellipse | Line | Text>;
  nodes: AttrNode[];
  shape: Element["shape"];
  w: number;
  h: number;
  angle: number;
  scale: number;
  fingerprint: string;
}

export interface ElementLabelLayout extends TextLayout {
  W: number;
  H: number;
  /** 每行实际宽度，椭圆 / 菱形的内接计算会用到 */
  lineWidths: number[];
}

/**
 * 内容级缩放：图形、字号、描边、端点、基数标签共用的唯一比例。
 * 旧数据没有 layout_scale 时按 1 处理；非法值回退到 1，避免导入坏数据后整图消失。
 */
export function elementScale(el: Element): number {
  const raw = Number(el.layout_scale);
  if (!Number.isFinite(raw) || raw <= 0) return SCALE.default;
  return clamp(raw, SCALE.min, SCALE.max);
}

export function elementFingerprint(el: Element, styleKey = "") {
  const size = el.size ? `${el.size.w}x${el.size.h}` : "";
  return [
    el.shape,
    el.label,
    (el.attributes ?? []).join("\n"),
    el.is_weak ? 1 : 0,
    el.is_identifying ? 1 : 0,
    size,
    JSON.stringify(el.attr_style ?? {}),
    elementScale(el).toFixed(3),
    styleKey,
  ].join("|");
}

export function attrFingerprint(el: Element, angle: number, styleKey = "") {
  return [
    el.shape,
    Math.round(angle * 100),
    (el.attributes ?? []).join("\n"),
    JSON.stringify(el.attr_offsets ?? {}),
    JSON.stringify(el.attr_style ?? {}),
    elementScale(el).toFixed(3),
    styleKey,
  ].join("|");
}

/** 属性名前缀：* = 主键（实线下划线），# = 部分键 / 弱属性（虚线下划线） */
function parseAttr(raw: string): { name: string; kind: AttrKind } {
  const s = String(raw ?? "").trim();
  if (s.startsWith("*")) return { name: s.replace(/^\*+/, "").trim(), kind: "pk" };
  if (s.startsWith("#")) return { name: s.replace(/^#+/, "").trim(), kind: "partial" };
  return { name: s, kind: "normal" };
}

function parseAttrs(el: Element) {
  return (el.attributes ?? []).map(parseAttr).filter((a) => a.name);
}

function attrShapeAt(el: Element, index: number): AttrShape {
  const s = el.attr_style?.[String(index)];
  return s === "multi" || s === "derived" ? s : "normal";
}

/** 取偶数尺寸：图形以中心定位时半宽 / 半高才是整数，描边不会落在半像素上 */
function even(v: number) {
  const n = Math.round(v);
  return n % 2 ? n + 1 : n;
}

const labelOf = (el: Element) => (el.label ?? "").trim() || TITLE[el.shape] || "";

/** 每一行的真实宽度；用于把多行文字安全地放进椭圆 / 菱形 */
function lineWidths(layout: TextLayout, weight: number | string) {
  return layout.lines.map((line) => measureTextWidth(line, layout.fontSize, weight));
}

function fitTextInEllipse(
  layout: TextLayout,
  widths: number[],
  gap: number,
  minW: number,
  minH: number,
  padY: number,
  maxW: number,
) {
  const H = even(clamp(layout.height + padY * 2, minH, 640));
  const n = Math.max(1, widths.length);
  let needW = minW;
  for (let i = 0; i < n; i++) {
    // 第 i 行中心相对文本块中心的偏移
    const dy = (i - (n - 1) / 2) * layout.lineHeight;
    const ratio = Math.min(0.92, (2 * Math.abs(dy)) / H);
    const denom = Math.sqrt(Math.max(0.08, 1 - ratio * ratio));
    needW = Math.max(needW, (widths[i] + gap) / denom);
  }
  const W = even(clamp(needW, minW, maxW));
  return { W, H };
}

/** 菱形内可用的水平宽度随 |y| 线性收缩，逐行校验保证文字不出界 */
function fitTextInDiamond(
  layout: TextLayout,
  widths: number[],
  minW: number,
  minH: number,
  padY: number,
  maxW: number,
) {
  let H = even(clamp(layout.height + padY * 2, minH, 640));
  const n = Math.max(1, widths.length);
  const needW = () => {
    let max = minW;
    for (let i = 0; i < n; i++) {
      const dy = (i - (n - 1) / 2) * layout.lineHeight;
      const usable = 1 - (2 * Math.abs(dy)) / H;
      max = Math.max(max, (widths[i] + 16) / Math.max(0.28, usable));
    }
    return max;
  };
  let W = even(clamp(needW(), minW, maxW));
  // 极端长文本：先加高，避免文字从菱形尖角处溢出
  if (needW() > maxW) {
    H = even(clamp(H + (needW() - maxW) * 0.6, H, 640));
    W = even(clamp(needW(), minW, maxW));
  }
  return { W, H };
}

/**
 * 实体 / 属性 / 联系标签的完整排版：先按真实字宽换行，再反推图形尺寸。
 * 默认不截断，因此不需要任何省略号。
 */
export function labelLayout(el: Element, scale = elementScale(el)): ElementLabelLayout {
  const s = clamp(scale, SCALE.min, SCALE.max);
  const label = labelOf(el);
  if (el.shape === "rectangle") {
    const maxTextW = Math.max(80 * s, (GEO.entityMaxW - GEO.entityPadX * 2) * s);
    const layout = layoutText(label, {
      fontSize: FONT.entity * s,
      weight: WEIGHT.entity,
      maxWidth: maxTextW,
    });
    const widths = lineWidths(layout, WEIGHT.entity);
    const W = even(
      clamp(
        Math.max(layout.width, ...widths) + GEO.entityPadX * 2 * s,
        GEO.entityMinW * s,
        GEO.entityMaxW * s,
      ),
    );
    const H = even(clamp(layout.height + GEO.entityPadY * 2 * s, GEO.entityH * s, 640 * s));
    return { ...layout, W, H, lineWidths: widths };
  }

  if (el.shape === "ellipse") {
    const maxTextW = Math.max(80 * s, GEO.attrMaxTextW * s);
    const layout = layoutText(label, {
      fontSize: FONT.attr * s,
      weight: WEIGHT.attr,
      maxWidth: maxTextW,
    });
    const widths = lineWidths(layout, WEIGHT.attr);
    const { W, H } = fitTextInEllipse(
      layout,
      widths,
      10 * s,
      GEO.attrMinW * s,
      GEO.attrH * s,
      GEO.attrPadY * s,
      560 * s,
    );
    return { ...layout, W, H, lineWidths: widths };
  }

  const maxTextW = Math.max(80 * s, GEO.diamondMaxTextW * s);
  const layout = layoutText(label, {
    fontSize: FONT.relation * s,
    weight: WEIGHT.relation,
    maxWidth: maxTextW,
  });
  const widths = lineWidths(layout, WEIGHT.relation);
  const { W, H } = fitTextInDiamond(
    layout,
    widths,
    GEO.diamondMinW * s,
    GEO.diamondH * s,
    GEO.diamondPadY * s,
    480 * s,
  );
  return { ...layout, W, H, lineWidths: widths };
}

/** 属性椭圆的尺寸（只给排版用，避免持有整份 TextLayout） */
export function ellipseMetrics(label: string, scale = 1) {
  const s = clamp(scale, SCALE.min, SCALE.max);
  const layout = layoutText(String(label ?? ""), {
    fontSize: FONT.attr * s,
    weight: WEIGHT.attr,
    maxWidth: Math.max(80 * s, GEO.attrMaxTextW * s),
  });
  const widths = lineWidths(layout, WEIGHT.attr);
  const { W, H } = fitTextInEllipse(
    layout,
    widths,
    10 * s,
    GEO.attrMinW * s,
    GEO.attrH * s,
    GEO.attrPadY * s,
    560 * s,
  );
  return { W, H, layout, lineWidths: widths };
}

export function ellipseSize(label: string, scale = 1) {
  const { W, H } = ellipseMetrics(label, scale);
  return { W, H };
}

/** 完全按文字反推的自然尺寸（忽略手动尺寸），自动布局用 */
export function naturalCoreSize(el: Element) {
  const base = labelLayout(el, 1);
  return { W: base.W, H: base.H };
}

/** 用户手动拖拽过的自定义尺寸；永远不小于文字自然尺寸，避免文字溢出 */
export function computeSize(el: Element, scale = elementScale(el), ignoreCustom = false) {
  const base = labelLayout(el, scale);
  const custom = ignoreCustom ? undefined : el.size;
  if (!custom || !(custom.w > 0) || !(custom.h > 0)) {
    return { W: base.W, H: base.H };
  }
  return {
    W: even(clamp(custom.w, base.W, 900 * scale)),
    H: even(clamp(custom.h, base.H, 640 * scale)),
  };
}

function txt(value: string, opts: Record<string, unknown>) {
  return new Text(String(value ?? ""), {
    fontFamily: FONT.family,
    selectable: false,
    evented: false,
    objectCaching: false,
    ...opts,
  });
}

function labelTextObject(el: Element, layout: ElementLabelLayout, ink: string) {
  const weight =
    el.shape === "rectangle"
      ? WEIGHT.entity
      : el.shape === "diamond"
        ? WEIGHT.relation
        : WEIGHT.attr;
  return txt(layout.lines.join("\n"), {
    ...textBlockStyle(layout),
    left: 0,
    top: 0,
    originX: "center",
    originY: "center",
    fontWeight: weight,
    fill: ink,
  });
}

/**
 * 陈氏记法图形本体：默认白底、墨线、直角、无阴影。
 * 展示主题只替换 fill（浅色晕染），描边与文字始终是深墨色。
 * 严重度不在这里处理 —— 由 ErCanvas 在图形外侧画环。
 */
export function createElementGroup(el: Element, style: ShapeStyle): ElementVisual {
  const cx = el.position?.x ?? 0;
  const cy = el.position?.y ?? 0;
  const s = elementScale(el);
  const layout = labelLayout(el, s);
  const { W, H } = computeSize(el, s);
  const hw = W / 2;
  const hh = H / 2;
  const children: Array<Rect | Ellipse | Polygon | Text> = [];
  let body: Rect | Ellipse | Polygon;
  let innerBody: Rect | Ellipse | Polygon | undefined;
  const inset = GEO.inset * s;

  const fill =
    el.shape === "rectangle"
      ? style.entityFill
      : el.shape === "ellipse"
        ? style.attrFill
        : style.relationFill;
  const shapeBase = {
    fill,
    stroke: style.ink,
    strokeWidth: STROKE.shape * s,
    strokeUniform: false,
    selectable: false,
    evented: false,
    objectCaching: false,
  };

  if (el.shape === "rectangle") {
    body = new Rect({ left: -hw, top: -hh, width: W, height: H, ...shapeBase });
    children.push(body);
    if (el.is_weak) {
      innerBody = new Rect({
        left: -hw + inset,
        top: -hh + inset,
        width: W - inset * 2,
        height: H - inset * 2,
        fill: "transparent",
        stroke: style.ink,
        strokeWidth: STROKE.inner * s,
        strokeUniform: false,
        selectable: false,
        evented: false,
        objectCaching: false,
      });
      children.push(innerBody);
    }
  } else if (el.shape === "ellipse") {
    body = new Ellipse({ left: -hw, top: -hh, rx: hw, ry: hh, ...shapeBase });
    children.push(body);
  } else {
    body = new Polygon(
      [
        { x: 0, y: -hh },
        { x: hw, y: 0 },
        { x: 0, y: hh },
        { x: -hw, y: 0 },
      ],
      { left: 0, top: 0, originX: "center", originY: "center", ...shapeBase },
    );
    children.push(body);
    if (el.is_identifying) {
      const iw = Math.max(8 * s, hw - 6 * s);
      const ih = Math.max(8 * s, hh - 6 * s);
      innerBody = new Polygon(
        [
          { x: 0, y: -ih },
          { x: iw, y: 0 },
          { x: 0, y: ih },
          { x: -iw, y: 0 },
        ],
        {
          left: 0,
          top: 0,
          originX: "center",
          originY: "center",
          fill: "transparent",
          stroke: style.ink,
          strokeWidth: STROKE.inner * s,
          strokeUniform: false,
          selectable: false,
          evented: false,
          objectCaching: false,
        },
      );
      children.push(innerBody);
    }
  }

  children.push(labelTextObject(el, layout, style.ink));
  const labelObj = children[children.length - 1] as Text;
  (labelObj as unknown as { erKind: string; erId: string }).erKind = "elementLabel";
  (labelObj as unknown as { erId: string }).erId = el.id;

  const group = new Group(children, {
    originX: "center",
    originY: "center",
    objectCaching: false,
    left: cx,
    top: cy,
    selectable: true,
    evented: true,
    hasControls: true,
    lockRotation: true,
    lockScalingFlip: true,
    borderColor: style.selection,
    cornerColor: style.paper,
    cornerStrokeColor: style.selection,
    transparentCorners: false,
    cornerSize: 7,
    cornerStyle: "rect",
    borderScaleFactor: 1,
    borderOpacityWhenMoving: 0.95,
    hoverCursor: "move",
    padding: 3 * s,
  });
  // 旋转没有意义：隐藏旋转手柄，避免画布上多出一条连接线
  group.setControlsVisibility({ mtr: false });
  (group as unknown as { erId: string; erKind: string }).erId = el.id;
  (group as unknown as { erKind: string }).erKind = "element";
  group.setCoords();

  return {
    group,
    body,
    innerBody,
    w: W,
    h: H,
    shape: el.shape,
    fingerprint: elementFingerprint(el, style.key),
  };
}

export interface AttrPlacement {
  name: string;
  kind: AttrKind;
  ox: number;
  oy: number;
  w: number;
  h: number;
}

/** 从中心沿角度 a 到图形边框的距离（射线与图形求交） */
export function shapeEdgeDistance(shape: Element["shape"], W: number, H: number, a: number) {
  const ux = Math.cos(a);
  const uy = Math.sin(a);
  if (shape === "ellipse") {
    const rx = Math.max(W / 2, 1);
    const ry = Math.max(H / 2, 1);
    return 1 / Math.sqrt((ux * ux) / (rx * rx) + (uy * uy) / (ry * ry));
  }
  const hw = Math.max(W / 2, 1);
  const hh = Math.max(H / 2, 1);
  if (shape === "rectangle") {
    return Math.min(ux !== 0 ? hw / Math.abs(ux) : Infinity, uy !== 0 ? hh / Math.abs(uy) : Infinity);
  }
  return 1 / (Math.abs(ux) / hw + Math.abs(uy) / hh);
}

/**
 * 属性椭圆在实体周围的落点：先按扇形均匀散开，再用松弛把互相压住的椭圆沿各自方向往外推，
 * 直到任意两个椭圆之间都留出 GEO.attrPad 的空隙。被手动拖过的椭圆保持原位，作为固定障碍。
 */
export function attrPlacements(el: Element, angle: number): AttrPlacement[] {
  const attrs = parseAttrs(el);
  const n = attrs.length;
  if (!n) return [];
  const s = elementScale(el);
  const { W, H } = computeSize(el, s);
  const span = Math.min(Math.PI * 0.9, Math.max(0, n - 1) * (Math.PI / 7.2));
  const items = attrs.map((attr, i) => {
    const size = ellipseSize(attr.name, s);
    const a = angle + (n === 1 ? 0 : (i / (n - 1) - 0.5) * span);
    const off = (el.attr_offsets ?? {})[String(i)];
    // 只有有限坐标才算"手动定位"：空对象 / NaN 一律回退到自动扇形，
    // 避免导入坏数据后属性椭圆跑到 (NaN, NaN)。
    const validOff = !!off && Number.isFinite(off.x) && Number.isFinite(off.y);
    // 基准半径 = 图形边框距离 + 间隙 + 椭圆自身在该方向上的半径
    const r =
      shapeEdgeDistance(el.shape, W, H, a) +
      GEO.attrGap * s +
      shapeEdgeDistance("ellipse", size.W, size.H, a);
    return {
      name: attr.name,
      kind: attr.kind,
      w: size.W,
      h: size.H,
      a,
      r,
      fixed: validOff,
      ox: validOff ? off!.x : Math.cos(a) * r,
      oy: validOff ? off!.y : Math.sin(a) * r,
    };
  });

  const put = (p: (typeof items)[number]) => {
    p.ox = Math.cos(p.a) * p.r;
    p.oy = Math.sin(p.a) * p.r;
  };
  const clash = (p: (typeof items)[number], q: (typeof items)[number]) => {
    const dx = p.ox - q.ox;
    const dy = p.oy - q.oy;
    const hw = p.w / 2 + q.w / 2 + GEO.attrPad * s;
    const hh = p.h / 2 + q.h / 2 + GEO.attrPad * s;
    return (dx * dx) / (hw * hw) + (dy * dy) / (hh * hh) < 1;
  };

  for (let iter = 0; iter < 240; iter++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (!clash(items[i], items[j])) continue;
        for (const k of [i, j]) {
          if (items[k].fixed) continue;
          items[k].r += 6;
          put(items[k]);
          moved = true;
        }
      }
    }
    if (!moved) break;
  }

  return items.map((it) => ({
    name: it.name,
    kind: it.kind,
    ox: Math.round(it.ox),
    oy: Math.round(it.oy),
    w: it.w,
    h: it.h,
  }));
}

/**
 * 把实体 / 联系的 attributes 摊成它旁边的属性椭圆（陈氏画法）。
 * angle 是扇形基准方向（弧度，0=右，π=左）；没有属性时返回 null。
 */
export function createAttrNodes(
  el: Element,
  angle: number,
  cx: number,
  cy: number,
  style: ShapeStyle,
): AttrNodeVisual | null {
  const attrs = parseAttrs(el);
  if (!attrs.length) return null;
  const s = elementScale(el);
  const { W, H } = computeSize(el, s);
  const spots = attrPlacements(el, angle);
  const parts: Array<Ellipse | Line | Text> = [];
  const nodes: AttrNode[] = [];

  attrs.forEach((attr, i) => {
    const spot = spots[i];
    const shape = attrShapeAt(el, i);
    const metrics = ellipseMetrics(attr.name, s);
    const link = new Line([0, 0, 0, 0], {
      stroke: style.ink,
      strokeWidth: STROKE.link * s,
      strokeUniform: false,
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    const ellipse = new Ellipse({
      rx: spot.w / 2,
      ry: spot.h / 2,
      fill: style.attrFill,
      stroke: style.ink,
      strokeWidth: STROKE.shape * s,
      strokeUniform: false,
      strokeDashArray: shape === "derived" ? [4 * s, 3 * s] : null,
      selectable: true,
      evented: true,
      hasControls: false,
      hasBorders: true,
      borderColor: style.selection,
      borderScaleFactor: 1,
      lockRotation: true,
      hoverCursor: "move",
    });
    (ellipse as unknown as { erKind: string }).erKind = "attribute";
    (ellipse as unknown as { erAttrOwner: string }).erAttrOwner = el.id;
    (ellipse as unknown as { erAttrIndex: number }).erAttrIndex = i;

    let inner: Ellipse | undefined;
    if (shape === "multi") {
      inner = new Ellipse({
        rx: Math.max(2 * s, spot.w / 2 - GEO.inset * s),
        ry: Math.max(2 * s, spot.h / 2 - GEO.inset * s),
        fill: "transparent",
        stroke: style.ink,
        strokeWidth: STROKE.inner * s,
        strokeUniform: false,
        selectable: false,
        evented: false,
        objectCaching: false,
      });
    }

    const label = txt(metrics.layout.lines.join("\n"), {
      ...textBlockStyle(metrics.layout),
      left: 0,
      top: 0,
      originX: "center",
      originY: "center",
      fontWeight: WEIGHT.attr,
      fill: style.ink,
    });
    (label as unknown as { erKind: string }).erKind = "attrLabel";
    (label as unknown as { erAttrOwner: string }).erAttrOwner = el.id;
    (label as unknown as { erAttrIndex: number }).erAttrIndex = i;

    const underlines: Line[] = [];
    if (attr.kind !== "normal") {
      for (let li = 0; li < metrics.layout.lines.length; li++) {
        const underline = new Line([0, 0, 0, 0], {
          stroke: style.ink,
          strokeWidth: STROKE.underline * s,
          strokeUniform: false,
          strokeDashArray: attr.kind === "partial" ? [3 * s, 2 * s] : null,
          selectable: false,
          evented: false,
          objectCaching: false,
        });
        underlines.push(underline);
      }
    }

    const node: AttrNode = {
      ellipse,
      inner,
      link,
      label,
      underlines,
      name: attr.name,
      kind: attr.kind,
      shape,
      ox: spot.ox,
      oy: spot.oy,
      w: spot.w,
      h: spot.h,
      lines: metrics.layout.lines,
      lineHeight: metrics.layout.lineHeight,
    };
    parts.push(link, ellipse);
    if (inner) parts.push(inner);
    parts.push(label);
    parts.push(...underlines);
    nodes.push(node);
  });

  const vis: AttrNodeVisual = {
    parts,
    nodes,
    shape: el.shape,
    w: W,
    h: H,
    angle,
    scale: s,
    fingerprint: attrFingerprint(el, angle, style.key),
  };
  layoutAttrNodes(vis, cx, cy);
  return vis;
}

/** 实体（cx, cy 为实体中心）移动后重新摆放属性椭圆与归属直线 */
export function layoutAttrNodes(vis: AttrNodeVisual, cx: number, cy: number) {
  const s = vis.scale;
  for (const n of vis.nodes) {
    // 取整：椭圆中心落在整数像素上，描边才不会被抗锯齿糊掉
    const ex = Math.round(cx + n.ox);
    const ey = Math.round(cy + n.oy);
    n.ellipse.set({ left: ex - n.w / 2, top: ey - n.h / 2 });
    if (n.inner) {
      n.inner.set({
        left: ex - (n.w / 2 - GEO.inset * s),
        top: ey - (n.h / 2 - GEO.inset * s),
      });
    }
    n.label.set({ left: ex, top: ey });
    // Text 的 origin 是 center：set(left/top) 之后必须刷新坐标，
    // 否则 getBoundingRect / 命中区域仍是上一版位置（比例切换时会误判文字出界）
    n.label.setCoords();
    if (n.inner) n.inner.setCoords();

    const nLines = Math.max(1, n.lines.length);
    const blockTop = ey - (nLines * n.lineHeight) / 2;
    const fontPx = Number(n.label.fontSize) || FONT.attr;
    for (let li = 0; li < n.underlines.length; li++) {
      const tw = measureTextWidth(n.lines[li] ?? "", fontPx, WEIGHT.attr);
      const uy = blockTop + n.lineHeight * (li + 0.86);
      n.underlines[li].set({ x1: ex - tw / 2, y1: uy, x2: ex + tw / 2, y2: uy });
    }

    const onEllipse = borderPoint("ellipse", n.w, n.h, ex, ey, cx, cy);
    const onShape = borderPoint(vis.shape, vis.w, vis.h, cx, cy, ex, ey);
    n.link.set({ x1: onEllipse.x, y1: onEllipse.y, x2: onShape.x, y2: onShape.y });
    n.ellipse.setCoords();
  }
}

/** 属性扇形基准方向：取与所有连线方向夹角最大的"空闲"方向 */
export function attrBaseAngle(
  el: Element,
  elements: Element[],
  connections: Connection[],
): number {
  const angles: number[] = [];
  for (const c of connections) {
    const otherId = c.from === el.id ? c.to : c.to === el.id ? c.from : null;
    if (!otherId) continue;
    const other = elements.find((e) => e.id === otherId);
    if (!other) continue;
    angles.push(Math.atan2(other.position.y - el.position.y, other.position.x - el.position.x));
  }
  if (!angles.length) return 0;
  let best = 0;
  let bestScore = -1;
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2 - Math.PI;
    let minDiff = Math.PI;
    for (const b of angles) {
      let d = Math.abs(a - b);
      if (d > Math.PI) d = Math.PI * 2 - d;
      if (d < minDiff) minDiff = d;
    }
    if (minDiff > bestScore) {
      bestScore = minDiff;
      best = a;
    }
  }
  return best;
}

/** 纯几何：属性椭圆的绝对中心与尺寸（渲染与重叠检测共用同一套排布） */
export function attrNodeBoxes(el: Element, angle: number) {
  return attrPlacements(el, angle).map((p) => ({
    name: p.name,
    kind: p.kind,
    cx: el.position.x + p.ox,
    cy: el.position.y + p.oy,
    w: p.w,
    h: p.h,
  }));
}
