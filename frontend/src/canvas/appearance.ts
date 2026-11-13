/**
 * 画布外观：背景 / 网格 / 图形主题。
 *
 * 这些设置**只影响渲染**，不进入 ER 数据模型，也不会写进导出 JSON 或发给后端。
 * 图形主题在「教材规范（黑白）」与「展示主题（克制配色）」之间切换，
 * 背景颜色永远不自动改变图形样式。
 */

import { Pattern } from "fabric";
import { GRID_STEP, INK, PAPER, SEL } from "./theme";

export type GridMode = "dots" | "lines" | "off";
export type ShapeTheme = "textbook" | "display";

export interface CanvasAppearance {
  /** #RRGGBB */
  background: string;
  grid: GridMode;
  theme: ShapeTheme;
  /** 仅展示主题使用；教材规范仍是黑白 */
  accent: string;
}

export interface BackgroundPreset {
  id: string;
  label: string;
  value: string;
}

export const BACKGROUND_PRESETS: BackgroundPreset[] = [
  { id: "white", label: "纯白", value: "#FFFFFF" },
  { id: "warm", label: "暖白", value: "#FAF7F0" },
  { id: "gray", label: "浅灰", value: "#F1F3F5" },
  { id: "blue", label: "淡蓝", value: "#EDF4FB" },
  { id: "violet", label: "淡紫", value: "#F3EFFB" },
  { id: "dark", label: "深色", value: "#20242C" },
];

export interface AccentPreset {
  id: string;
  label: string;
  value: string;
}

/** 展示主题的克制配色：只用于图形填充的浅色晕染，描边与文字仍是深墨色 */
export const ACCENT_PRESETS: AccentPreset[] = [
  { id: "indigo", label: "靛蓝", value: "#4F46E5" },
  { id: "teal", label: "青灰", value: "#0F766E" },
  { id: "rust", label: "赭石", value: "#B45309" },
  { id: "plum", label: "紫梅", value: "#7E22CE" },
  { id: "slate", label: "石板", value: "#475569" },
];

export const DEFAULT_APPEARANCE: CanvasAppearance = {
  background: "#FFFFFF",
  grid: "dots",
  theme: "textbook",
  accent: ACCENT_PRESETS[0].value,
};

export const APPEARANCE_KEY = "erstudio.appearance";

const HEX = /^#[0-9a-f]{6}$/i;

export function isHexColor(value: unknown): value is string {
  return typeof value === "string" && HEX.test(value.trim());
}

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v));
}

function hexToRgb(hex: string) {
  const h = HEX.test(hex) ? hex.slice(1) : "FFFFFF";
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

function toHex(n: number) {
  return Math.round(clamp01(n / 255) * 255)
    .toString(16)
    .padStart(2, "0");
}

/** 把 accent 与白色混合；t 越大越浅 */
export function tint(hex: string, t: number) {
  const { r, g, b } = hexToRgb(hex);
  const k = 1 - clamp01(t);
  return `#${toHex(255 - (255 - r) * k)}${toHex(255 - (255 - g) * k)}${toHex(255 - (255 - b) * k)}`;
}

/** 相对亮度（WCAG），用于判断背景明暗并自动配网格颜色 */
export function luminance(hex: string) {
  const { r, g, b } = hexToRgb(hex);
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export function isDarkBackground(hex: string) {
  return luminance(hex) < 0.36;
}

/** 网格颜色自动跟随背景对比度 */
export function gridColorFor(background: string) {
  return isDarkBackground(background) ? "rgba(255,255,255,0.22)" : "rgba(28,26,22,0.16)";
}

export function pageBorderColorFor(background: string) {
  return isDarkBackground(background) ? "rgba(255,255,255,0.28)" : "rgba(28,26,22,0.18)";
}

export interface ShapeStyle {
  theme: ShapeTheme;
  ink: string;
  paper: string;
  entityFill: string;
  attrFill: string;
  relationFill: string;
  /** 连线标签挖空描边所用的底色 */
  knockout: string;
  selection: string;
  key: string;
}

export function shapeStyleFor(appearance: CanvasAppearance): ShapeStyle {
  const display = appearance.theme === "display";
  const accent = isHexColor(appearance.accent) ? appearance.accent : DEFAULT_APPEARANCE.accent;
  const entityFill = display ? tint(accent, 0.9) : PAPER;
  const attrFill = display ? tint(accent, 0.93) : PAPER;
  const relationFill = display ? tint(accent, 0.87) : PAPER;
  return {
    theme: appearance.theme,
    ink: INK,
    paper: PAPER,
    entityFill,
    attrFill,
    relationFill,
    knockout: appearance.background,
    selection: SEL,
    // 背景色也进入 key：连线文字的挖空描边要跟着换，避免在深色背景上留下白边
    key: `${appearance.theme}|${accent}|${entityFill}|${attrFill}|${relationFill}|${INK}|${appearance.background}`,
  };
}

/** 只接受合法字段；坏数据一律回退到默认值，避免 localStorage 损坏导致画布崩掉 */
export function normalizeAppearance(raw: unknown): CanvasAppearance {
  const o = (raw ?? {}) as Partial<CanvasAppearance>;
  const background = isHexColor(o.background) ? o.background.toUpperCase() : DEFAULT_APPEARANCE.background;
  const grid: GridMode = o.grid === "lines" || o.grid === "off" ? o.grid : "dots";
  const theme: ShapeTheme = o.theme === "display" ? "display" : "textbook";
  const accent = isHexColor(o.accent) ? o.accent.toUpperCase() : DEFAULT_APPEARANCE.accent;
  return { background, grid, theme, accent };
}

export function loadAppearance(): CanvasAppearance {
  try {
    const raw = localStorage.getItem(APPEARANCE_KEY);
    if (!raw) return { ...DEFAULT_APPEARANCE };
    return normalizeAppearance(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

export function saveAppearance(appearance: CanvasAppearance) {
  try {
    localStorage.setItem(APPEARANCE_KEY, JSON.stringify(normalizeAppearance(appearance)));
  } catch {
    /* localStorage 不可用时只影响持久化，不影响当前会话 */
  }
}

/**
 * 生成网格图案。withPaper=true 时同时铺背景色（用于页面），
 * false 时保持透明（用于自由画布的桌面背景）。
 */
export function makeGridPattern(
  background: string,
  mode: GridMode,
  withPaper: boolean,
): Pattern | null {
  if (mode === "off" && !withPaper) return null;
  const tile = document.createElement("canvas");
  tile.width = GRID_STEP;
  tile.height = GRID_STEP;
  const c = tile.getContext("2d");
  if (!c) return null;

  if (withPaper) {
    c.fillStyle = background;
    c.fillRect(0, 0, GRID_STEP, GRID_STEP);
  }
  if (mode === "off") {
    return new Pattern({ source: tile, repeat: "repeat" });
  }

  c.fillStyle = gridColorFor(background);
  if (mode === "lines") {
    // 0.5 偏移让 1px 线落在像素中心，缩放时不会发虚
    c.fillRect(0, 0, GRID_STEP, 1);
    c.fillRect(0, 0, 1, GRID_STEP);
  } else {
    c.beginPath();
    c.arc(GRID_STEP / 2, GRID_STEP / 2, 1, 0, Math.PI * 2);
    c.fill();
  }
  return new Pattern({ source: tile, repeat: "repeat" });
}
