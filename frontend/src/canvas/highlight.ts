import type { PaintState } from "../protocol/types";
import { HALO } from "./theme";

/**
 * 严重度只用于「图形外部」的标注与面板，不参与图形本身的填充 / 描边。
 * 教材式 ER 图必须保持白底墨线，红色 / 橙色只说明检查结果。
 */
export function haloColor(state: PaintState): string | null {
  if (state === "error") return HALO.error;
  if (state === "warn") return HALO.warn;
  return null;
}

export function severityColor(state: PaintState): string {
  if (state === "error") return "#C92147";
  if (state === "warn") return "#C2410C";
  if (state === "ok") return "#15803D";
  return "#726B5E";
}
