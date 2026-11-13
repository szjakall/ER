import { Line, Text } from "fabric";
import type { Canvas } from "fabric";
import type { Connection } from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import type { ShapeStyle } from "./appearance";
import { borderPoint } from "./geometry";
import { FONT, GEO, SCALE, STROKE, WEIGHT } from "./theme";
import type { ElementVisual } from "./shapes";

export interface ConnVisual {
  data: Connection;
  parts: Array<{ obj: Line | Text; tag: string; i?: number }>;
  /** 连线中点（画布坐标），供"线上写基数"浮层定位 */
  mid: { x: number; y: number };
  /** 内容级缩放：字号、描边、基数偏移都跟图形共用同一个比例 */
  scale: number;
}

function labelText(
  value: string,
  size: number,
  weight: string | number,
  style: ShapeStyle,
  scale = 1,
) {
  return new Text(value, {
    fontFamily: FONT.family,
    fontSize: size * scale,
    fontWeight: weight,
    originX: "center",
    originY: "center",
    selectable: false,
    evented: false,
    objectCaching: false,
    fill: style.ink,
    // 背景色描边垫在字下面，压住连线时数字依然清晰
    stroke: style.knockout,
    strokeWidth: 4 * scale,
    paintFirst: "stroke",
  });
}

/**
 * 联系分支线：菱形联系 ↔ 矩形实体。
 * 只有这种线才写基数（1 / N / M / P）；实体连属性、联系连自身属性的线一律不写。
 */
export function isRelationBranchVisual(
  from: ElementVisual | undefined,
  to: ElementVisual | undefined,
): boolean {
  if (!from || !to) return false;
  return (
    (from.shape === "diamond" && to.shape === "rectangle") ||
    (from.shape === "rectangle" && to.shape === "diamond")
  );
}

export function createConnectionVisual(
  canvas: Canvas,
  conn: Connection,
  style: ShapeStyle,
  scale = 1,
): ConnVisual {
  const s = Math.max(SCALE.min, Math.min(SCALE.max, scale));
  const parts: ConnVisual["parts"] = [];
  const free = isFreeConnection(conn);
  // 自由端只有一条干净直线：不加中点文字、不加基数、不加任何端点装饰
  const segs = free ? 1 : conn.type === "diamond_line" ? 2 : 1;
  // 命中区域：整条连线用一条加粗透明线，坐标随布局更新
  const hit = new Line([0, 0, 1, 1], {
    // 极低不透明度的 16px 粗线：肉眼几乎不可见，但让命中检测只落在连线上，
    // 避免斜线的包围盒把大片空白区域都当成"选中了连线"（会挡住空白处拖拽平移）
    stroke: "rgba(0,0,0,0.02)",
    strokeWidth: 16 * s,
    strokeLineCap: "round",
    strokeUniform: true,
    selectable: true,
    evented: true,
    perPixelTargetFind: true,
    hasControls: false,
    hasBorders: !free,
    borderColor: style.selection,
    borderScaleFactor: 1,
    lockMovementX: true,
    lockMovementY: true,
    objectCaching: false,
  });
  (hit as unknown as { erId: string; erKind: string }).erId = conn.id;
  (hit as unknown as { erKind: string }).erKind = "connection";
  (hit as unknown as { erFree: boolean }).erFree = free;
  parts.push({ obj: hit, tag: "hit" });
  for (let i = 0; i < segs; i++) {
    const line = new Line([0, 0, 1, 1], {
      stroke: style.ink,
      strokeWidth: STROKE.link * s,
      // 可见连线随视口缩放，与文字 / 图形保持同一比例；命中线仍用固定屏幕宽度。
      strokeLineCap: "round",
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    parts.push({ obj: line, tag: "seg", i });
  }
  if (free) {
    for (const p of parts) canvas.add(p.obj);
    return { data: { ...conn, mode: "free" }, parts, mid: { x: 0, y: 0 }, scale: s };
  }
  // 联系名按教材写在菱形里，connection.label 只在有值时作为可选标签
  parts.push({
    obj: labelText(conn.label || "", 12, "bold", style, s),
    tag: "mid",
  });
  // Chen 记法：一条线上只写一个基数符号
  parts.push({
    obj: labelText(String(conn.cardinality ?? ""), FONT.card, WEIGHT.card, style, s),
    tag: "card",
  });
  for (const p of parts) canvas.add(p.obj);
  return { data: { ...conn, mode: "smart" }, parts, mid: { x: 0, y: 0 }, scale: s };
}

export function layoutConnection(vis: ConnVisual, elems: Map<string, ElementVisual>) {
  const from = elems.get(vis.data.from);
  if (!from) return;
  const free = isFreeConnection(vis.data);
  const A = from.group.getCenterPoint();

  let B: { x: number; y: number };
  let to: ElementVisual | undefined;
  if (free) {
    B = vis.data.free_end
      ? { x: vis.data.free_end.x, y: vis.data.free_end.y }
      : { x: A.x + 140, y: A.y };
  } else {
    to = elems.get(vis.data.to);
    if (!to) return;
    B = to.group.getCenterPoint();
  }

  const a = borderPoint(from.shape, from.w, from.h, A.x, A.y, B.x, B.y);
  // 自由端从终点指向起点，不需要第二段边框；终点就是用户点的位置
  const b = free
    ? { x: B.x, y: B.y }
    : borderPoint(to!.shape, to!.w, to!.h, B.x, B.y, A.x, A.y);
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  vis.mid = { x: mx, y: my };
  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  const ux = (b.x - a.x) / len;
  const uy = (b.y - a.y) / len;
  const canCard = !free && isRelationBranchVisual(from, to);
  const segs = free
    ? [[a, b]]
    : vis.data.type === "diamond_line"
      ? [
          [a, { x: mx, y: my }],
          [{ x: mx, y: my }, b],
        ]
      : [[a, b]];
  for (const p of vis.parts) {
    if (p.tag === "seg") {
      const s = segs[p.i ?? 0] ?? segs[0];
      (p.obj as Line).set({ x1: s[0].x, y1: s[0].y, x2: s[1].x, y2: s[1].y });
      p.obj.setCoords();
    } else if (p.tag === "hit") {
      (p.obj as Line).set({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
      p.obj.setCoords();
    } else if (p.tag === "mid") {
      const t = p.obj as Text;
      const show = !!vis.data.label;
      t.set({ text: vis.data.label || "", visible: show, left: mx, top: my - 14 * vis.scale });
    } else if (p.tag === "card") {
      // 基数写在**实体端**、贴线；一条线只有一个符号（取法向量中朝上的那一侧）
      const t = p.obj as Text;
      const card = vis.data.cardinality ? String(vis.data.cardinality) : "";
      const show = canCard && !!card;
      t.set("text", card);
      t.set("visible", show);
      if (!show) continue;
      const fromIsRect = from.shape === "rectangle";
      const entityEnd = fromIsRect ? a : b;
      const otherEnd = fromIsRect ? b : a;
      const ex = otherEnd.x - entityEnd.x;
      const ey = otherEnd.y - entityEnd.y;
      const elen = Math.hypot(ex, ey) || 1;
      const tEnd = Math.min((GEO.cardFromEnd * vis.scale) / elen, 0.35);
      let nx = -ey / elen;
      let ny = ex / elen;
      if (ny > 0) {
        nx = -nx;
        ny = -ny;
      }
      t.set({
        left: entityEnd.x + ex * tEnd + nx * GEO.cardOffset * vis.scale,
        top: entityEnd.y + ey * tEnd + ny * GEO.cardOffset * vis.scale,
      });
    }
  }
}

export function connFingerprint(c: Connection, styleKey = "") {
  const end = c.free_end ? `${Math.round(c.free_end.x)},${Math.round(c.free_end.y)}` : "";
  return `${c.mode ?? "smart"}|${c.from}|${c.to}|${end}|${c.type}|${c.label}|${c.cardinality ?? ""}|${styleKey}`;
}
