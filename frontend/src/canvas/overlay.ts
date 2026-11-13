import { Ellipse, Line, Polygon, Rect } from "fabric";
import type { Shape } from "../protocol/types";
import { SEL } from "./theme";

export interface OutlineOptions {
  stroke?: string;
  strokeWidth?: number;
  fill?: string;
  opacity?: number;
  dash?: number[];
}

/**
 * 在图形外侧画一圈轮廓（悬停 / 选中提示 / 严重度外环共用）。
 * 图形本体永远不改色，所有提示都画在外部。
 */
export function outline(
  shape: Shape,
  w: number,
  h: number,
  cx: number,
  cy: number,
  pad: number,
  opts: OutlineOptions = {},
) {
  const hw = Math.max(1, w / 2 + pad);
  const hh = Math.max(1, h / 2 + pad);
  const common = {
    fill: opts.fill ?? "transparent",
    stroke: opts.stroke ?? SEL,
    strokeWidth: opts.strokeWidth ?? 1.5,
    strokeUniform: true,
    strokeDashArray: opts.dash ?? null,
    selectable: false,
    evented: false,
    objectCaching: false,
    opacity: opts.opacity ?? 1,
  };
  if (shape === "ellipse") {
    return new Ellipse({ left: cx - hw, top: cy - hh, rx: hw, ry: hh, ...common });
  }
  if (shape === "rectangle") {
    return new Rect({ left: cx - hw, top: cy - hh, width: hw * 2, height: hh * 2, ...common });
  }
  return new Polygon(
    [
      { x: 0, y: -hh },
      { x: hw, y: 0 },
      { x: 0, y: hh },
      { x: -hw, y: 0 },
    ],
    { left: cx, top: cy, originX: "center", originY: "center", ...common },
  );
}

/** 连线外环：沿同一线段叠一条更宽的半透明线，墨线仍然压在上面 */
export function lineHalo(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  stroke: string,
  width = 7,
) {
  return new Line([x1, y1, x2, y2], {
    stroke,
    strokeWidth: width,
    strokeLineCap: "round",
    selectable: false,
    evented: false,
    objectCaching: false,
  });
}

/**
 * 选中框：只画外框 + 四角控制点（由 Fabric 的 group 控制点负责实际缩放）。
 * 这里提供的是无控制点的轻量框，用于悬停与定位闪烁。
 */
export function selectionBox(shape: Shape, w: number, h: number, cx: number, cy: number) {
  return outline(shape, w, h, cx, cy, 4, { stroke: SEL, strokeWidth: 1.5 });
}
