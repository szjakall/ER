import type { PaintState } from "../protocol/types";

export const STROKE: Record<PaintState, string> = {
  error: "#E11D48",
  warn: "#F97316",
  ok: "#16A34A",
  pending: "#94A3B8",
};

export const FILL_TINT: Record<PaintState, string> = {
  error: "rgba(225,29,72,.08)",
  warn: "rgba(249,115,22,.08)",
  ok: "rgba(22,163,74,.06)",
  pending: "#ffffff",
};

export const STROKE_W: Record<PaintState, number> = {
  error: 3,
  warn: 3,
  ok: 2.4,
  pending: 2,
};

export const FONT = {
  title: 15,
  padX: 12,
  family: '"Microsoft YaHei", "PingFang SC", sans-serif',
};

export function applyBodyStyle(
  body: { set: (o: Record<string, unknown>) => void },
  badge: { set: (o: Record<string, unknown>) => void } | null,
  severity: PaintState,
) {
  body.set({
    stroke: STROKE[severity],
    strokeWidth: STROKE_W[severity],
    fill: FILL_TINT[severity],
  });
  badge?.set({ fill: STROKE[severity] });
}
