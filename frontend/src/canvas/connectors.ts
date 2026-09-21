import { Line, Polygon, Text } from "fabric";
import type { Canvas } from "fabric";
import type { Connection } from "../protocol/types";
import { borderPoint, ribbonCorners, textWidth, truncateTo } from "./geometry";
import { FONT, STROKE, STROKE_W } from "./highlight";
import type { ElementVisual } from "./shapes";

export interface ConnVisual {
  data: Connection;
  parts: Array<{ obj: Line | Polygon | Text; tag: string; i?: number }>;
  /** 连线中点（画布坐标），供"线上写基数"浮层定位 */
  mid: { x: number; y: number };
}

function labelText(value: string, size: number, weight: string | number = "normal") {
  return new Text(value, {
    fontFamily: FONT.family,
    fontSize: size,
    fontWeight: weight,
    originX: "center",
    originY: "center",
    selectable: false,
    evented: false,
    objectCaching: false,
    fill: "#475569",
  });
}

/**
 * 联系分支线：菱形联系 ↔ 矩形实体。
 * 只有这种线才写基数（1 / N / M）；实体连属性、联系连自身属性的线一律不写。
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

export function createConnectionVisual(canvas: Canvas, conn: Connection): ConnVisual {
  const parts: ConnVisual["parts"] = [];
  const segs = conn.type === "diamond_line" ? 2 : 1;
  for (let i = 0; i < segs; i++) {
    const line = new Line([0, 0, 1, 1], {
      stroke: STROKE.pending,
      strokeWidth: STROKE_W.pending,
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    parts.push({ obj: line, tag: "seg", i });
    const hit = new Polygon(
      [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
        { x: 0, y: 1 },
      ],
      {
        fill: "rgba(0,0,0,0)",
        stroke: "rgba(0,0,0,0)",
        selectable: true,
        evented: true,
        hasControls: false,
        lockMovementX: true,
        lockMovementY: true,
        objectCaching: false,
      },
    );
    (hit as unknown as { erId: string; erKind: string }).erId = conn.id;
    (hit as unknown as { erKind: string }).erKind = "connection";
    parts.push({ obj: hit, tag: "hit", i });
  }
  parts.push({
    obj: labelText(truncateTo(conn.label || "", FONT.title, 180), 12, "bold"),
    tag: "mid",
  });
  // Chen 记法：一条线上只写一个基数符号
  parts.push({ obj: labelText(String(conn.cardinality ?? ""), 16, "bold"), tag: "card" });
  const bang = new Text("!", {
    fontFamily: FONT.family,
    fontSize: 14,
    fontWeight: "bold",
    originX: "center",
    originY: "center",
    fill: STROKE.error,
    selectable: false,
    evented: false,
    objectCaching: false,
    visible: false,
  });
  parts.push({ obj: bang, tag: "bang" });
  for (const p of parts) canvas.add(p.obj);
  return { data: { ...conn }, parts, mid: { x: 0, y: 0 } };
}

export function layoutConnection(
  vis: ConnVisual,
  elems: Map<string, ElementVisual>,
) {
  const from = elems.get(vis.data.from);
  const to = elems.get(vis.data.to);
  if (!from || !to) return;
  const A = from.group.getCenterPoint();
  const B = to.group.getCenterPoint();
  const a = borderPoint(from.shape, from.w, from.h, A.x, A.y, B.x, B.y);
  const b = borderPoint(to.shape, to.w, to.h, B.x, B.y, A.x, A.y);
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  vis.mid = { x: mx, y: my };
  const len = Math.hypot(B.x - A.x, B.y - A.y) || 1;
  const ux = (B.x - A.x) / len;
  const uy = (B.y - A.y) / len;
  const canCard = isRelationBranchVisual(from, to);
  const segs =
    vis.data.type === "diamond_line"
      ? [
          [a, { x: mx, y: my }],
          [{ x: mx, y: my }, b],
        ]
      : [[a, b]];
  for (const p of vis.parts) {
    if (p.tag === "seg" || p.tag === "hit") {
      const s = segs[p.i ?? 0] ?? segs[0];
      if (p.tag === "seg") {
        (p.obj as Line).set({ x1: s[0].x, y1: s[0].y, x2: s[1].x, y2: s[1].y });
      } else {
        (p.obj as Polygon).set({
          points: ribbonCorners(s[0].x, s[0].y, s[1].x, s[1].y, 8),
        });
      }
      p.obj.setCoords();
    } else if (p.tag === "mid") {
      p.obj.set({ left: mx, top: my - 14 });
      (p.obj as Text).set("text", vis.data.label || "");
    } else if (p.tag === "card") {
      // 一条线只有一个符号，写在连线上方（取法向量中朝上的那一侧）
      const t = p.obj as Text;
      const card = vis.data.cardinality ? String(vis.data.cardinality) : "";
      t.set("text", card);
      t.set("visible", canCard && !!card);
      let nx = -uy;
      let ny = ux;
      if (ny > 0) {
        nx = -nx;
        ny = -ny;
      }
      t.set({ left: mx + nx * 16, top: my + ny * 16 });
    } else if (p.tag === "bang") {
      p.obj.set({ left: mx + 14, top: my - 14 });
    }
  }
}

export function styleConnection(vis: ConnVisual, severity: "pending" | "ok" | "warn" | "error") {
  const stroke = STROKE[severity];
  const sw = STROKE_W[severity];
  for (const p of vis.parts) {
    if (p.tag === "seg") p.obj.set({ stroke, strokeWidth: sw });
    if (p.tag === "mid" || p.tag === "card") p.obj.set({ fill: stroke });
    if (p.tag === "bang") p.obj.set({ visible: severity === "error" || severity === "warn", fill: stroke });
  }
}

export function connFingerprint(c: Connection) {
  return `${c.from}|${c.to}|${c.type}|${c.label}|${c.cardinality ?? ""}`;
}
