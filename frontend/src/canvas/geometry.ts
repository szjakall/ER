export function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

function wideChar(code: number) {
  return (
    (code >= 0x1100 && code <= 0x11ff) ||
    (code >= 0x2e80 && code <= 0x9fff) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xff60)
  );
}

export function textWidth(str: string, fontSize: number) {
  let w = 0;
  for (const ch of String(str ?? "")) {
    const code = ch.codePointAt(0) ?? 0;
    w += wideChar(code) ? fontSize : fontSize * 0.58;
  }
  return w;
}

export function truncateTo(str: string, fontSize: number, maxW: number) {
  const s = String(str ?? "");
  if (textWidth(s, fontSize) <= maxW) return s;
  let out = "";
  let w = 0;
  const ell = "…";
  const ellW = textWidth(ell, fontSize);
  for (const ch of s) {
    const cw = textWidth(ch, fontSize);
    if (w + cw + ellW > maxW) break;
    out += ch;
    w += cw;
  }
  return out + ell;
}

export function borderPoint(
  shape: string,
  w: number,
  h: number,
  fromX: number,
  fromY: number,
  tx: number,
  ty: number,
) {
  const dx = tx - fromX;
  const dy = ty - fromY;
  if (!dx && !dy) return { x: fromX, y: fromY };
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  let scale = 1;
  if (shape === "ellipse") {
    const rx = w / 2;
    const ry = h / 2;
    scale = 1 / Math.sqrt((ux * ux) / (rx * rx) + (uy * uy) / (ry * ry));
  } else if (shape === "rectangle") {
    const hw = w / 2;
    const hh = h / 2;
    const txr = ux !== 0 ? hw / Math.abs(ux) : Infinity;
    const tyr = uy !== 0 ? hh / Math.abs(uy) : Infinity;
    scale = Math.min(txr, tyr);
  } else {
    const hw = w / 2;
    const hh = h / 2;
    scale = 1 / (Math.abs(ux) / hw + Math.abs(uy) / hh);
  }
  return { x: fromX + ux * scale, y: fromY + uy * scale };
}

export function ribbonCorners(x1: number, y1: number, x2: number, y2: number, thick: number) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  return [
    { x: x1 + nx * thick, y: y1 + ny * thick },
    { x: x2 + nx * thick, y: y2 + ny * thick },
    { x: x2 - nx * thick, y: y2 - ny * thick },
    { x: x1 - nx * thick, y: y1 - ny * thick },
  ];
}
