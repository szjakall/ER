/**
 * 统一的文字测量 / 换行工具。
 *
 * 所有图形（实体、属性、联系、连线标签）都必须走这里，保证：
 * - 中文、英文、数字、中英混排用同一套测量；
 * - 默认不截断、不显示省略号；
 * - 超过最大宽度时按真实字宽换行，宽高由调用方据此扩大图形。
 *
 * 测量走浏览器 Canvas 2D 的 measureText，字体与 Fabric 的 Text 完全一致；
 * 在没有 DOM / Canvas 的环境（例如单元测试）回退到按字符宽度估算。
 */

import { FONT } from "./theme";

export interface TextLayout {
  /** 已经换好行的文本；渲染时用 "\n" 连接即可 */
  lines: string[];
  /** 最长一行的实际宽度 */
  width: number;
  /** 整个文本块的高度 */
  height: number;
  /** 单行行高（px） */
  lineHeight: number;
  fontSize: number;
}

export interface TextLayoutOptions {
  fontSize: number;
  weight?: number | string;
  /** 单行允许的最大宽度（px） */
  maxWidth: number;
  lineHeightRatio?: number;
}

/** Fabric Text 的 lineHeight 是 fontSize 的倍数，这里保持一致 */
export const LINE_HEIGHT_RATIO = 1.35;

let measureCtx: CanvasRenderingContext2D | null | undefined;
const widthCache = new Map<string, number>();

function ctx(): CanvasRenderingContext2D | null {
  if (measureCtx !== undefined) return measureCtx;
  try {
    const c = document.createElement("canvas");
    measureCtx = c.getContext("2d") ?? null;
  } catch {
    measureCtx = null;
  }
  return measureCtx;
}

function wideChar(code: number) {
  return (
    (code >= 0x1100 && code <= 0x11ff) ||
    (code >= 0x2e80 && code <= 0x9fff) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6)
  );
}

/** 无 Canvas 时的保守估算：宽字符按 1em，其余按 0.6em */
function fallbackWidth(text: string, fontSize: number) {
  let w = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    w += wideChar(code) ? fontSize : fontSize * 0.6;
  }
  return w;
}

function fontSpec(fontSize: number, weight: number | string) {
  return `${weight} ${fontSize}px ${FONT.family}`;
}

/** 单行文字的实际像素宽度。结果按「字体 + 字号 + 字重 + 文本」缓存。 */
export function measureTextWidth(
  text: string,
  fontSize: number,
  weight: number | string = 400,
): number {
  const s = String(text ?? "");
  if (!s) return 0;
  const key = `${fontSize}|${weight}|${s}`;
  const hit = widthCache.get(key);
  if (hit !== undefined) return hit;

  const c = ctx();
  let w: number;
  if (c) {
    try {
      c.font = fontSpec(fontSize, weight);
      w = c.measureText(s).width;
    } catch {
      w = fallbackWidth(s, fontSize);
    }
  } else {
    w = fallbackWidth(s, fontSize);
  }
  // 测量失败的极端情况（0 宽）也退回估算，避免图形被压成一条线
  if (!Number.isFinite(w) || w <= 0) w = fallbackWidth(s, fontSize);
  if (widthCache.size > 4000) widthCache.clear();
  widthCache.set(key, w);
  return w;
}

function isCjk(ch: string) {
  const code = ch.codePointAt(0) ?? 0;
  return wideChar(code);
}

/** 可以在该字符之后断行（CJK、空格、连字符、斜杠） */
function breakAfter(ch: string) {
  return isCjk(ch) || /[\s\-_/·、，。；：！？）】》]/.test(ch);
}

function splitLongParagraph(text: string, fontSize: number, weight: number | string, maxWidth: number) {
  const chars = Array.from(text);
  const lines: string[] = [];
  let line = "";
  let lastBreak = -1;

  const push = (value: string) => {
    const v = value.replace(/\s+$/u, "");
    if (v || lines.length === 0) lines.push(v);
  };
  const refreshBreak = () => {
    lastBreak = -1;
    for (let i = line.length - 1; i >= 0; i--) {
      if (breakAfter(line[i])) {
        lastBreak = i + 1;
        break;
      }
    }
  };

  for (const ch of chars) {
    const candidate = line + ch;
    if (!line || measureTextWidth(candidate, fontSize, weight) <= maxWidth) {
      line = candidate;
      if (breakAfter(ch)) lastBreak = line.length;
      continue;
    }

    if (lastBreak > 0 && lastBreak < line.length) {
      push(line.slice(0, lastBreak));
      line = line.slice(lastBreak).replace(/^\s+/u, "") + ch;
    } else {
      push(line);
      line = ch;
    }
    refreshBreak();
  }
  if (line || !lines.length) push(line);
  return lines;
}

/**
 * 把文字排成若干行。显式换行优先；没有超过 maxWidth 时绝不拆行。
 */
export function layoutText(text: string, opts: TextLayoutOptions): TextLayout {
  const fontSize = Math.max(1, opts.fontSize);
  const weight = opts.weight ?? 400;
  const maxWidth = Math.max(1, opts.maxWidth);
  const lineHeight = Math.round(fontSize * (opts.lineHeightRatio ?? LINE_HEIGHT_RATIO));
  const raw = String(text ?? "");
  const paragraphs = raw.split(/\r?\n/);
  const lines: string[] = [];

  for (const paragraph of paragraphs) {
    if (measureTextWidth(paragraph, fontSize, weight) <= maxWidth) {
      lines.push(paragraph);
      continue;
    }
    lines.push(...splitLongParagraph(paragraph, fontSize, weight, maxWidth));
  }

  if (!lines.length) lines.push("");
  const width = lines.reduce((m, line) => Math.max(m, measureTextWidth(line, fontSize, weight)), 0);
  return {
    lines,
    width,
    height: Math.max(lineHeight, lines.length * lineHeight),
    lineHeight,
    fontSize,
  };
}

/** 多行文本对象共用的 Fabric 参数 */
export function textBlockStyle(layout: TextLayout) {
  return {
    text: layout.lines.join("\n"),
    fontSize: layout.fontSize,
    lineHeight: LINE_HEIGHT_RATIO,
  };
}
