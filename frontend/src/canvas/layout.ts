/**
 * 智能页面布局引擎（纯排版层）。
 *
 * 设计目标：
 * 1. 页面比例是布局约束，不是装饰边框；
 * 2. 从 Fabric 数据模型中抽取实体 / 属性 / 联系 / 连线 / 关联关系；
 * 3. 实体按图结构分层，联系落在相邻实体之间，属性围绕所属参与者；
 * 4. 先排核心图形，再排属性，最后整体旋转到目标页面比例并统一缩放；
 * 5. 只改 position / size / attr_offsets / layout_scale / free_end，
 *    绝不改 id / shape / label / attributes / cardinality 等业务语义。
 *
 * 坐标分两层：
 * - base 坐标：字号 14 / 15 的自然排版坐标，只用于计算；
 * - 输出坐标：page 坐标 × scale。图形、字号、描边、端点、基数共用同一个 scale。
 * viewportTransform 只负责把 page 装进屏幕，不参与内容缩放。
 */

import type { Connection, Element, Position, Shape } from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import { borderPoint } from "./geometry";
import { segmentHitsShape } from "./overlap";
import {
  ellipseSize,
  naturalCoreSize,
  shapeEdgeDistance,
} from "./shapes";
import { FONT, SCALE } from "./theme";
import {
  layoutProfileFor,
  ratioValue,
  type LayoutProfile,
  type PageBox,
  type PageRatio,
} from "./page";

export interface AutoLayoutStats {
  /** 核心图形 + 属性 / 独立属性椭圆的最终包围盒（页面坐标） */
  contentW: number;
  contentH: number;
  pageW: number;
  pageH: number;
  /** 内容包围盒面积 / 页面面积 */
  fill: number;
  /** 内容级缩放（字号、描边、尺寸共用） */
  scale: number;
  /** 最小正文字号（属性字号），低于 12 会触发告警 */
  minFont: number;
  /** 图形 / 属性椭圆之间的重叠对数 */
  overlaps: number;
  /** 连线交叉对数（只统计智能连线） */
  crossings: number;
  /** 最长连线长度（页面坐标） */
  longestEdge: number;
  /** 参与布局的参与者数（不含内嵌属性） */
  nodes: number;
}

export interface AutoLayoutResult {
  positions: Record<string, Position>;
  sizes: Record<string, { w: number; h: number }>;
  offsets: Record<string, Record<string, Position>>;
  freeEnds: Record<string, Position>;
  scale: number;
  pageBox: PageBox | null;
  stats: AutoLayoutStats;
  warnings: string[];
}

interface Box {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

interface LAttr {
  /** 在过滤掉空属性后的下标，与 shapes.parseAttrs 一致 */
  index: number;
  name: string;
  w: number;
  h: number;
  ox: number;
  oy: number;
  /** 非空表示这是独立的属性椭圆元素（satellite） */
  satelliteId?: string;
}

interface LNode {
  id: string;
  el: Element;
  shape: Shape;
  kind: "anchor" | "relation" | "satellite";
  w: number;
  h: number;
  x: number;
  y: number;
  deg: number;
  comp: number;
  attrs: LAttr[];
  /** 属性扇形需要的预留半径：分层排版时按它留出间距，属性才不会压到邻居 */
  halo: number;
  /** satellite：归属的实体 id */
  ownerId?: string;
}

interface Link {
  a: string;
  b: string;
  weight: number;
}

const CORE_GAP = 86;
const CROSS_GAP = 58;
const COMP_GAP = 110;
const REL_GAP = 34;
const ATTR_GAP = 20;
const ATTR_PAD = 12;
const OVERLAP_PAD = 10;

function round(v: number) {
  return Math.round(v);
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

function median(values: number[]) {
  if (!values.length) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

function attrName(raw: string) {
  return String(raw ?? "")
    .trim()
    .replace(/^\*+/, "")
    .replace(/^#+/, "")
    .trim();
}

function elementAttrs(el: Element) {
  const out: Array<{ index: number; name: string }> = [];
  (el.attributes ?? []).forEach((raw) => {
    const name = attrName(raw);
    if (name) out.push({ index: out.length, name });
  });
  return out;
}

/** 属性扇形大致需要的外扩半径（base 坐标），用于在分层排版时预留空间 */
function attributeHalo(attrs: LAttr[]) {
  if (!attrs.length) return 0;
  let maxDim = 0;
  for (const a of attrs) maxDim = Math.max(maxDim, a.w, a.h);
  // 预留太大会让页面按「空白」放大，整页适应视口后字号反而更小；
  // 这里的数值只保证属性扇形有基本落脚空间，剩余冲突由后段属性避让解决。
  return Math.min(140, Math.max(42, Math.sqrt(attrs.length) * 30 + maxDim * 0.22));
}

function coreBox(node: { x: number; y: number; w: number; h: number }): Box {
  return {
    minX: node.x - node.w / 2,
    minY: node.y - node.h / 2,
    maxX: node.x + node.w / 2,
    maxY: node.y + node.h / 2,
  };
}

function unionBox(a: Box, b: Box): Box {
  return {
    minX: Math.min(a.minX, b.minX),
    minY: Math.min(a.minY, b.minY),
    maxX: Math.max(a.maxX, b.maxX),
    maxY: Math.max(a.maxY, b.maxY),
  };
}

function boxWidth(b: Box) {
  return Math.max(1, b.maxX - b.minX);
}

function boxHeight(b: Box) {
  return Math.max(1, b.maxY - b.minY);
}

function overlapOf(a: Box, b: Box, pad = 0) {
  const ox = Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX) + pad;
  const oy = Math.min(a.maxY, b.maxY) - Math.max(a.minY, b.minY) + pad;
  if (ox <= 0 || oy <= 0) return null;
  return { ox, oy };
}

function rotatePoint(x: number, y: number, cx: number, cy: number, angle: number) {
  if (!angle) return { x, y };
  const dx = x - cx;
  const dy = y - cy;
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return { x: cx + dx * c - dy * s, y: cy + dx * s + dy * c };
}

interface ShapeProbe {
  shape: Shape;
  cx: number;
  cy: number;
  w: number;
  h: number;
}

function pointInProbe(s: ShapeProbe, x: number, y: number) {
  const hw = Math.max(1, s.w / 2 - 1.5);
  const hh = Math.max(1, s.h / 2 - 1.5);
  const dx = (x - s.cx) / hw;
  const dy = (y - s.cy) / hh;
  if (s.shape === "rectangle") return Math.abs(dx) <= 1 && Math.abs(dy) <= 1;
  if (s.shape === "ellipse") return dx * dx + dy * dy <= 1;
  return Math.abs(dx) + Math.abs(dy) <= 1;
}

function probeSamples(s: ShapeProbe) {
  const hw = Math.max(1, s.w / 2 - 1.5);
  const hh = Math.max(1, s.h / 2 - 1.5);
  const pts = [{ x: s.cx, y: s.cy }];
  if (s.shape === "rectangle") {
    pts.push(
      { x: s.cx - hw, y: s.cy - hh },
      { x: s.cx + hw, y: s.cy - hh },
      { x: s.cx + hw, y: s.cy + hh },
      { x: s.cx - hw, y: s.cy + hh },
    );
  } else if (s.shape === "ellipse") {
    for (let k = 0; k < 20; k++) {
      const a = (k / 20) * Math.PI * 2;
      pts.push({ x: s.cx + Math.cos(a) * hw, y: s.cy + Math.sin(a) * hh });
    }
  } else {
    pts.push(
      { x: s.cx, y: s.cy - hh },
      { x: s.cx + hw, y: s.cy },
      { x: s.cx, y: s.cy + hh },
      { x: s.cx - hw, y: s.cy },
    );
  }
  return pts;
}

/** 真实图形是否相交（矩形 / 椭圆 / 菱形），用于统计与告警，避免包围盒误报 */
function probesIntersect(a: ShapeProbe, b: ShapeProbe) {
  if (
    Math.abs(a.cx - b.cx) > (a.w + b.w) / 2 ||
    Math.abs(a.cy - b.cy) > (a.h + b.h) / 2
  ) {
    return false;
  }
  for (const p of probeSamples(a)) if (pointInProbe(b, p.x, p.y)) return true;
  for (const p of probeSamples(b)) if (pointInProbe(a, p.x, p.y)) return true;
  return false;
}

/** 严格相交（共享端点、共线都不算） */
function segmentsCross(
  a1: { x: number; y: number },
  a2: { x: number; y: number },
  b1: { x: number; y: number },
  b2: { x: number; y: number },
) {
  const d = (p: { x: number; y: number }, q: { x: number; y: number }, r: { x: number; y: number }) =>
    (r.x - p.x) * (q.y - p.y) - (r.y - p.y) * (q.x - p.x);
  const d1 = d(a1, a2, b1);
  const d2 = d(a1, a2, b2);
  const d3 = d(b1, b2, a1);
  const d4 = d(b1, b2, a2);
  return (d1 > 0 !== d2 > 0) && (d3 > 0 !== d4 > 0);
}

function crossingPairs(segments: Array<[string, string, { x: number; y: number }, { x: number; y: number }]>) {
  let count = 0;
  for (let i = 0; i < segments.length; i++) {
    for (let j = i + 1; j < segments.length; j++) {
      const [a1, a2, p1, p2] = segments[i];
      const [b1, b2, q1, q2] = segments[j];
      if (a1 === b1 || a1 === b2 || a2 === b1 || a2 === b2) continue;
      if (segmentsCross(p1, p2, q1, q2)) count += 1;
    }
  }
  return count;
}

/** 旋转后的轴对齐包围盒：图形本身不旋转，只旋转中心 */
function rotatedBoundsForBoxes(
  boxes: Array<{ x: number; y: number; w: number; h: number }>,
  angle: number,
  cx: number,
  cy: number,
): Box {
  let out: Box | null = null;
  for (const b of boxes) {
    const p = rotatePoint(b.x, b.y, cx, cy, angle);
    const box = {
      minX: p.x - b.w / 2,
      minY: p.y - b.h / 2,
      maxX: p.x + b.w / 2,
      maxY: p.y + b.h / 2,
    };
    out = out ? unionBox(out, box) : box;
  }
  return out ?? { minX: 0, minY: 0, maxX: 1, maxY: 1 };
}

/**
 * 选一个整体旋转角，让轴对齐包围盒尽量接近页面比例。
 * 这样 2 个实体 + 1 个联系的横向链在 16:9 下会轻微倾斜，在 1:1 下接近 45°，
 * 既不改变“联系位于实体之间”，又不会把所有内容挤在页面中间。
 */
function bestRotation(
  boxes: Array<{ x: number; y: number; w: number; h: number }>,
  targetAspect: number,
  cx: number,
  cy: number,
) {
  if (boxes.length < 2) return 0;
  let best = 0;
  let bestScore = Infinity;
  const step = (2 * Math.PI) / 90;
  for (let i = -44; i <= 44; i++) {
    const angle = i * step;
    const box = rotatedBoundsForBoxes(boxes, angle, cx, cy);
    const aspect = boxWidth(box) / boxHeight(box);
    const score =
      Math.abs(Math.log(aspect / targetAspect)) +
      // 轻微偏好小角度，避免无意义的大幅旋转
      Math.abs(angle) * 0.035;
    if (score < bestScore) {
      bestScore = score;
      best = angle;
    }
  }
  return Math.abs(best) < (2.5 * Math.PI) / 180 ? 0 : best;
}

/** 某方向的边界距离：实体用真实形状，属性椭圆用椭圆 */
function edgeAt(shape: Shape, w: number, h: number, angle: number) {
  return shapeEdgeDistance(shape, w, h, angle);
}

/** 环形摆布：同一参与者的内嵌属性 + 独立属性椭圆共用一个扇形 */
function ringOffsets(
  owner: LNode,
  items: Array<{ w: number; h: number }>,
  baseAngle: number,
  span: number,
  extraGap: number,
) {
  const n = items.length;
  const out: Array<{ ox: number; oy: number }> = [];
  const radius: number[] = [];
  const fullCircle = span >= Math.PI * 2 - 1e-6;
  const angleAt = (i: number) => {
    if (n === 1) return baseAngle;
    // 整圈时用 i/n，首尾不会落在同一个点上；扇形时用 i/(n-1) 覆盖两端
    return baseAngle + (fullCircle ? (i / n) * span : (i / (n - 1) - 0.5) * span);
  };
  items.forEach((item, i) => {
    const a = angleAt(i);
    const r =
      edgeAt(owner.shape, owner.w, owner.h, a) +
      ATTR_GAP +
      extraGap +
      edgeAt("ellipse", item.w, item.h, a);
    radius.push(r);
    out.push({ ox: Math.cos(a) * r, oy: Math.sin(a) * r });
  });

  // 同一扇形上相邻椭圆可能因为行高 / 多行文字互相压住：沿各自方向外推
  for (let iter = 0; iter < 18; iter++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = out[i].ox - out[j].ox;
        const dy = out[i].oy - out[j].oy;
        const needX = items[i].w / 2 + items[j].w / 2 + ATTR_PAD;
        const needY = items[i].h / 2 + items[j].h / 2 + ATTR_PAD;
        if ((dx * dx) / (needX * needX) + (dy * dy) / (needY * needY) >= 1) continue;
        for (const k of [i, j]) {
          radius[k] += 10;
          const a = angleAt(k);
          out[k] = { ox: Math.cos(a) * radius[k], oy: Math.sin(a) * radius[k] };
        }
        moved = true;
      }
    }
    if (!moved) break;
  }
  return out;
}

/** 属性扇形候选评分：避开其它图形、已排属性、连线 */
function scoreRing(
  owner: LNode,
  items: Array<{ w: number; h: number }>,
  offsets: Array<{ ox: number; oy: number }>,
  coreObstacles: Box[],
  placedAttrBoxes: Box[],
  segments: Array<[{ x: number; y: number }, { x: number; y: number }]>,
  baseAngle: number,
  preferred: number,
  profile: LayoutProfile,
) {
  let score = Math.abs(Math.atan2(Math.sin(baseAngle - preferred), Math.cos(baseAngle - preferred))) * 14;
  let bx0 = owner.x - owner.w / 2;
  let bx1 = owner.x + owner.w / 2;
  let by0 = owner.y - owner.h / 2;
  let by1 = owner.y + owner.h / 2;
  for (let i = 0; i < items.length; i++) {
    const cx = owner.x + offsets[i].ox;
    const cy = owner.y + offsets[i].oy;
    const box: Box = {
      minX: cx - items[i].w / 2,
      minY: cy - items[i].h / 2,
      maxX: cx + items[i].w / 2,
      maxY: cy + items[i].h / 2,
    };
    bx0 = Math.min(bx0, box.minX);
    bx1 = Math.max(bx1, box.maxX);
    by0 = Math.min(by0, box.minY);
    by1 = Math.max(by1, box.maxY);
    let hit = false;
    for (const ob of coreObstacles) {
      const o = overlapOf(box, ob, ATTR_PAD * 0.5);
      if (!o) continue;
      score += 4200 + o.ox * o.oy * 0.9;
      hit = true;
      break;
    }
    if (!hit) {
      for (const ob of placedAttrBoxes) {
        const o = overlapOf(box, ob, ATTR_PAD);
        if (!o) continue;
        score += 4200 + o.ox * o.oy * 0.9;
        break;
      }
    }
    for (const [p1, p2] of segments) {
      if (segmentHitsShape("ellipse", items[i].w + ATTR_PAD, items[i].h + ATTR_PAD, cx, cy, p1, p2)) {
        score += 900;
      }
    }
    // 轻微偏好紧凑，避免无意义的远距离属性
    score += Math.hypot(offsets[i].ox, offsets[i].oy) * 0.08;
  }
  // 让「参与者 + 属性」整体形状贴近页面比例：
  // A4 纵向会偏向上下扇形，16:9 会偏向左右扇形，减少页面内部大片空白。
  const aspect = Math.max(1, bx1 - bx0) / Math.max(1, by1 - by0);
  score += Math.abs(Math.log(aspect / profile.targetAspect)) * 260;
  return score;
}

/** 为某个参与者选择最佳属性扇形（含独立属性椭圆） */
function placeOwnerAttrs(
  owner: LNode,
  satellites: LNode[],
  coreObstacles: Box[],
  placedAttrBoxes: Box[],
  segments: Array<[{ x: number; y: number }, { x: number; y: number }]>,
  preferred: number,
  profile: LayoutProfile,
) {
  const items = [
    ...owner.attrs.map((a) => ({ w: a.w, h: a.h })),
    ...satellites.map((s) => ({ w: s.w, h: s.h })),
  ];
  if (!items.length) return;

  const n = items.length;
  const baseSpan = n <= 1 ? 0 : Math.min(Math.PI * 2, Math.max(1.15, (n - 1) * 0.5));
  const spans = n <= 1 ? [0] : [baseSpan, Math.min(Math.PI * 2, baseSpan * 1.25), Math.PI * 2];
  const extraGaps = [0, 20, 46, 80];
  const deltas = [0, -0.32, 0.32, -0.62, 0.62, -0.95, 0.95, -1.35, 1.35];

  let best: {
    offsets: Array<{ ox: number; oy: number }>;
    score: number;
  } | null = null;

  for (const span of spans) {
    for (const extra of extraGaps) {
      for (const d of deltas) {
        const baseAngle = preferred + d;
        const offsets = ringOffsets(owner, items, baseAngle, span, extra);
        let score = scoreRing(
          owner,
          items,
          offsets,
          coreObstacles,
          placedAttrBoxes,
          segments,
          baseAngle,
          preferred,
          profile,
        );
        // 极端分散只在属性很多时加分，避免 2 个属性被拆到页面两端
        if (n >= 5 && span >= Math.PI * 1.9) score -= 120;
        if (profile.attrBias === "compact" && n >= 4) score -= 40;
        if (!best || score < best.score) best = { offsets, score };
      }
    }
  }

  // 两侧分组：纵向页面把属性分到上/下，横向页面分到左/右。
  // 单个扇形在 A4 纵向会天然偏宽，导致页面上下留白；两侧分组能真正填满长边。
  if (n >= 2) {
    const axis =
      profile.attrBias === "tall" ? -Math.PI / 2 : profile.attrBias === "wide" ? 0 : -Math.PI / 4;
    for (const extra of extraGaps) {
      for (const groupSpan of [0.9, 1.25, 1.7, 2.2]) {
        const sideA: number[] = [];
        const sideB: number[] = [];
        for (let i = 0; i < n; i++) (i % 2 === 0 ? sideA : sideB).push(i);
        const offA = ringOffsets(
          owner,
          sideA.map((i) => items[i]),
          axis,
          sideA.length <= 1 ? 0 : groupSpan,
          extra,
        );
        const offB = ringOffsets(
          owner,
          sideB.map((i) => items[i]),
          axis + Math.PI,
          sideB.length <= 1 ? 0 : groupSpan,
          extra,
        );
        const offsets: Array<{ ox: number; oy: number }> = new Array(n);
        sideA.forEach((idx, k) => (offsets[idx] = offA[k]));
        sideB.forEach((idx, k) => (offsets[idx] = offB[k]));
        const score = scoreRing(
          owner,
          items,
          offsets,
          coreObstacles,
          placedAttrBoxes,
          segments,
          axis,
          preferred,
          profile,
        );
        if (!best || score < best.score) best = { offsets, score };
      }
    }
  }

  if (!best) return;
  owner.attrs.forEach((a, i) => {
    a.ox = best!.offsets[i].ox;
    a.oy = best!.offsets[i].oy;
  });
  satellites.forEach((s, i) => {
    const p = best!.offsets[owner.attrs.length + i];
    s.x = owner.x + p.ox;
    s.y = owner.y + p.oy;
  });
}

function layerPosition(
  layers: string[][],
  nodes: Map<string, LNode>,
  axis: "x" | "y",
) {
  let cursor = 0;
  for (const layer of layers) {
    if (!layer.length) continue;
    if (axis === "x") {
      // 层宽 = 图形 + 两侧属性预留；相邻层之间也各留一份 halo
      const maxSpanW = Math.max(...layer.map((id) => nodes.get(id)!.w + nodes.get(id)!.halo * 2));
      const x = cursor + (cursor === 0 ? maxSpanW / 2 : 0);
      cursor = x + maxSpanW / 2;
      const totalH =
        layer.reduce((sum, id) => sum + nodes.get(id)!.h + nodes.get(id)!.halo * 2, 0) +
        Math.max(0, layer.length - 1) * CROSS_GAP;
      let c = -totalH / 2;
      for (const id of layer) {
        const n = nodes.get(id)!;
        n.x = x;
        n.y = c + n.halo + n.h / 2;
        c += n.h + n.halo * 2 + CROSS_GAP;
      }
      cursor += CORE_GAP;
    } else {
      const maxSpanH = Math.max(...layer.map((id) => nodes.get(id)!.h + nodes.get(id)!.halo * 2));
      const y = cursor + (cursor === 0 ? maxSpanH / 2 : 0);
      cursor = y + maxSpanH / 2;
      const totalW =
        layer.reduce((sum, id) => sum + nodes.get(id)!.w + nodes.get(id)!.halo * 2, 0) +
        Math.max(0, layer.length - 1) * CROSS_GAP;
      let c = -totalW / 2;
      for (const id of layer) {
        const n = nodes.get(id)!;
        n.x = c + n.halo + n.w / 2;
        n.y = y;
        c += n.w + n.halo * 2 + CROSS_GAP;
      }
      cursor += CORE_GAP;
    }
  }
}

function compBounds(
  anchors: string[],
  relations: string[],
  nodes: Map<string, LNode>,
) {
  let box: Box | null = null;
  for (const id of anchors) {
    const n = nodes.get(id)!;
    const b = coreBox(n);
    const padded = {
      minX: b.minX - n.halo,
      minY: b.minY - n.halo,
      maxX: b.maxX + n.halo,
      maxY: b.maxY + n.halo,
    };
    box = box ? unionBox(box, padded) : padded;
  }
  if (box) {
    // 联系菱形通常落在实体之间，向四周留出菱形半径，避免打包时压到相邻组件
    let pad = 0;
    for (const id of relations) pad = Math.max(pad, Math.max(nodes.get(id)!.w, nodes.get(id)!.h) / 2 + 20);
    box = { minX: box.minX - pad, minY: box.minY - pad, maxX: box.maxX + pad, maxY: box.maxY + pad };
  }
  return box;
}

function componentScore(anchors: string[], links: Link[], nodes: Map<string, LNode>) {
  const segments: Array<[string, string, { x: number; y: number }, { x: number; y: number }]> = [];
  let length = 0;
  for (const l of links) {
    const a = nodes.get(l.a);
    const b = nodes.get(l.b);
    if (!a || !b) continue;
    segments.push([l.a, l.b, { x: a.x, y: a.y }, { x: b.x, y: b.y }]);
    length += Math.hypot(a.x - b.x, a.y - b.y);
  }
  let overlaps = 0;
  for (let i = 0; i < anchors.length; i++) {
    for (let j = i + 1; j < anchors.length; j++) {
      if (overlapOf(coreBox(nodes.get(anchors[i])!), coreBox(nodes.get(anchors[j])!), 10)) overlaps += 1;
    }
  }
  return crossingPairs(segments) * 900 + length * 0.18 + overlaps * 4000;
}

/** 单连通分量：BFS 分层 + 重心排序 + 同层交换降交叉 */
function layoutComponent(anchors: string[], links: Link[], nodes: Map<string, LNode>, profile: LayoutProfile) {
  if (!anchors.length) return;
  if (anchors.length === 1) {
    const n = nodes.get(anchors[0])!;
    n.x = 0;
    n.y = 0;
    return;
  }
  const adj = new Map<string, string[]>();
  for (const id of anchors) adj.set(id, []);
  for (const l of links) {
    if (!adj.has(l.a) || !adj.has(l.b)) continue;
    adj.get(l.a)!.push(l.b);
    adj.get(l.b)!.push(l.a);
  }
  const degree = (id: string) => adj.get(id)?.length ?? 0;
  const root = [...anchors].sort((a, b) => degree(b) - degree(a) || a.localeCompare(b))[0];

  const layerOf = new Map<string, number>();
  const queue = [root];
  layerOf.set(root, 0);
  const layers: string[][] = [[root]];
  while (queue.length) {
    const id = queue.shift()!;
    const d = layerOf.get(id) ?? 0;
    for (const nb of adj.get(id) ?? []) {
      if (layerOf.has(nb)) continue;
      layerOf.set(nb, d + 1);
      (layers[d + 1] ??= []).push(nb);
      queue.push(nb);
    }
  }
  // 图有环时可能仍有未访问节点（被已访问节点包围）：挂到最后一层
  for (const id of anchors) {
    if (layerOf.has(id)) continue;
    layerOf.set(id, layers.length);
    layers.push([id]);
  }

  const orderIndex = new Map<string, number>();
  const refreshIndex = () => {
    layers.forEach((layer) =>
      layer.forEach((id, i) => {
        orderIndex.set(id, i);
      }),
    );
  };
  const barycenterSort = (layer: string[], neighborLayer: string[]) => {
    const pos = new Map(neighborLayer.map((id, i) => [id, i]));
    return [...layer].sort((a, b) => {
      const score = (id: string) => {
        const ns = (adj.get(id) ?? []).filter((n) => pos.has(n));
        if (!ns.length) return orderIndex.get(id) ?? 0;
        return ns.reduce((s, n) => s + (pos.get(n) ?? 0), 0) / ns.length;
      };
      return score(a) - score(b) || a.localeCompare(b);
    });
  };

  refreshIndex();
  for (let round = 0; round < 3; round++) {
    for (let i = 1; i < layers.length; i++) layers[i] = barycenterSort(layers[i], layers[i - 1]);
    for (let i = layers.length - 2; i >= 0; i--) layers[i] = barycenterSort(layers[i], layers[i + 1]);
    refreshIndex();
  }

  const apply = () => {
    layerPosition(layers, nodes, profile.axis);
    // 以包围盒中心归零
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const id of anchors) {
      const n = nodes.get(id)!;
      minX = Math.min(minX, n.x - n.w / 2);
      maxX = Math.max(maxX, n.x + n.w / 2);
      minY = Math.min(minY, n.y - n.h / 2);
      maxY = Math.max(maxY, n.y + n.h / 2);
    }
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    for (const id of anchors) {
      const n = nodes.get(id)!;
      n.x -= cx;
      n.y -= cy;
    }
  };

  apply();
  let bestScore = componentScore(anchors, links, nodes);
  // 同层相邻交换：只接受能减少交叉 / 边长的改动
  for (let round = 0; round < 3; round++) {
    let improved = false;
    for (const layer of layers) {
      for (let i = 0; i + 1 < layer.length; i++) {
        [layer[i], layer[i + 1]] = [layer[i + 1], layer[i]];
        apply();
        const score = componentScore(anchors, links, nodes);
        if (score + 1e-6 < bestScore) {
          bestScore = score;
          improved = true;
        } else {
          [layer[i], layer[i + 1]] = [layer[i + 1], layer[i]];
          apply();
        }
      }
    }
    if (!improved) break;
  }
  apply();
}

function placeRelations(
  relationIds: string[],
  nodes: Map<string, LNode>,
  smart: Connection[],
  coreObstacles: Box[],
  compCenters: Map<number, { x: number; y: number }>,
) {
  const neighborsOf = new Map<string, string[]>();
  for (const id of relationIds) neighborsOf.set(id, []);
  for (const c of smart) {
    if (neighborsOf.has(c.from) && nodes.get(c.to)?.kind !== "satellite") neighborsOf.get(c.from)!.push(c.to);
    if (neighborsOf.has(c.to) && nodes.get(c.from)?.kind !== "satellite") neighborsOf.get(c.to)!.push(c.from);
  }

  // 同一对实体之间的多条联系：沿垂直方向错开，避免完全重叠
  const groups = new Map<string, string[]>();
  for (const id of relationIds) {
    const key = [...neighborsOf.get(id)!].sort().join("|") || `solo:${id}`;
    const list = groups.get(key) ?? [];
    list.push(id);
    groups.set(key, list);
  }

  for (const id of relationIds) {
    const node = nodes.get(id)!;
    const neighbors = neighborsOf.get(id)!
      .map((nid) => nodes.get(nid))
      .filter((n): n is LNode => !!n && n.kind !== "satellite");
    const group = groups.get([...neighborsOf.get(id)!].sort().join("|") || `solo:${id}`) ?? [id];
    let base = { x: 0, y: 0 };
    let dir = { x: 1, y: 0 };

    if (neighbors.length >= 2) {
      base = {
        x: neighbors.reduce((s, n) => s + n.x, 0) / neighbors.length,
        y: neighbors.reduce((s, n) => s + n.y, 0) / neighbors.length,
      };
      const a = neighbors[0];
      const b = neighbors[1];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      dir = { x: -dy / len, y: dx / len };
      if (group.length > 1) {
        const idx = group.indexOf(id);
        const off = (idx - (group.length - 1) / 2) * (node.h + 26);
        base.x += dir.x * off;
        base.y += dir.y * off;
      }
    } else if (neighbors.length === 1) {
      const n = neighbors[0];
      const center = compCenters.get(node.comp) ?? { x: n.x, y: n.y };
      let dx = n.x - center.x;
      let dy = n.y - center.y;
      if (!dx && !dy) {
        dx = 1;
        dy = 0;
      }
      const len = Math.hypot(dx, dy) || 1;
      dir = { x: dx / len, y: dy / len };
      base = {
        x: n.x + dir.x * (Math.max(n.w, n.h) / 2 + node.w / 2 + REL_GAP),
        y: n.y + dir.y * (Math.max(n.w, n.h) / 2 + node.h / 2 + REL_GAP),
      };
    } else {
      const center = compCenters.get(node.comp) ?? { x: 0, y: 0 };
      base = { x: center.x, y: center.y };
    }

    const candidates: Array<{ x: number; y: number }> = [base];
    for (const r of [22, 44, 72, 104, 140]) {
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        candidates.push({ x: base.x + Math.cos(a) * r, y: base.y + Math.sin(a) * r });
      }
    }
    let best = candidates[0];
    let bestScore = Infinity;
    for (const p of candidates) {
      const b = {
        minX: p.x - node.w / 2,
        minY: p.y - node.h / 2,
        maxX: p.x + node.w / 2,
        maxY: p.y + node.h / 2,
      };
      let score = Math.hypot(p.x - base.x, p.y - base.y) * 0.6;
      for (const ob of coreObstacles) {
        const o = overlapOf(b, ob, 12);
        if (o) score += 5000 + o.ox * o.oy;
      }
      if (score < bestScore) {
        bestScore = score;
        best = p;
      }
    }
    node.x = best.x;
    node.y = best.y;
    coreObstacles.push(coreBox(node));
  }
}

function fallbackPreferred(
  node: LNode,
  neighbors: LNode[],
  compCenter: { x: number; y: number } | undefined,
  profile: LayoutProfile,
) {
  const angles = neighbors.map((n) => Math.atan2(n.y - node.y, n.x - node.x));
  if (angles.length) {
    // 选与所有连线方向夹角都尽量大的"空闲方向"。
    // 联系菱形两端都有线时，简单取反方向会互相抵消，属性就会压在分支线上。
    let best = 0;
    let bestScore = -1;
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * Math.PI * 2 - Math.PI;
      let minDiff = Math.PI;
      for (const b of angles) {
        let d = Math.abs(a - b);
        if (d > Math.PI) d = Math.PI * 2 - d;
        if (d < minDiff) minDiff = d;
      }
      if (minDiff > bestScore) {
        bestScore = minDiff;
        best = a;
      }
    }
    return best;
  }
  const center = compCenter ?? { x: 0, y: 0 };
  let dx = node.x - center.x;
  let dy = node.y - center.y;
  if (Math.abs(dx) + Math.abs(dy) < 1) {
    if (profile.attrBias === "tall") {
      dx = 0;
      dy = -1;
    } else if (profile.attrBias === "wide") {
      dx = 1;
      dy = 0;
    } else {
      dx = 1;
      dy = 1;
    }
  }
  return Math.atan2(dy, dx);
}

/**
 * 属性 / 独立属性椭圆与连线分离：
 * R20 规则会把「连线压到属性椭圆」判成错误，所以自动布局最后再沿属性自身方向外推，
 * 直到它不再压线、也不压别的图形。实体位置保持不动。
 */
function separateAttrsFromLines(
  owners: string[],
  satellites: string[],
  nodes: Map<string, LNode>,
  smart: Connection[],
) {
  const segments = buildSegments(nodes, smart);
  if (!segments.length) return;
  const ownerSet = new Set(owners);
  const coreIds = [...nodes.values()].filter((n) => n.kind !== "satellite").map((n) => n.id);
  const attrBox = (n: LNode, a: LAttr): Box => ({
    minX: n.x + a.ox - a.w / 2,
    minY: n.y + a.oy - a.h / 2,
    maxX: n.x + a.ox + a.w / 2,
    maxY: n.y + a.oy + a.h / 2,
  });
  const satBox = (s: LNode): Box => coreBox(s);

  for (let pass = 0; pass < 3; pass++) {
    // 当前所有属性盒（含独立属性椭圆），用于避让
    const boxes: Array<{ key: string; box: Box }> = [];
    for (const id of owners) {
      const n = nodes.get(id)!;
      n.attrs.forEach((a) => boxes.push({ key: `a:${id}:${a.index}`, box: attrBox(n, a) }));
    }
    for (const id of satellites) {
      const s = nodes.get(id)!;
      boxes.push({ key: `s:${id}`, box: satBox(s) });
    }

    let moved = false;
    for (const id of owners) {
      const n = nodes.get(id)!;
      for (const a of n.attrs) {
        const key = `a:${id}:${a.index}`;
        const center = { x: n.x + a.ox, y: n.y + a.oy };
        const hitLine = segments.some(([p1, p2]) =>
          segmentHitsShape("ellipse", a.w, a.h, center.x, center.y, p1, p2),
        );
        if (!hitLine) continue;
        const clearAt = (nx: number, ny: number) => {
          if (segments.some(([p1, p2]) => segmentHitsShape("ellipse", a.w, a.h, nx, ny, p1, p2))) return false;
          const cand: Box = {
            minX: nx - a.w / 2,
            minY: ny - a.h / 2,
            maxX: nx + a.w / 2,
            maxY: ny + a.h / 2,
          };
          for (const ob of coreIds) {
            if (ob === id) continue;
            if (overlapOf(cand, coreBox(nodes.get(ob)!), 1)) return false;
          }
          for (const b of boxes) {
            if (b.key === key) continue;
            if (overlapOf(cand, b.box, 2)) return false;
          }
          return true;
        };
        const len = Math.hypot(a.ox, a.oy) || 1;
        const ux = a.ox / len;
        const uy = a.oy / len;
        let found = false;
        for (let step = 1; step <= 26 && !found; step++) {
          const nx = n.x + a.ox + ux * step * 10;
          const ny = n.y + a.oy + uy * step * 10;
          if (!clearAt(nx, ny)) continue;
          a.ox = nx - n.x;
          a.oy = ny - n.y;
          moved = true;
          found = true;
        }
        if (!found) {
          // 外推仍被挡住：绕参与者换一个角度（保持半径，必要时略放大）
          const baseA = Math.atan2(a.oy, a.ox);
          for (const rf of [1, 1.12, 1.28]) {
            for (let k = 1; k < 24 && !found; k++) {
              const aa = baseA + (k / 24) * Math.PI * 2;
              const rr = len * rf;
              const nx = n.x + Math.cos(aa) * rr;
              const ny = n.y + Math.sin(aa) * rr;
              if (!clearAt(nx, ny)) continue;
              a.ox = nx - n.x;
              a.oy = ny - n.y;
              moved = true;
              found = true;
            }
            if (found) break;
          }
        }
      }
    }
    for (const id of satellites) {
      const s = nodes.get(id)!;
      if (!s.ownerId) continue;
      const owner = nodes.get(s.ownerId);
      if (!owner || !ownerSet.has(owner.id)) continue;
      const key = `s:${id}`;
      const hitLine = segments.some(([p1, p2]) =>
        segmentHitsShape("ellipse", s.w, s.h, s.x, s.y, p1, p2),
      );
      if (!hitLine) continue;
      const dx0 = s.x - owner.x;
      const dy0 = s.y - owner.y;
      const len = Math.hypot(dx0, dy0) || 1;
      const ux = dx0 / len;
      const uy = dy0 / len;
      const clearAt = (nx: number, ny: number) => {
        if (segments.some(([p1, p2]) => segmentHitsShape("ellipse", s.w, s.h, nx, ny, p1, p2))) return false;
        const cand: Box = {
          minX: nx - s.w / 2,
          minY: ny - s.h / 2,
          maxX: nx + s.w / 2,
          maxY: ny + s.h / 2,
        };
        for (const ob of coreIds) {
          if (ob === id) continue;
          if (overlapOf(cand, coreBox(nodes.get(ob)!), 1)) return false;
        }
        for (const b of boxes) {
          if (b.key === key) continue;
          if (overlapOf(cand, b.box, 2)) return false;
        }
        return true;
      };
      let found = false;
      for (let step = 1; step <= 26 && !found; step++) {
        const nx = s.x + ux * step * 10;
        const ny = s.y + uy * step * 10;
        if (!clearAt(nx, ny)) continue;
        s.x = nx;
        s.y = ny;
        moved = true;
        found = true;
      }
      if (!found) {
        const baseA = Math.atan2(dy0, dx0);
        for (const rf of [1, 1.12, 1.28]) {
          for (let k = 1; k < 24 && !found; k++) {
            const aa = baseA + (k / 24) * Math.PI * 2;
            const nx = owner.x + Math.cos(aa) * len * rf;
            const ny = owner.y + Math.sin(aa) * len * rf;
            if (!clearAt(nx, ny)) continue;
            s.x = nx;
            s.y = ny;
            moved = true;
            found = true;
          }
          if (found) break;
        }
      }
    }
    if (!moved) break;
  }
}

function buildSegments(nodes: Map<string, LNode>, smart: Connection[]) {
  const out: Array<[{ x: number; y: number }, { x: number; y: number }]> = [];
  for (const c of smart) {
    const a = nodes.get(c.from);
    const b = nodes.get(c.to);
    if (!a || !b) continue;
    const p1 = borderPoint(a.shape, a.w, a.h, a.x, a.y, b.x, b.y);
    const p2 = borderPoint(b.shape, b.w, b.h, b.x, b.y, a.x, a.y);
    out.push([p1, p2]);
  }
  return out;
}

/** 页面尺寸：内容包围盒 + 页边距，再补足目标比例 */
function fitPage(
  contentW: number,
  contentH: number,
  ratio: PageRatio,
  profile: LayoutProfile,
) {
  const r = ratioValue(ratio);
  if (!r) return null;
  const targetLong = profile.pageLong || 1600;
  let scale = clamp(targetLong / Math.max(1, Math.max(contentW, contentH)), SCALE.min, SCALE.max);
  let pageW = 0;
  let pageH = 0;
  let margin = 48;
  for (let i = 0; i < 5; i++) {
    const w0 = contentW * scale;
    const h0 = contentH * scale;
    let w = Math.max(w0 + margin * 2, (h0 + margin * 2) * r);
    let h = w / r;
    if (w / r > h) h = w / r;
    pageW = w;
    pageH = h;
    const next = clamp(Math.min(w, h) * 0.05, 24, 90);
    if (Math.abs(next - margin) < 0.5) break;
    margin = next;
  }
  if (!pageW || !pageH) return null;
  return { scale, pageW, pageH, margin, contentW: contentW * scale, contentH: contentH * scale, grown: false };
}

/**
 * 把内容装进「当前页面」：优先保持现有画布宽高（只缩放到刚好填满可用区域）。
 * 只有内容多到最小字号都放不下时，才按比例扩大工作区域并标记 grown。
 * 这是自动布局与画布尺寸解耦的关键：自动布局默认不改页面宽高。
 */
function fitIntoPage(contentW: number, contentH: number, pageW: number, pageH: number) {
  const margin = clamp(Math.min(pageW, pageH) * 0.05, 24, 90);
  const usableW = Math.max(1, pageW - margin * 2);
  const usableH = Math.max(1, pageH - margin * 2);
  let scale = Math.min(
    usableW / Math.max(1, contentW),
    usableH / Math.max(1, contentH),
    SCALE.max,
  );
  let w = pageW;
  let h = pageH;
  let grown = false;
  if (!Number.isFinite(scale) || scale < SCALE.min) {
    scale = SCALE.min;
    const needW = contentW * scale + margin * 2;
    const needH = contentH * scale + margin * 2;
    const r = pageW / pageH;
    w = Math.max(pageW, needW, needH * r);
    h = w / r;
    if (h < needH) {
      h = needH;
      w = h * r;
    }
    grown = true;
  }
  return { scale, pageW: w, pageH: h, margin, contentW: contentW * scale, contentH: contentH * scale, grown };
}

export function computeAutoLayout(
  elements: Element[],
  connections: Connection[],
  ratio: PageRatio,
  preferredPage?: PageBox | null,
): AutoLayoutResult | null {
  if (!elements.length) return null;
  const profile = layoutProfileFor(ratio);
  const ratioAspect = ratioValue(ratio);
  const smart = connections.filter(
    (c) => !isFreeConnection(c) && !!c.to && elements.some((e) => e.id === c.from) && elements.some((e) => e.id === c.to),
  );
  const oldPos = new Map(elements.map((e) => [e.id, { ...e.position }]));

  const nodes = new Map<string, LNode>();
  for (const el of elements) {
    const { W, H } = naturalCoreSize(el);
    const attrs: LAttr[] = elementAttrs(el).map((a) => {
      const size = ellipseSize(a.name, 1);
      return { index: a.index, name: a.name, w: size.W, h: size.H, ox: 0, oy: 0 };
    });
    nodes.set(el.id, {
      id: el.id,
      el,
      shape: el.shape,
      kind: el.shape === "diamond" ? "relation" : "anchor",
      w: W,
      h: H,
      x: el.position?.x ?? 0,
      y: el.position?.y ?? 0,
      deg: 0,
      comp: -1,
      attrs,
      halo: attributeHalo(attrs),
    });
  }

  for (const c of smart) {
    const a = nodes.get(c.from);
    const b = nodes.get(c.to);
    if (a) a.deg += 1;
    if (b) b.deg += 1;
  }

  const rectIds = [...nodes.values()].filter((n) => n.shape === "rectangle").map((n) => n.id);

  // 独立属性椭圆：没有显式连线时，归到最近的实体旁边，不单独占一个图节点
  for (const n of nodes.values()) {
    if (n.shape !== "ellipse" || n.deg !== 0 || !rectIds.length) continue;
    let best: LNode | null = null;
    let bestD = Infinity;
    for (const rid of rectIds) {
      const r = nodes.get(rid)!;
      const d = Math.hypot(r.x - n.x, r.y - n.y);
      if (d < bestD) {
        bestD = d;
        best = r;
      }
    }
    if (best) {
      n.kind = "satellite";
      n.ownerId = best.id;
    }
  }

  let anchors = [...nodes.values()].filter((n) => n.kind === "anchor").map((n) => n.id);
  let relations = [...nodes.values()].filter((n) => n.kind === "relation").map((n) => n.id);
  // 全是菱形（少见）时退化：菱形之间直接连线
  if (!anchors.length && relations.length) {
    anchors = [...relations];
    relations = [];
    for (const id of anchors) nodes.get(id)!.kind = "anchor";
  }

  const anchorSet = new Set(anchors);
  const relationSet = new Set(relations);
  const linkMap = new Map<string, Link>();
  const addLink = (a: string, b: string, weight: number) => {
    if (a === b) return;
    const key = a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
    const cur = linkMap.get(key);
    if (cur) cur.weight += weight;
    else linkMap.set(key, { a, b, weight });
  };

  // 直接连线（不含菱形）→ 实体图边
  for (const c of smart) {
    if (!anchorSet.has(c.from) || !anchorSet.has(c.to)) continue;
    if (relationSet.has(c.from) || relationSet.has(c.to)) continue;
    addLink(c.from, c.to, 1);
  }

  // 经过联系菱形：把菱形两侧的参与者投影成实体图边
  const relationNeighbors = new Map<string, string[]>();
  for (const rid of relations) relationNeighbors.set(rid, []);
  for (const c of smart) {
    if (relationSet.has(c.from) && anchorSet.has(c.to)) relationNeighbors.get(c.from)!.push(c.to);
    if (relationSet.has(c.to) && anchorSet.has(c.from)) relationNeighbors.get(c.to)!.push(c.from);
    if (relationSet.has(c.from) && relationSet.has(c.to)) addLink(c.from, c.to, 1);
  }
  for (const [, neighbors] of relationNeighbors) {
    const uniq = [...new Set(neighbors)];
    if (uniq.length < 2) continue;
    const weight = 1 / (uniq.length - 1);
    for (let i = 0; i < uniq.length; i++) {
      for (let j = i + 1; j < uniq.length; j++) addLink(uniq[i], uniq[j], weight);
    }
  }
  const links = [...linkMap.values()];

  // 连通分量
  const adj = new Map<string, string[]>();
  for (const id of anchors) adj.set(id, []);
  for (const l of links) {
    if (!adj.has(l.a) || !adj.has(l.b)) continue;
    adj.get(l.a)!.push(l.b);
    adj.get(l.b)!.push(l.a);
  }
  const comps: string[][] = [];
  const seen = new Set<string>();
  for (const id of anchors) {
    if (seen.has(id)) continue;
    const comp: string[] = [];
    const queue = [id];
    seen.add(id);
    while (queue.length) {
      const cur = queue.shift()!;
      comp.push(cur);
      for (const nb of adj.get(cur) ?? []) {
        if (seen.has(nb)) continue;
        seen.add(nb);
        queue.push(nb);
      }
    }
    comps.push(comp);
  }
  comps.forEach((comp, i) => comp.forEach((id) => (nodes.get(id)!.comp = i)));

  // 菱形归属到邻居实体所在分量；没有邻居时按原始位置就近
  for (const rid of relations) {
    const node = nodes.get(rid)!;
    const ns = [...new Set(relationNeighbors.get(rid) ?? [])];
    if (ns.length) {
      node.comp = nodes.get(ns[0])!.comp;
    } else if (comps.length) {
      let best = 0;
      let bestD = Infinity;
      comps.forEach((comp, i) => {
        for (const id of comp) {
          const n = nodes.get(id)!;
          const d = Math.hypot(n.x - node.x, n.y - node.y);
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        }
      });
      node.comp = best;
    }
  }

  // 每个分量先独立分层排版
  comps.forEach((comp, i) => {
    const compLinks = links.filter((l) => nodes.get(l.a)!.comp === i && nodes.get(l.b)!.comp === i);
    layoutComponent(comp, compLinks, nodes, profile);
  });

  // 分量打包：按面积从大到小，行式货架
  const compBoxes: Array<{ i: number; box: Box }> = comps.map((comp, i) => {
    const b = compBounds(
      comp,
      relations.filter((id) => nodes.get(id)!.comp === i),
      nodes,
    );
    return { i, box: b ?? { minX: 0, minY: 0, maxX: 1, maxY: 1 } };
  });
  const totalArea = compBoxes.reduce((s, c) => s + boxWidth(c.box) * boxHeight(c.box), 0);
  const targetWidth = Math.max(
    380,
    Math.sqrt(Math.max(1, totalArea) * (ratioAspect ?? 1.45)) * 1.15,
  );
  compBoxes.sort((a, b) => boxWidth(b.box) * boxHeight(b.box) - boxWidth(a.box) * boxHeight(a.box));
  let cursorX = 0;
  let cursorY = 0;
  let rowH = 0;
  const compOffsets = new Map<number, { x: number; y: number }>();
  for (const c of compBoxes) {
    const w = boxWidth(c.box);
    const h = boxHeight(c.box);
    if (cursorX > 0 && cursorX + w > targetWidth) {
      cursorX = 0;
      cursorY += rowH + COMP_GAP;
      rowH = 0;
    }
    compOffsets.set(c.i, {
      x: cursorX - c.box.minX,
      y: cursorY - c.box.minY,
    });
    cursorX += w + COMP_GAP;
    rowH = Math.max(rowH, h);
  }
  for (const [i, off] of compOffsets) {
    for (const id of comps[i]) {
      const n = nodes.get(id)!;
      n.x += off.x;
      n.y += off.y;
    }
  }

  // 全局居中
  let world: Box | null = null;
  for (const id of anchors) {
    const b = coreBox(nodes.get(id)!);
    world = world ? unionBox(world, b) : b;
  }
  if (world) {
    const cx = (world.minX + world.maxX) / 2;
    const cy = (world.minY + world.maxY) / 2;
    for (const id of anchors) {
      const n = nodes.get(id)!;
      n.x -= cx;
      n.y -= cy;
    }
  }

  const compCenters = new Map<number, { x: number; y: number }>();
  comps.forEach((comp, i) => {
    const xs = comp.map((id) => nodes.get(id)!.x);
    const ys = comp.map((id) => nodes.get(id)!.y);
    compCenters.set(i, {
      x: xs.reduce((s, v) => s + v, 0) / Math.max(1, xs.length),
      y: ys.reduce((s, v) => s + v, 0) / Math.max(1, ys.length),
    });
  });

  const coreObstacles: Box[] = anchors.map((id) => coreBox(nodes.get(id)!));
  placeRelations(relations, nodes, smart, coreObstacles, compCenters);

  // 先旋转「核心图形」再排属性：
  // 图形本身不旋转，旋转后必须重新留出轴对齐间距，否则属性会压到实体上。
  let spin = 0;
  if (ratioAspect && anchors.length + relations.length > 1) {
    const coreShapes: Array<{ x: number; y: number; w: number; h: number }> = [...anchors, ...relations].map((id) => {
      const n = nodes.get(id)!;
      return { x: n.x, y: n.y, w: n.w, h: n.h };
    });
    const pre = coreShapes.reduce<Box | null>((acc, b) => {
      const box = { minX: b.x - b.w / 2, minY: b.y - b.h / 2, maxX: b.x + b.w / 2, maxY: b.y + b.h / 2 };
      return acc ? unionBox(acc, box) : box;
    }, null);
    const preCx = pre ? (pre.minX + pre.maxX) / 2 : 0;
    const preCy = pre ? (pre.minY + pre.maxY) / 2 : 0;
    spin = bestRotation(coreShapes, ratioAspect, preCx, preCy);
    if (spin) {
      for (const id of [...anchors, ...relations]) {
        const n = nodes.get(id)!;
        const p = rotatePoint(n.x, n.y, preCx, preCy, spin);
        n.x = p.x;
        n.y = p.y;
      }
    }
  }
  coreObstacles.length = 0;
  for (const id of anchors) coreObstacles.push(coreBox(nodes.get(id)!));
  for (const rid of relations) coreObstacles.push(coreBox(nodes.get(rid)!));

  // 核心图形去重叠（联系菱形允许小幅让位；实体尽量保持分层位置）
  for (let iter = 0; iter < 60; iter++) {
    let moved = false;
    for (let i = 0; i < coreObstacles.length; i++) {
      for (let j = i + 1; j < coreObstacles.length; j++) {
        const o = overlapOf(coreObstacles[i], coreObstacles[j], 14);
        if (!o) continue;
        const dx = (coreObstacles[i].minX + coreObstacles[i].maxX - coreObstacles[j].minX - coreObstacles[j].maxX) / 2;
        const dy = (coreObstacles[i].minY + coreObstacles[i].maxY - coreObstacles[j].minY - coreObstacles[j].maxY) / 2;
        const pushX = o.ox * (dx >= 0 ? 1 : -1) * 0.5;
        const pushY = o.oy * (dy >= 0 ? 1 : -1) * 0.5;
        if (o.ox < o.oy) {
          coreObstacles[i] = shiftBox(coreObstacles[i], pushX, 0);
          coreObstacles[j] = shiftBox(coreObstacles[j], -pushX, 0);
        } else {
          coreObstacles[i] = shiftBox(coreObstacles[i], 0, pushY);
          coreObstacles[j] = shiftBox(coreObstacles[j], 0, -pushY);
        }
        moved = true;
      }
    }
    if (!moved) break;
  }
  // 盒模型推开的位移写回节点（按 id 顺序：anchors 在前，relations 在后）
  const coreIds = [...anchors, ...relations];
  coreIds.forEach((id, i) => {
    const n = nodes.get(id)!;
    const b = coreObstacles[i];
    n.x = (b.minX + b.maxX) / 2;
    n.y = (b.minY + b.maxY) / 2;
  });

  // 属性 / 独立属性椭圆
  const centerOfComp = (comp: number) => compCenters.get(comp);
  const placedAttrBoxes: Box[] = [];
  const segments = buildSegments(nodes, smart);
  const ownerIds = [...anchors, ...relations].filter((id) => {
    const n = nodes.get(id)!;
    const sats = [...nodes.values()].filter((x) => x.kind === "satellite" && x.ownerId === id);
    return n.attrs.length > 0 || sats.length > 0;
  });
  ownerIds.sort((a, b) => {
    const na = nodes.get(a)!;
    const nb = nodes.get(b)!;
    return nb.w * nb.h - na.w * na.h;
  });
  for (const id of ownerIds) {
    const node = nodes.get(id)!;
    const sats = [...nodes.values()].filter((x) => x.kind === "satellite" && x.ownerId === id);
    const neighbors = smart
      .filter((c) => c.from === id || c.to === id)
      .map((c) => nodes.get(c.from === id ? c.to : c.from))
      .filter((n): n is LNode => !!n && n.kind !== "satellite" && n.id !== id);
    const preferred = fallbackPreferred(node, neighbors, centerOfComp(node.comp), profile);
    // 自己不能作为障碍，否则永远算重叠
    const obstacles = coreObstacles.filter((b) => b !== coreObstacles[coreIds.indexOf(id)]);
    placeOwnerAttrs(node, sats, obstacles, placedAttrBoxes, segments, preferred, profile);
    for (const a of node.attrs) {
      const box: Box = {
        minX: node.x + a.ox - a.w / 2,
        minY: node.y + a.oy - a.h / 2,
        maxX: node.x + a.ox + a.w / 2,
        maxY: node.y + a.oy + a.h / 2,
      };
      placedAttrBoxes.push(box);
    }
    for (const s of sats) {
      placedAttrBoxes.push(coreBox(s));
      coreObstacles.push(coreBox(s));
    }
  }

  // 属性 + 核心整体再让一次，确保页面内不出现明显重叠
  const allMoveIds = [...anchors, ...relations, ...[...nodes.values()].filter((n) => n.kind === "satellite").map((n) => n.id)];
  for (let iter = 0; iter < 90; iter++) {
    const boxes = new Map<string, Box>();
    for (const id of allMoveIds) {
      const n = nodes.get(id)!;
      let b = coreBox(n);
      for (const a of n.attrs) {
        b = unionBox(b, {
          minX: n.x + a.ox - a.w / 2,
          minY: n.y + a.oy - a.h / 2,
          maxX: n.x + a.ox + a.w / 2,
          maxY: n.y + a.oy + a.h / 2,
        });
      }
      boxes.set(id, b);
    }
    let moved = false;
    for (let i = 0; i < allMoveIds.length; i++) {
      for (let j = i + 1; j < allMoveIds.length; j++) {
        const A = boxes.get(allMoveIds[i])!;
        const B = boxes.get(allMoveIds[j])!;
        const o = overlapOf(A, B, OVERLAP_PAD);
        if (!o) continue;
        const a = nodes.get(allMoveIds[i])!;
        const b = nodes.get(allMoveIds[j])!;
        const ax0 = a.x;
        const ay0 = a.y;
        const bx0 = b.x;
        const by0 = b.y;
        if (o.ox < o.oy) {
          const dir = a.x <= b.x ? -1 : 1;
          a.x += (dir * o.ox) / 2;
          b.x -= (dir * o.ox) / 2;
        } else {
          const dir = a.y <= b.y ? -1 : 1;
          a.y += (dir * o.oy) / 2;
          b.y -= (dir * o.oy) / 2;
        }
        // 位移量取「节点中心的变化」，不能用并集包围盒中心反推：
        // 属性扇形不对称时两者并不重合，否则会把刚推开的盒子又移回去。
        boxes.set(allMoveIds[i], shiftBox(A, a.x - ax0, a.y - ay0));
        boxes.set(allMoveIds[j], shiftBox(B, b.x - bx0, b.y - by0));
        moved = true;
      }
    }
    if (!moved) break;
  }

  // 属性 / 独立属性椭圆与连线分离（R20：不允许连线压住属性）
  const satelliteIds = [...nodes.values()].filter((n) => n.kind === "satellite").map((n) => n.id);
  separateAttrsFromLines(ownerIds, satelliteIds, nodes, smart);

  /**
   * 比例填充：内容形状与页面比例不一致时，只拉伸「图形中心」的间距，
   * 图形尺寸 / 字号 / 属性相对位置都不变。这样页面不会被比例补边撑出大片留白，
   * 也不会因为缩放属性而破坏间距。
   */
  const bboxOfAll = (): Box | null => {
    let box: Box | null = null;
    for (const id of allMoveIds) {
      const n = nodes.get(id)!;
      let b = coreBox(n);
      for (const a of n.attrs) {
        b = unionBox(b, {
          minX: n.x + a.ox - a.w / 2,
          minY: n.y + a.oy - a.h / 2,
          maxX: n.x + a.ox + a.w / 2,
          maxY: n.y + a.oy + a.h / 2,
        });
      }
      box = box ? unionBox(box, b) : b;
    }
    return box;
  };
  if (ratioAspect) {
    for (let iter = 0; iter < 3; iter++) {
      const b = bboxOfAll();
      if (!b) break;
      const w = boxWidth(b);
      const h = boxHeight(b);
      let fx = 1;
      let fy = 1;
      if (w / h < ratioAspect * 0.97) fx = Math.min(1.9, (ratioAspect * h) / w);
      else if (w / h > ratioAspect * 1.03) fy = Math.min(1.9, w / (ratioAspect * h));
      if (fx < 1.03 && fy < 1.03) break;
      const cx = (b.minX + b.maxX) / 2;
      const cy = (b.minY + b.maxY) / 2;
      const satRel = new Map<string, { x: number; y: number }>();
      for (const id of satelliteIds) {
        const s = nodes.get(id)!;
        if (!s.ownerId) continue;
        const o = nodes.get(s.ownerId);
        if (o) satRel.set(id, { x: s.x - o.x, y: s.y - o.y });
      }
      for (const id of [...anchors, ...relations]) {
        const n = nodes.get(id)!;
        n.x = cx + (n.x - cx) * fx;
        n.y = cy + (n.y - cy) * fy;
      }
      for (const id of satelliteIds) {
        const s = nodes.get(id)!;
        const o = s.ownerId ? nodes.get(s.ownerId) : null;
        const rel = satRel.get(id);
        if (o && rel) {
          s.x = o.x + rel.x;
          s.y = o.y + rel.y;
        }
      }
    }
    // 拉伸后线条变长，重新做一次属性避让
    separateAttrsFromLines(ownerIds, satelliteIds, nodes, smart);
  }

  // 最终 base 包围盒（含内嵌属性、独立属性椭圆、自由端）
  const freeRel = new Map<string, { x: number; y: number }>();
  for (const c of connections) {
    if (!isFreeConnection(c) || !c.free_end) continue;
    const from = nodes.get(c.from);
    const old = oldPos.get(c.from);
    if (!from || !old) continue;
    freeRel.set(c.id, { x: c.free_end.x - old.x, y: c.free_end.y - old.y });
  }

  let contentBox: Box | null = null;
  const grow = (b: Box) => {
    contentBox = contentBox ? unionBox(contentBox, b) : b;
  };
  for (const id of allMoveIds) {
    const n = nodes.get(id)!;
    grow(coreBox(n));
    for (const a of n.attrs) {
      grow({
        minX: n.x + a.ox - a.w / 2,
        minY: n.y + a.oy - a.h / 2,
        maxX: n.x + a.ox + a.w / 2,
        maxY: n.y + a.oy + a.h / 2,
      });
    }
  }
  for (const [id, rel] of freeRel) {
    const c = connections.find((x) => x.id === id);
    const from = c ? nodes.get(c.from) : null;
    if (!from) continue;
    const rx = spin ? rotatePoint(rel.x, rel.y, 0, 0, spin) : rel;
    grow({
      minX: from.x + rx.x,
      minY: from.y + rx.y,
      maxX: from.x + rx.x + 1,
      maxY: from.y + rx.y + 1,
    });
  }
  const baseBox = contentBox ?? { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  const baseW = boxWidth(baseBox);
  const baseH = boxHeight(baseBox);
  const baseCx = (baseBox.minX + baseBox.maxX) / 2;
  const baseCy = (baseBox.minY + baseBox.maxY) / 2;

  // 页面缩放：优先装进「当前页面」，保持画布宽高不变；
  // 只有内容多到最小字号都放不下时，才按比例扩大工作区域。
  const oldScale = median(elements.map((e) => Number(e.layout_scale) || 1));
  const ratioAspectNow = ratioValue(ratio);
  const preferred =
    preferredPage &&
    preferredPage.w > 0 &&
    preferredPage.h > 0 &&
    ratioAspectNow !== null &&
    Math.abs(preferredPage.w / preferredPage.h - ratioAspectNow) < 0.02
      ? preferredPage
      : null;
  const preferredCx = preferred ? preferred.x + preferred.w / 2 : 0;
  const preferredCy = preferred ? preferred.y + preferred.h / 2 : 0;
  const fitted = preferred
    ? fitIntoPage(baseW, baseH, preferred.w, preferred.h)
    : fitPage(baseW, baseH, ratio, profile);
  const scale = fitted ? fitted.scale : clamp(oldScale, SCALE.min, SCALE.max);

  // 没有当前页面时（自由画布 / 比例刚切换还未上报页面盒）：
  // 以旧内容中心为锚，新页面围绕它生成，重排后画面中心不跳走。
  let oldBox: Box | null = null;
  for (const id of allMoveIds) {
    const n = nodes.get(id)!;
    const old = oldPos.get(id);
    if (!old) continue;
    const b: Box = {
      minX: old.x - n.w / 2,
      minY: old.y - n.h / 2,
      maxX: old.x + n.w / 2,
      maxY: old.y + n.h / 2,
    };
    oldBox = oldBox ? unionBox(oldBox, b) : b;
  }
  const oldCx = oldBox ? (oldBox.minX + oldBox.maxX) / 2 : 0;
  const oldCy = oldBox ? (oldBox.minY + oldBox.maxY) / 2 : 0;

  const pageBox = fitted
    ? preferred
      ? {
          x: round(preferredCx - fitted.pageW / 2),
          y: round(preferredCy - fitted.pageH / 2),
          w: round(fitted.pageW),
          h: round(fitted.pageH),
        }
      : {
          x: round(oldCx - fitted.pageW / 2),
          y: round(oldCy - fitted.pageH / 2),
          w: round(fitted.pageW),
          h: round(fitted.pageH),
        }
    : null;

  // 新内容包围盒中心映射到页面中心（有页面）或旧内容中心（自由画布）。
  const originX = preferred ? preferredCx : oldCx;
  const originY = preferred ? preferredCy : oldCy;

  const positions: Record<string, Position> = {};
  const sizes: Record<string, { w: number; h: number }> = {};
  const offsets: Record<string, Record<string, Position>> = {};
  for (const id of allMoveIds) {
    const n = nodes.get(id)!;
    positions[id] = {
      x: round((n.x - baseCx) * scale + originX),
      y: round((n.y - baseCy) * scale + originY),
    };
    sizes[id] = { w: round(n.w * scale), h: round(n.h * scale) };
    if (n.attrs.length) {
      const map: Record<string, Position> = {};
      for (const a of n.attrs) {
        map[String(a.index)] = { x: round(a.ox * scale), y: round(a.oy * scale) };
      }
      offsets[id] = map;
    }
  }
  const freeEnds: Record<string, Position> = {};
  for (const [id, rel] of freeRel) {
    const c = connections.find((x) => x.id === id);
    const from = c ? nodes.get(c.from) : null;
    if (!from) continue;
    const rx = spin ? rotatePoint(rel.x, rel.y, 0, 0, spin) : rel;
    freeEnds[id] = {
      x: round((from.x + rx.x - baseCx) * scale + originX),
      y: round((from.y + rx.y - baseCy) * scale + originY),
    };
  }

  // 统计：重叠 / 交叉 / 页面利用
  const probes: ShapeProbe[] = [];
  for (const id of allMoveIds) {
    const n = nodes.get(id)!;
    const p = positions[id];
    const s = sizes[id];
    probes.push({ shape: n.shape, cx: p.x, cy: p.y, w: s.w, h: s.h });
    for (const a of n.attrs) {
      const size = ellipseSize(a.name, scale);
      const o = offsets[id]?.[String(a.index)] ?? { x: 0, y: 0 };
      probes.push({ shape: "ellipse", cx: p.x + o.x, cy: p.y + o.y, w: size.W, h: size.H });
    }
  }
  let overlaps = 0;
  for (let i = 0; i < probes.length; i++) {
    for (let j = i + 1; j < probes.length; j++) {
      if (probesIntersect(probes[i], probes[j])) overlaps += 1;
    }
  }
  const segs: Array<[string, string, { x: number; y: number }, { x: number; y: number }]> = [];
  let longestEdge = 0;
  for (const c of smart) {
    const a = positions[c.from];
    const b = positions[c.to];
    const sa = sizes[c.from];
    const sb = sizes[c.to];
    const na = nodes.get(c.from);
    const nb = nodes.get(c.to);
    if (!a || !b || !sa || !sb || !na || !nb) continue;
    const p1 = borderPoint(na.shape, sa.w, sa.h, a.x, a.y, b.x, b.y);
    const p2 = borderPoint(nb.shape, sb.w, sb.h, b.x, b.y, a.x, a.y);
    segs.push([c.from, c.to, p1, p2]);
    longestEdge = Math.max(longestEdge, Math.hypot(p2.x - p1.x, p2.y - p1.y));
  }
  const crossings = crossingPairs(segs);
  const minFont = FONT.attr * scale;
  const fill =
    fitted && pageBox
      ? (Math.max(1, baseW * scale) * Math.max(1, baseH * scale)) / (pageBox.w * pageBox.h)
      : 0;

  const warnings: string[] = [];
  if (overlaps > 0) warnings.push(`仍有 ${overlaps} 处图形/属性重叠，可点「重新排列」再试一次。`);
  if (fitted?.grown) {
    warnings.push("内容较多：已按当前比例扩大工作区域并保持最小字号 12px，未压缩文字。");
  } else if (fitted && scale <= SCALE.min + 0.002) {
    warnings.push("内容较复杂：已扩大页面并保持最小字号 12px，未继续压缩文字。");
  }
  if (fitted && fill < 0.4) warnings.push("页面留白偏多：可尝试「重新排列」或换一个页面比例。");

  const stats: AutoLayoutStats = {
    contentW: round(baseW * scale),
    contentH: round(baseH * scale),
    pageW: pageBox?.w ?? 0,
    pageH: pageBox?.h ?? 0,
    fill,
    scale,
    minFont,
    overlaps,
    crossings,
    longestEdge,
    nodes: anchors.length + relations.length + [...nodes.values()].filter((n) => n.kind === "satellite").length,
  };

  return {
    positions,
    sizes,
    offsets,
    freeEnds,
    scale,
    pageBox,
    stats,
    warnings,
  };
}

function shiftBox(b: Box, dx: number, dy: number): Box {
  return { minX: b.minX + dx, minY: b.minY + dy, maxX: b.maxX + dx, maxY: b.maxY + dy };
}
