import { Canvas, Line } from "fabric";
import type { Connection, Element, PaintState } from "../protocol/types";
import {
  connFingerprint,
  createConnectionVisual,
  layoutConnection,
  styleConnection,
  type ConnVisual,
} from "./connectors";
import { applyBodyStyle, STROKE } from "./highlight";
import { borderPoint } from "./geometry";
import {
  attrBaseAngle,
  attrFingerprint,
  createAttrNodes,
  createElementGroup,
  elementFingerprint,
  layoutAttrNodes,
  styleAttrNodes,
  type AttrNodeVisual,
  type ElementVisual,
} from "./shapes";

export interface CanvasCallbacks {
  onSelect: (kind: "element" | "connection", id: string) => void;
  onClearSelection: () => void;
  onBackgroundClick: (pt: { x: number; y: number }) => void;
  onNodeClick: (id: string) => void;
  onConnCancel: () => void;
  onElementMoved: (id: string, x: number, y: number) => void;
  onViewChanged?: () => void;
  onAttrMoved?: (ownerId: string, index: number, ox: number, oy: number) => void;
}

export function createErCanvas(el: HTMLCanvasElement, cb: CanvasCallbacks) {
  const canvas = new Canvas(el, {
    selection: false,
    preserveObjectStacking: true,
    stopContextMenu: true,
    // 后备缓冲按 devicePixelRatio 放大，避免高分屏/系统缩放下发虚
    enableRetinaScaling: true,
  });

  const elems = new Map<string, ElementVisual>();
  const conns = new Map<string, ConnVisual>();
  const attrNodes = new Map<string, AttrNodeVisual>(); // 实体属性摊成的椭圆节点
  const ownerLines: Line[] = []; // 属性椭圆 → 实体的归属连线
  let currentElements: Element[] = []; // 当前元素数据（供归属连线用）
  let currentConnections: Connection[] = [];
  let paintMap: Record<string, PaintState> = {};
  let tool = "select";
  let silent = false;
  let panning: { x: number; y: number } | null = null;
  let lastVpt = "";

  // 平移/缩放时通知外层（让"线上写基数"浮层跟着动）
  canvas.on("after:render", () => {
    const vpt = canvas.viewportTransform;
    const key = vpt ? `${vpt[0]}|${vpt[4]}|${vpt[5]}` : "";
    if (key !== lastVpt) {
      lastVpt = key;
      cb.onViewChanged?.();
    }
  });

  function sendConnsBack() {
    const objs: unknown[] = [];
    for (const vis of conns.values()) for (const p of vis.parts) objs.push(p.obj);
    for (let i = objs.length - 1; i >= 0; i--) {
      canvas.sendObjectToBack(objs[i] as never);
    }
  }

  /** 元素组中心（拖拽过程中以画布上的实际位置为准） */
  function elementCenter(id: string) {
    const vis = elems.get(id);
    if (vis) return vis.group.getCenterPoint();
    const model = currentElements.find((e) => e.id === id);
    return model ? { x: model.position.x, y: model.position.y } : null;
  }

  /** 属性扇形基准方向：统一走 shapes 里的纯函数，渲染与重叠检测保持一致 */
  function attrAngleOf(id: string): number {
    const me = currentElements.find((e) => e.id === id);
    if (!me) return 0;
    return attrBaseAngle(me, currentElements, currentConnections);
  }

  /** 把实体的属性摊成椭圆节点：属性变了就重建，位置变了就重排 */
  function syncAttrNodes(model: Element) {
    const angle = attrAngleOf(model.id);
    const fingerprint = attrFingerprint(model, angle);
    const center = elementCenter(model.id) ?? model.position;
    const cur = attrNodes.get(model.id);
    if (cur) {
      if (cur.fingerprint === fingerprint) {
        layoutAttrNodes(cur, center.x, center.y);
        styleAttrNodes(cur, paintMap[model.id] ?? "pending");
        return;
      }
      for (const p of cur.parts) canvas.remove(p as never);
      attrNodes.delete(model.id);
    }
    const vis = createAttrNodes(model, angle, center.x, center.y);
    if (!vis) return;
    attrNodes.set(model.id, vis);
    for (const p of vis.parts) canvas.add(p as never);
    for (const p of vis.parts) canvas.sendObjectToBack(p as never);
    styleAttrNodes(vis, paintMap[model.id] ?? "pending");
  }

  function removeAttrNodes(id: string) {
    const vis = attrNodes.get(id);
    if (!vis) return;
    for (const p of vis.parts) canvas.remove(p as never);
    attrNodes.delete(id);
  }

  function layoutFor(id: string) {
    for (const vis of conns.values()) {
      if (vis.data.from === id || vis.data.to === id) layoutConnection(vis, elems);
    }
    const attr = attrNodes.get(id);
    const center = elementCenter(id);
    if (attr && center) layoutAttrNodes(attr, center.x, center.y);
    syncOwnerLines(currentElements);
    canvas.requestRenderAll();
  }

  function addElement(model: Element) {
    const vis = createElementGroup(model);
    elems.set(model.id, vis);
    canvas.add(vis.group);
    sendConnsBack();
    syncOwnerLines(currentElements);
  }

  function replaceElement(model: Element) {
    const old = elems.get(model.id);
    if (!old) {
      addElement(model);
      return;
    }
    const active = canvas.getActiveObject() === old.group;
    canvas.remove(old.group);
    const vis = createElementGroup(model);
    elems.set(model.id, vis);
    canvas.add(vis.group);
    if (active) {
      silent = true;
      canvas.setActiveObject(vis.group);
      silent = false;
    }
    layoutFor(model.id);
    sendConnsBack();
  }

  function removeElement(id: string) {
    const vis = elems.get(id);
    removeAttrNodes(id);
    if (!vis) return;
    if (canvas.getActiveObject() === vis.group) canvas.discardActiveObject();
    canvas.remove(vis.group);
    elems.delete(id);
    syncOwnerLines(currentElements);
  }

  function addConnection(model: Connection) {
    const vis = createConnectionVisual(canvas, model);
    conns.set(model.id, vis);
    layoutConnection(vis, elems);
    sendConnsBack();
  }

  function replaceConnection(model: Connection) {
    removeConnection(model.id);
    addConnection(model);
  }

  function removeConnection(id: string) {
    const vis = conns.get(id);
    if (!vis) return;
    if (vis.parts.some((p) => canvas.getActiveObject() === p.obj)) canvas.discardActiveObject();
    for (const p of vis.parts) canvas.remove(p.obj);
    conns.delete(id);
  }

  // Chen ER 图规范：属性椭圆自动连到最近的实体（归属连线）
  const OWNER_LINE_MAX_DIST = 140; // 最大归属距离（px）
  function syncOwnerLines(elements: Element[]) {
    // 清除旧线
    for (const line of ownerLines) canvas.remove(line);
    ownerLines.length = 0;

    const ellipses = elements.filter((e) => e.shape === "ellipse");
    const rects = elements.filter((e) => e.shape === "rectangle");
    // 已经用连线显式连到实体的属性椭圆不再画虚线
    const linked = new Set<string>();
    for (const c of currentConnections) {
      linked.add(`${c.from}|${c.to}`);
      linked.add(`${c.to}|${c.from}`);
    }

    for (const ell of ellipses) {
      const ellVis = elems.get(ell.id);
      if (!ellVis) continue;
      const ec = ellVis.group.getCenterPoint();

      // 找最近的矩形实体
      let bestRect: ElementVisual | null = null;
      let bestRectId = "";
      let bestDist = Infinity;
      for (const rect of rects) {
        const rv = elems.get(rect.id);
        if (!rv) continue;
        const rc = rv.group.getCenterPoint();
        const d = Math.hypot(rc.x - ec.x, rc.y - ec.y);
        if (d < bestDist) {
          bestDist = d;
          bestRect = rv;
          bestRectId = rect.id;
        }
      }

      if (!bestRect || bestDist > OWNER_LINE_MAX_DIST) continue;
      if (linked.has(`${ell.id}|${bestRectId}`)) continue;

      // 计算椭圆和矩形的边框交点
      const rc = bestRect.group.getCenterPoint();
      const ep = borderPoint("ellipse", ellVis.w, ellVis.h, ec.x, ec.y, rc.x, rc.y);
      const rp = borderPoint("rectangle", bestRect.w, bestRect.h, rc.x, rc.y, ec.x, ec.y);

      const line = new Line([ep.x, ep.y, rp.x, rp.y], {
        stroke: "#94A3B8",
        strokeWidth: 1,
        strokeDashArray: [4, 3],
        selectable: false,
        evented: false,
        objectCaching: false,
      });
      canvas.add(line);
      ownerLines.push(line);
    }
    // 归属连线放到最底层
    for (const line of ownerLines) canvas.sendObjectToBack(line);
  }

  function sync(
    elements: Element[],
    connections: Connection[],
    paint: Record<string, PaintState>,
  ) {
    currentElements = elements;
    currentConnections = connections;
    paintMap = paint;
    const eids = new Set(elements.map((e) => e.id));
    const cids = new Set(connections.map((c) => c.id));
    for (const id of [...elems.keys()]) if (!eids.has(id)) removeElement(id);
    for (const id of [...conns.keys()]) if (!cids.has(id)) removeConnection(id);

    for (const model of elements) {
      const vis = elems.get(model.id);
      if (!vis) addElement(model);
      else if (vis.fingerprint !== elementFingerprint(model)) replaceElement(model);
      else {
        const g = vis.group;
        if (Math.abs((g.left ?? 0) - model.position.x) > 0.5 || Math.abs((g.top ?? 0) - model.position.y) > 0.5) {
          if (canvas.getActiveObject() !== g) {
            g.set({ left: model.position.x, top: model.position.y });
            g.setCoords();
            layoutFor(model.id);
          }
        }
      }
    }
    for (const c of connections) {
      const vis = conns.get(c.id);
      if (!vis) addConnection(c);
      else if (connFingerprint(vis.data) !== connFingerprint(c)) replaceConnection(c);
    }
    for (const model of elements) {
      syncAttrNodes(model);
      const vis = elems.get(model.id);
      if (!vis) continue;
      const sev = paint[model.id] ?? "pending";
      applyBodyStyle(vis.body, vis.badge, sev);
      if (vis.innerBody) vis.innerBody.set({ stroke: STROKE[sev] });
      vis.group.dirty = true;
    }
    for (const c of connections) {
      const vis = conns.get(c.id);
      if (vis) styleConnection(vis, paint[c.id] ?? "pending");
    }
    sendConnsBack();
    syncOwnerLines(elements);
    canvas.requestRenderAll();
  }

  canvas.on("mouse:down", (opt) => {
    const e = opt.e as MouseEvent;
    const empty = !opt.target;
    if (e.button === 1 || (e.button === 0 && empty && tool === "select")) {
      panning = { x: e.clientX, y: e.clientY };
      if (empty) canvas.discardActiveObject();
      return;
    }
    if (empty) {
      if (tool === "connect") {
        cb.onConnCancel();
        return;
      }
      const pt = canvas.getPointer(e);
      // 落在整数像素上，新建的图形与文字才不会发虚
      cb.onBackgroundClick({ x: Math.round(pt.x), y: Math.round(pt.y) });
    }
  });
  canvas.on("mouse:move", (opt) => {
    if (!panning) return;
    const e = opt.e as MouseEvent;
    const vpt = canvas.viewportTransform;
    if (!vpt) return;
    vpt[4] += e.clientX - panning.x;
    vpt[5] += e.clientY - panning.y;
    panning = { x: e.clientX, y: e.clientY };
    canvas.requestRenderAll();
  });
  canvas.on("mouse:up", () => {
    panning = null;
  });
  canvas.on("selection:created", () => {
    if (silent) return;
    const a = canvas.getActiveObject() as { erId?: string; erKind?: string } | undefined;
    if (a?.erId && (a.erKind === "element" || a.erKind === "connection")) cb.onSelect(a.erKind, a.erId);
  });
  canvas.on("selection:updated", () => {
    if (silent) return;
    const a = canvas.getActiveObject() as { erId?: string; erKind?: string } | undefined;
    if (a?.erId && (a.erKind === "element" || a.erKind === "connection")) cb.onSelect(a.erKind, a.erId);
  });
  canvas.on("selection:cleared", () => {
    if (!silent) cb.onClearSelection();
  });
  canvas.on("mouse:down", (opt) => {
    const t = opt.target as { erId?: string; erKind?: string } | undefined;
    if (tool === "connect" && t?.erKind === "element" && t.erId) {
      cb.onNodeClick(t.erId);
    }
  });
  canvas.on("object:moving", (opt) => {
    const o = opt.target as {
      erId?: string;
      erKind?: string;
      erAttrOwner?: string;
      erAttrIndex?: number;
      getCenterPoint?: () => { x: number; y: number };
    } | undefined;
    if (o?.erAttrOwner !== undefined && o.erAttrIndex !== undefined && o.getCenterPoint) {
      const owner = elems.get(o.erAttrOwner);
      const vis = attrNodes.get(o.erAttrOwner);
      if (owner && vis) {
        const c = owner.group.getCenterPoint();
        const p = o.getCenterPoint();
        const node = vis.nodes[o.erAttrIndex];
        if (node) {
          node.ox = p.x - c.x;
          node.oy = p.y - c.y;
          layoutAttrNodes(vis, c.x, c.y);
          canvas.requestRenderAll();
        }
      }
      return;
    }
    if (o?.erKind === "element" && o.erId) layoutFor(o.erId);
  });
  canvas.on("object:modified", (opt) => {
    const o = opt.target as {
      erId?: string;
      erKind?: string;
      erAttrOwner?: string;
      erAttrIndex?: number;
      getCenterPoint?: () => { x: number; y: number };
    };
    if (o?.erAttrOwner !== undefined && o.erAttrIndex !== undefined && o.getCenterPoint) {
      const owner = elems.get(o.erAttrOwner);
      if (owner) {
        const c = owner.group.getCenterPoint();
        const p = o.getCenterPoint();
        cb.onAttrMoved?.(o.erAttrOwner, o.erAttrIndex, p.x - c.x, p.y - c.y);
      }
      return;
    }
    if (o?.erKind === "element" && o.erId && o.getCenterPoint) {
      // 落点取整：图形与文字压在整数像素上才清晰
      const p = o.getCenterPoint();
      const x = Math.round(p.x);
      const y = Math.round(p.y);
      const group = elems.get(o.erId)?.group;
      if (group) {
        group.set({ left: x, top: y });
        group.setCoords();
        layoutFor(o.erId);
      }
      cb.onElementMoved(o.erId, x, y);
    }
  });

  function selectVisual(kind: "element" | "connection" | null, id: string | null) {
    silent = true;
    canvas.discardActiveObject();
    if (kind === "element" && id) {
      const vis = elems.get(id);
      if (vis) canvas.setActiveObject(vis.group);
    } else if (kind === "connection" && id) {
      const vis = conns.get(id);
      const hit = vis?.parts.find((p) => p.tag === "hit");
      if (hit) canvas.setActiveObject(hit.obj as never);
    }
    silent = false;
    canvas.requestRenderAll();
  }

  return {
    canvas,
    sync,
    setTool(t: string) {
      tool = t;
      canvas.defaultCursor = t === "select" ? "default" : "crosshair";
    },
    selectVisual,
    /** 连线中点的屏幕坐标（供"线上写基数"浮层定位） */
    connectionAnchor(id: string) {
      const vis = conns.get(id);
      if (!vis) return null;
      const vpt = canvas.viewportTransform;
      if (!vpt) return null;
      return {
        x: vis.mid.x * vpt[0] + vpt[4],
        y: vis.mid.y * vpt[3] + vpt[5],
      };
    },
    resize(w: number, h: number) {
      // Fabric 把后备缓冲设成 "CSS 尺寸 × devicePixelRatio" 再取整：
      // 若乘积带小数（如系统缩放 125% 时 494×1.25=617.5），整块画面会被缩放零点几像素而整体发虚。
      // 这里把 CSS 尺寸取成"× dpr 正好是整数"的值，让一个绘制像素对应一个屏幕像素。
      const dpr = window.devicePixelRatio || 1;
      const snap = (v: number) => Math.max(1, Math.floor(v * dpr) / dpr);
      canvas.setDimensions({ width: snap(w), height: snap(h) });
    },
    zoomBy(factor: number) {
      const vpt = canvas.viewportTransform;
      if (!vpt) return;
      const zoom = Math.max(0.2, Math.min(2.5, vpt[0] * factor));
      const cw = canvas.getWidth();
      const ch = canvas.getHeight();
      const sx = (cw / 2 - vpt[4]) / (vpt[0] || 1);
      const sy = (ch / 2 - vpt[5]) / (vpt[3] || 1);
      vpt[0] = zoom;
      vpt[3] = zoom;
      vpt[4] = cw / 2 - sx * zoom;
      vpt[5] = ch / 2 - sy * zoom;
      canvas.requestRenderAll();
    },
    destroy() {
      canvas.dispose();
    },
  };
}

export type ErCanvasApi = ReturnType<typeof createErCanvas>;
