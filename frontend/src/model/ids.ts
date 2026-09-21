import type { Shape } from "../protocol/types";

const PREFIX: Record<Shape, "rect" | "ell" | "dia"> = {
  rectangle: "rect",
  ellipse: "ell",
  diamond: "dia",
};

const counters = { rect: 1, ell: 1, dia: 1, conn: 1 };

export function nextElementId(shape: Shape, taken: Set<string>): string {
  const prefix = PREFIX[shape];
  return bump(prefix, taken);
}

export function nextConnectionId(taken: Set<string>): string {
  return bump("conn", taken);
}

export function claimId(id: string) {
  const m = /^(rect|ell|dia|conn)_(\d+)$/.exec(id);
  if (!m) return;
  const key = m[1] as keyof typeof counters;
  counters[key] = Math.max(counters[key], Number(m[2]) + 1);
}

export function resetIds() {
  counters.rect = 1;
  counters.ell = 1;
  counters.dia = 1;
  counters.conn = 1;
}

function bump(prefix: keyof typeof counters, taken: Set<string>): string {
  let id: string;
  do {
    id = `${prefix}_${String(counters[prefix]).padStart(3, "0")}`;
    counters[prefix] += 1;
  } while (taken.has(id));
  return id;
}
