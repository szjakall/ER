import { Circle, Ellipse, Group, Line, Polygon, Rect, Text } from "fabric";
import type { Connection, Element, PaintState } from "../protocol/types";
import { borderPoint, clamp, textWidth, truncateTo } from "./geometry";
import { FILL_TINT, FONT, STROKE, STROKE_W } from "./highlight";

const TITLE: Record<string, string> = { rectangle: "实体", ellipse: "属性", diamond: "联系" };

/**
 * 陈氏（Chen）ER 图记法：矩形 = 实体（框内只写实体名）、椭圆 = 属性、菱形 = 联系。
 * 实体/联系上的 attributes 摊成它们旁边的属性椭圆 + 归属直线，按"扇形"散开，
 * 避免排成一排或一列（教材里属性是围绕实体散开的）。
 */
const ATTR_GAP = 18; // 属性椭圆与实体边框的间隙
const ATTR_PAD = 14; // 相邻属性椭圆之间至少留出的空隙

export interface ElementVisual {
  group: Group;
  body: Rect | Ellipse | Polygon;
  badge: Circle;
  /** 弱实体的内框（双线矩形） */
  innerBody?: Rect;
  w: number;
  h: number;
  shape: Element["shape"];
  fingerprint: string;
}

/** 一个派生属性椭圆节点：椭圆 + 到实体的直线 + 属性名（+ 部分键虚线下划线） */
export interface AttrNode {
  ellipse: Ellipse;
  link: Line;
  label: Text;
  dash?: Line;
  name: string;
  ox: number; // 椭圆中心相对实体中心的水平偏移
  oy: number; // 椭圆中心相对实体中心的纵向偏移
  w: number;
  h: number;
}

export interface AttrNodeVisual {
  parts: Array<Ellipse | Line | Text>;
  nodes: AttrNode[];
  shape: Element["shape"];
  w: number;
  h: number;
  /** 扇形基准方向（弧度，0=右，π=左） */
  angle: number;
  fingerprint: string;
}

type AttrKind = "normal" | "pk" | "partial";

export function elementFingerprint(el: Element) {
  return `${el.shape}|${el.label}|${(el.attributes ?? []).join("\n")}|${el.is_weak ? 1 : 0}`;
}

export function attrFingerprint(el: Element, angle: number) {
  const offs = JSON.stringify(el.attr_offsets ?? {});
  return `${el.shape}|${Math.round(angle * 100)}|${(el.attributes ?? []).join("\n")}|${offs}`;
}

/** 属性名前缀：* = 主键（实线下划线），# = 部分键/弱属性（虚线下划线） */
function parseAttr(raw: string): { name: string; kind: AttrKind } {
  const s = String(raw ?? "").trim();
  if (s.startsWith("*")) return { name: s.replace(/^\*+/, "").trim(), kind: "pk" };
  if (s.startsWith("#")) return { name: s.replace(/^#+/, "").trim(), kind: "partial" };
  return { name: s, kind: "normal" };
}

function parseAttrs(el: Element) {
  return (el.attributes ?? []).map(parseAttr).filter((a) => a.name);
}

/** 取偶数尺寸：图形以中心定位时半宽/半高才是整数，避免描边落在半像素上发虚 */
function even(v: number) {
  return v % 2 ? v + 1 : v;
}

export function ellipseSize(label: string) {
  return { W: even(clamp(Math.round(textWidth(label, FONT.title) + 58), 76, 340)), H: 44 };
}

export function computeSize(el: Element) {
  const label = (el.label ?? "").trim() || TITLE[el.shape] || "";
  if (el.shape === "rectangle") {
    return { W: even(clamp(Math.round(textWidth(label, FONT.title) + FONT.padX * 2 + 16), 120, 340)), H: 44 };
  }
  if (el.shape === "ellipse") {
    return ellipseSize(label);
  }
  const W = even(clamp(Math.round(textWidth(label, FONT.title) + 72), 140, 380));
  return { W, H: even(Math.round(W * 0.58)) };
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

export function createElementGroup(el: Element): ElementVisual {
  const cx = el.position?.x ?? 0;
  const cy = el.position?.y ?? 0;
  const label = (el.label ?? "").trim() || TITLE[el.shape] || "";
  const { W, H } = computeSize(el);
  const hw = W / 2;
  const hh = H / 2;
  const children: unknown[] = [];
  let body: Rect | Ellipse | Polygon;
  let innerBody: Rect | undefined;

  if (el.shape === "rectangle") {
    body = new Rect({
      left: -hw,
      top: -hh,
      width: W,
      height: H,
      rx: 2,
      ry: 2,
      fill: FILL_TINT.pending,
      stroke: STROKE.pending,
      strokeWidth: STROKE_W.pending,
      selectable: false,
      evented: false,
    });
    children.push(body);
    if (el.is_weak) {
      innerBody = new Rect({
        left: -hw + 5,
        top: -hh + 5,
        width: W - 10,
        height: H - 10,
        rx: 1,
        ry: 1,
        fill: "transparent",
        stroke: STROKE.pending,
        strokeWidth: 1.4,
        selectable: false,
        evented: false,
      });
      children.push(innerBody);
    }
    children.push(
      txt(truncateTo(label, FONT.title, W - FONT.padX * 2), {
        left: 0,
        top: 0,
        originX: "center",
        originY: "center",
        fontSize: FONT.title,
        fontWeight: "bold",
        fill: "#0F172A",
      }),
    );
  } else if (el.shape === "ellipse") {
    body = new Ellipse({
      left: -hw,
      top: -hh,
      rx: hw,
      ry: hh,
      fill: FILL_TINT.pending,
      stroke: STROKE.pending,
      strokeWidth: STROKE_W.pending,
      selectable: false,
      evented: false,
    });
    children.push(body);
    children.push(
      txt(truncateTo(label, FONT.title, W - 40), {
        left: 0,
        top: 1,
        originX: "center",
        originY: "center",
        fontSize: FONT.title,
        fill: "#0F172A",
      }),
    );
  } else {
    body = new Polygon(
      [
        { x: 0, y: -hh },
        { x: hw, y: 0 },
        { x: 0, y: hh },
        { x: -hw, y: 0 },
      ],
      {
        fill: FILL_TINT.pending,
        stroke: STROKE.pending,
        strokeWidth: STROKE_W.pending,
        selectable: false,
        evented: false,
      },
    );
    children.push(body);
    children.push(
      txt(truncateTo(label, FONT.title, W - 40), {
        left: 0,
        top: 1,
        originX: "center",
        originY: "center",
        fontSize: FONT.title,
        fontWeight: "bold",
        fill: "#0F172A",
      }),
    );
  }

  const badge = new Circle({
    left: hw - 8,
    top: -hh - 2,
    radius: 6,
    fill: STROKE.pending,
    stroke: "#fff",
    strokeWidth: 1.5,
    selectable: false,
    evented: false,
  });
  children.push(badge);

  const group = new Group(children as never[], {
    originX: "center",
    originY: "center",
    objectCaching: false,
    left: cx,
    top: cy,
    selectable: true,
    evented: true,
    hasControls: false,
    lockRotation: true,
    lockScalingX: true,
    lockScalingY: true,
    borderColor: "#2563EB",
    cornerColor: "#2563EB",
  });
  (group as unknown as { erId: string; erKind: string }).erId = el.id;
  (group as unknown as { erKind: string }).erKind = "element";
  group.setCoords();

  return {
    group,
    body,
    badge,
    innerBody,
    w: W,
    h: H,
    shape: el.shape,
    fingerprint: elementFingerprint(el),
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
function edgeDist(shape: Element["shape"], W: number, H: number, a: number) {
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
 * 直到任意两个椭圆之间都留出 ATTR_PAD 的空隙。被手动拖过的椭圆保持原位，作为固定障碍。
 */
export function attrPlacements(el: Element, angle: number): AttrPlacement[] {
  const attrs = parseAttrs(el);
  const n = attrs.length;
  if (!n) return [];
  const { W, H } = computeSize(el);
  const span = Math.min(Math.PI * 0.9, Math.max(0, n - 1) * (Math.PI / 7.2));
  const items = attrs.map((attr, i) => {
    const size = ellipseSize(attr.name);
    const a = angle + (n === 1 ? 0 : (i / (n - 1) - 0.5) * span);
    const off = (el.attr_offsets ?? {})[String(i)];
    // 基准半径 = 实体边框距离 + 间隙 + 椭圆自身在该方向上的半径
    const r = edgeDist(el.shape, W, H, a) + ATTR_GAP + edgeDist("ellipse", size.W, size.H, a);
    return {
      name: attr.name,
      kind: attr.kind,
      w: size.W,
      h: size.H,
      a,
      r,
      fixed: !!off,
      ox: off ? off.x : Math.cos(a) * r,
      oy: off ? off.y : Math.sin(a) * r,
    };
  });

  const put = (p: (typeof items)[number]) => {
    p.ox = Math.cos(p.a) * p.r;
    p.oy = Math.sin(p.a) * p.r;
  };
  const clash = (p: (typeof items)[number], q: (typeof items)[number]) => {
    const dx = p.ox - q.ox;
    const dy = p.oy - q.oy;
    const hw = p.w / 2 + q.w / 2 + ATTR_PAD;
    const hh = p.h / 2 + q.h / 2 + ATTR_PAD;
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
 * 把实体/联系的 attributes 摊成它旁边的属性椭圆（陈氏画法）。
 * angle 是扇形基准方向（弧度，0=右，π=左）；没有属性时返回 null。
 */
export function createAttrNodes(
  el: Element,
  angle: number,
  cx: number,
  cy: number,
): AttrNodeVisual | null {
  const attrs = parseAttrs(el);
  if (!attrs.length) return null;
  const { W, H } = computeSize(el);
  const spots = attrPlacements(el, angle);
  const parts: Array<Ellipse | Line | Text> = [];
  const nodes: AttrNode[] = [];

  attrs.forEach((attr, i) => {
    const spot = spots[i];
    const ellipse = new Ellipse({
      rx: spot.w / 2,
      ry: spot.h / 2,
      fill: FILL_TINT.pending,
      stroke: STROKE.pending,
      strokeWidth: STROKE_W.pending,
      selectable: true,
      evented: true,
      hasControls: false,
      hasBorders: false,
      lockRotation: true,
      lockScalingX: true,
      lockScalingY: true,
      hoverCursor: "move",
    });
    (ellipse as unknown as { erAttrOwner?: string; erAttrIndex?: number }).erAttrOwner = el.id;
    (ellipse as unknown as { erAttrOwner?: string; erAttrIndex?: number }).erAttrIndex = i;
    const label = new Text(attr.name, {
      fontFamily: FONT.family,
      fontSize: FONT.title,
      fill: "#0F172A",
      underline: attr.kind === "pk",
      originX: "center",
      originY: "center",
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    const link = new Line([0, 0, 0, 0], {
      stroke: STROKE.pending,
      strokeWidth: 1.4,
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    const node: AttrNode = {
      ellipse,
      link,
      label,
      name: attr.name,
      ox: spot.ox,
      oy: spot.oy,
      w: spot.w,
      h: spot.h,
    };
    parts.push(link, ellipse, label);
    if (attr.kind === "partial") {
      const dash = new Line([0, 0, 0, 0], {
        stroke: "#334155",
        strokeWidth: 1.4,
        strokeDashArray: [3, 2],
        selectable: false,
        evented: false,
        objectCaching: false,
      });
      parts.push(dash);
      node.dash = dash;
    }
    nodes.push(node);
  });

  const vis: AttrNodeVisual = {
    parts,
    nodes,
    shape: el.shape,
    w: W,
    h: H,
    angle,
    fingerprint: attrFingerprint(el, angle),
  };
  layoutAttrNodes(vis, cx, cy);
  return vis;
}

/** 实体（cx, cy 为实体中心）移动后重新摆放属性椭圆与归属直线 */
export function layoutAttrNodes(vis: AttrNodeVisual, cx: number, cy: number) {
  for (const n of vis.nodes) {
    // 取整：椭圆中心落在整数像素上，描边才不会被抗锯齿糊掉
    const ex = Math.round(cx + n.ox);
    const ey = Math.round(cy + n.oy);
    n.ellipse.set({ left: ex - n.w / 2, top: ey - n.h / 2 });
    n.label.set({ left: ex, top: ey });
    const onEllipse = borderPoint("ellipse", n.w, n.h, ex, ey, cx, cy);
    const onShape = borderPoint(vis.shape, vis.w, vis.h, cx, cy, ex, ey);
    n.link.set({ x1: onEllipse.x, y1: onEllipse.y, x2: onShape.x, y2: onShape.y });
    if (n.dash) {
      const tw = textWidth(n.name, FONT.title);
      n.dash.set({ x1: ex - tw / 2, y1: ey + 12, x2: ex + tw / 2, y2: ey + 12 });
    }
    n.ellipse.setCoords();
  }
}

export function styleAttrNodes(vis: AttrNodeVisual, severity: PaintState) {
  for (const n of vis.nodes) {
    n.ellipse.set({
      stroke: STROKE[severity],
      strokeWidth: STROKE_W[severity],
      fill: FILL_TINT[severity],
    });
    n.link.set({ stroke: STROKE[severity] });
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