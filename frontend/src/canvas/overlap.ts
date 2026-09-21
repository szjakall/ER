import type { Connection, Element, Issue, Shape } from "../protocol/types";
import { borderPoint } from "./geometry";
import { attrBaseAngle, attrNodeBoxes, computeSize } from "./shapes";

/** 线段是否与轴对齐包围盒相交（Liang-Barsky 裁剪） */
function segmentHitsAABB(
  p1: { x: number; y: number },
  p2: { x: number; y: number },
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
): boolean {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  let t0 = 0;
  let t1 = 1;
  const clip = (p: number, q: number): boolean => {
    if (p === 0) return q >= 0;
    const r = q / p;
    if (p < 0) {
      if (r > t1) return false;
      if (r > t0) t0 = r;
    } else {
      if (r < t0) return false;
      if (r < t1) t1 = r;
    }
    return true;
  };
  return (
    clip(-dx, p1.x - minX) &&
    clip(dx, maxX - p1.x) &&
    clip(-dy, p1.y - minY) &&
    clip(dy, maxY - p1.y)
  );
}

/** 线段是否穿过某个图形（矩形精确；菱形/椭圆先过包围盒，再沿线段采样细化） */
export function segmentHitsShape(
  shape: Shape,
  w: number,
  h: number,
  cx: number,
  cy: number,
  p1: { x: number; y: number },
  p2: { x: number; y: number },
): boolean {
  const hw = Math.max(w / 2, 1);
  const hh = Math.max(h / 2, 1);
  if (!segmentHitsAABB(p1, p2, cx - hw, cy - hh, cx + hw, cy + hh)) return false;
  if (shape === "rectangle") return true;
  const N = 40;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const x = p1.x + (p2.x - p1.x) * t;
    const y = p1.y + (p2.y - p1.y) * t;
    const nx = (x - cx) / hw;
    const ny = (y - cy) / hh;
    if (shape === "ellipse") {
      if (nx * nx + ny * ny <= 1) return true;
    } else if (Math.abs(nx) + Math.abs(ny) <= 1) {
      return true;
    }
  }
  return false;
}

/**
 * 检测连线与"其它元素的图形 / 任何元素的属性椭圆"是否重合。
 * 返回：连线 id → 合成的问题列表（R20，红色）。
 */
export function detectOverlaps(
  elements: Element[],
  connections: Connection[],
): Map<string, Issue[]> {
  const out = new Map<string, Issue[]>();
  const byId = new Map(elements.map((e) => [e.id, e]));
  const sizeById = new Map(elements.map((e) => [e.id, computeSize(e)]));
  const boxesById = new Map<string, ReturnType<typeof attrNodeBoxes>>();
  for (const el of elements) {
    boxesById.set(el.id, attrNodeBoxes(el, attrBaseAngle(el, elements, connections)));
  }

  for (const c of connections) {
    const a = byId.get(c.from);
    const b = byId.get(c.to);
    if (!a || !b) continue;
    const sa = sizeById.get(a.id)!;
    const sb = sizeById.get(b.id)!;
    // 与渲染一致：取两个图形边框之间的可见线段
    const p1 = borderPoint(a.shape, sa.W, sa.H, a.position.x, a.position.y, b.position.x, b.position.y);
    const p2 = borderPoint(b.shape, sb.W, sb.H, b.position.x, b.position.y, a.position.x, a.position.y);

    let hitName = "";
    for (const el of elements) {
      // 图形本体：跳过这条连线自己的两个端点（线本来就贴着它们）
      if (el.id !== c.from && el.id !== c.to) {
        const s = sizeById.get(el.id)!;
        if (segmentHitsShape(el.shape, s.W, s.H, el.position.x, el.position.y, p1, p2)) {
          hitName = el.label || el.id;
          break;
        }
      }
      // 属性椭圆：连自己的端点的属性也不能压线
      for (const box of boxesById.get(el.id) ?? []) {
        if (segmentHitsShape("ellipse", box.w, box.h, box.cx, box.cy, p1, p2)) {
          hitName = `${el.label || el.id}·${box.name}`;
          break;
        }
      }
      if (hitName) break;
    }

    if (hitName) {
      out.set(c.id, [
        {
          rule_id: "R20",
          level: "error",
          message: `连线与「${hitName}」重叠 —— 请拖动元素或属性椭圆避开`,
        },
      ]);
    }
  }
  return out;
}
