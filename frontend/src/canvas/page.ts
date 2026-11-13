import { Pattern, Rect } from "fabric";
import { pageBorderColorFor } from "./appearance";
import { DESK, INK, SNAP_STEP } from "./theme";

export type PageRatio = "free" | "16:9" | "4:3" | "3:2" | "1:1" | "golden" | "a4" | "a4p";

export interface PageOption {
  id: PageRatio;
  label: string;
  hint: string;
  value: number | null;
}

/** 黄金比例与 A4 用常见近似值，便于显示 */
export const PAGE_OPTIONS: PageOption[] = [
  { id: "free", label: "自由", hint: "无限画布", value: null },
  { id: "16:9", label: "16:9", hint: "宽屏 / 投影", value: 16 / 9 },
  { id: "4:3", label: "4:3", hint: "课堂投影", value: 4 / 3 },
  { id: "3:2", label: "3:2", hint: "相机画幅", value: 3 / 2 },
  { id: "1:1", label: "1:1", hint: "方形", value: 1 },
  { id: "golden", label: "黄金比例", hint: "1 : 1.618", value: 1.618 },
  { id: "a4", label: "A4 横向", hint: "297 : 210", value: 297 / 210 },
  { id: "a4p", label: "A4 纵向", hint: "210 : 297", value: 210 / 297 },
];

/**
 * 每种页面比例对应一套布局策略。
 * axis：分层主方向（x = 横向铺开，y = 纵向铺开）
 * targetAspect：内容整体旋转 / 拉伸的目标比例（= 页面比例）
 * pageLong：页面基准长边（内容简单时按此放大，内容复杂时让页面长大而不是压小字号）
 */
export type LayoutAxis = "x" | "y";

export interface LayoutProfile {
  id: PageRatio;
  axis: LayoutAxis;
  targetAspect: number;
  pageLong: number;
  /** 属性扇形优先朝向：wide = 左右，tall = 上下，compact = 全向 */
  attrBias: "wide" | "tall" | "compact";
}

export function layoutProfileFor(ratio: PageRatio): LayoutProfile {
  switch (ratio) {
    case "16:9":
      return { id: ratio, axis: "x", targetAspect: 16 / 9, pageLong: 1600, attrBias: "wide" };
    case "4:3":
      return { id: ratio, axis: "x", targetAspect: 4 / 3, pageLong: 1440, attrBias: "wide" };
    case "3:2":
      return { id: ratio, axis: "x", targetAspect: 3 / 2, pageLong: 1500, attrBias: "wide" };
    case "1:1":
      return { id: ratio, axis: "x", targetAspect: 1, pageLong: 1280, attrBias: "compact" };
    case "golden":
      return { id: ratio, axis: "x", targetAspect: 1.618, pageLong: 1554, attrBias: "wide" };
    case "a4":
      return { id: ratio, axis: "x", targetAspect: 297 / 210, pageLong: 1485, attrBias: "wide" };
    case "a4p":
      return { id: ratio, axis: "y", targetAspect: 210 / 297, pageLong: 1485, attrBias: "tall" };
    default:
      return { id: "free", axis: "x", targetAspect: 1.45, pageLong: 0, attrBias: "wide" };
  }
}

export const PAGE_RATIO_KEY = "erstudio.pageRatio";

/** 兼容旧版本保存的 a4 / 非法值：一律回退到自由画布 */
export function normalizeStoredRatio(value: string | null): PageRatio {
  if (!value) return "free";
  if (PAGE_OPTIONS.some((o) => o.id === value)) return value as PageRatio;
  return "free";
}

export function readStoredRatio(): PageRatio {
  try {
    return normalizeStoredRatio(localStorage.getItem(PAGE_RATIO_KEY));
  } catch {
    return "free";
  }
}

export function saveStoredRatio(ratio: PageRatio) {
  try {
    localStorage.setItem(PAGE_RATIO_KEY, ratio);
  } catch {
    /* localStorage 不可用时只影响持久化 */
  }
}

export function ratioValue(ratio: PageRatio): number | null {
  return PAGE_OPTIONS.find((o) => o.id === ratio)?.value ?? null;
}

export function ratioLabel(ratio: PageRatio): string {
  return PAGE_OPTIONS.find((o) => o.id === ratio)?.label ?? "自由";
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface PageBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const PAGE_MIN_W = 1080;
export const PAGE_MARGIN = 48;

/**
 * 页面 = 内容包围盒左右各留 MARGIN，再按比例补足短边。
 * 只在「选择比例 / 适应页面」时重算，绘制过程中不跳动。
 */
export function pageBoxFor(ratio: PageRatio, bounds: Bounds | null): PageBox | null {
  const r = ratioValue(ratio);
  if (!r) return null;
  if (!bounds) {
    const w = PAGE_MIN_W;
    return { x: 0, y: 0, w, h: Math.round(w / r) };
  }
  const contentW = Math.max(1, bounds.maxX - bounds.minX);
  const contentH = Math.max(1, bounds.maxY - bounds.minY);
  let w = Math.max(contentW + PAGE_MARGIN * 2, PAGE_MIN_W);
  let h = Math.max(contentH + PAGE_MARGIN * 2, w / r);
  if (h * r > w) w = h * r;
  if (w / r > h) h = w / r;
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  return {
    x: Math.round(cx - w / 2),
    y: Math.round(cy - h / 2),
    w: Math.round(w),
    h: Math.round(h),
  };
}

/** 页面对象：背景色 + 网格 + 1px 边框；自由模式隐藏 */
export function createPage(grid: Pattern | string, border = pageBorderColorFor("#FFFFFF")) {
  return new Rect({
    left: 0,
    top: 0,
    width: PAGE_MIN_W,
    height: 640,
    fill: grid,
    stroke: border,
    strokeWidth: 1,
    strokeUniform: true,
    selectable: false,
    evented: false,
    objectCaching: false,
    visible: false,
  });
}

/** 自由模式的大幅网格（透明底），铺满可视区并随缩放变化 */
export function createFreeGrid(grid: Pattern | string) {
  const size = 16000;
  return new Rect({
    left: -size / 2,
    top: -size / 2,
    width: size,
    height: size,
    fill: grid,
    selectable: false,
    evented: false,
    objectCaching: false,
    visible: true,
  });
}

export function snapToGrid(value: number, step = SNAP_STEP) {
  return Math.round(value / step) * step;
}

/** 默认桌面色；实际画布背景由 CanvasAppearance 决定 */
export const CANVAS_DESK = DESK;
export const PAGE_INK = INK;
