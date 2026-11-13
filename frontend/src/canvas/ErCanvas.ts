import { Canvas, Circle, Ellipse, Line, Point, Polygon, Rect, type FabricObject } from "fabric";
import type { Connection, Element, PaintState } from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import {
  connFingerprint,
  createConnectionVisual,
  layoutConnection,
  type ConnVisual,
} from "./connectors";
import {
  DEFAULT_APPEARANCE,
  makeGridPattern,
  normalizeAppearance,
  pageBorderColorFor,
  shapeStyleFor,
  type CanvasAppearance,
  type ShapeStyle,
} from "./appearance";
import { haloColor } from "./highlight";
import { lineHalo, outline } from "./overlay";
import { borderPoint, clamp } from "./geometry";
import {
  attrBaseAngle,
  attrFingerprint,
  createAttrNodes,
  createElementGroup,
  elementFingerprint,
  elementScale,
  layoutAttrNodes,
  type AttrNodeVisual,
  type ElementVisual,
} from "./shapes";
import {
  createFreeGrid,
  createPage,
  pageBoxFor,
  snapToGrid,
  type Bounds,
  type PageBox,
  type PageRatio,
} from "./page";
import { HALO_LINE, SNAP_STEP, STROKE } from "./theme";

export interface CanvasCallbacks {
  onSelect: (kind: "element" | "connection", id: string) => void;
  onSelectAttribute: (ownerId: string, index: number) => void;
  onClearSelection: () => void;
  onBackgroundClick: (pt: { x: number; y: number }) => void;
  onNodeClick: (id: string) => void;
  onConnCancel: () => void;
  /** 自由端连线：在画布任意位置确认自由终点 */
  onFreePoint?: (pt: { x: number; y: number }) => void;
  /** 自由端控制点被拖动结束 */
  onFreeEndMoved?: (id: string, x: number, y: number) => void;
  onElementMoved: (id: string, x: number, y: number) => void;
  onElementResized?: (id: string, w: number, h: number) => void;
  onAttrMoved?: (ownerId: string, index: number, ox: number, oy: number) => void;
  onViewChanged?: () => void;
  /** 页面盒（工作画布尺寸）变化：供比例面板显示实际尺寸，不参与图形数据 */
  onPageChanged?: (box: PageBox | null) => void;
}

type ErTarget = {
  erKind?: string;
  erId?: string;
  erAttrOwner?: string;
  erAttrIndex?: number;
  getCenterPoint?: () => { x: number; y: number };
};

export function createErCanvas(el: HTMLCanvasElement, cb: CanvasCallbacks) {
  let appearance: CanvasAppearance = { ...DEFAULT_APPEARANCE };
  let style: ShapeStyle = shapeStyleFor(appearance);
  let pageShown = false;

  const canvas = new Canvas(el, {
    selection: false,
    preserveObjectStacking: true,
    stopContextMenu: true,
    backgroundColor: appearance.background,
    // 后备缓冲按 devicePixelRatio 放大，避免高分屏/系统缩放下发虚
    enableRetinaScaling: true,
  });

  const elems = new Map<string, ElementVisual>();
  const conns = new Map<string, ConnVisual>();
  // 仅开发环境：方便在浏览器控制台核对画布状态（生产构建会被摇掉）
  if (import.meta.env.DEV) {
    (window as unknown as { __erCanvas?: Canvas }).__erCanvas = canvas;
  }
  const attrNodes = new Map<string, AttrNodeVisual>(); // 实体属性摊成的椭圆节点
  const ownerLines: Line[] = []; // 独立属性椭圆 → 最近实体的归属连线
  const elemHalos = new Map<string, FabricObject[]>();
  const connHalos = new Map<string, FabricObject[]>();
  let currentElements: Element[] = []; // 当前元素数据（供归属连线用）
  let currentConnections: Connection[] = [];
  let paintMap: Record<string, PaintState> = {};
  let tool = "select";
  let silent = false;
  let panning: { x: number; y: number } | null = null;
  let spacePan = false;
  let snapEnabled = true;
  let lastVpt = "";
  let hoverRing: FabricObject | null = null;
  let hoverRingId = "";
  let guideV: Line | null = null;
  let guideH: Line | null = null;
  let pageRatio: PageRatio = "free";
  /** 自由端连线的预览线 / 编辑控制点 */
  let freePreview: { fromId: string; line: Line } | null = null;
  let freeHandle: Circle | null = null;
  let freeHandleId = "";
  let suppressNodeDown = false;
  /** 记录当前选中对象，外观重绘后据此恢复选中 */
  let selectedVisual: { kind: "element" | "connection"; id: string; attrIndex?: number } | null = null;

  // ---------- 页面 / 网格 ----------
  let pageFill: ReturnType<typeof makeGridPattern> | string =
    makeGridPattern(appearance.background, appearance.grid, true) ?? appearance.background;
  let freeFill: ReturnType<typeof makeGridPattern> | string =
    makeGridPattern(appearance.background, appearance.grid, false) ?? appearance.background;
  const page = createPage(pageFill, pageBorderColorFor(appearance.background));
  const freeGrid = createFreeGrid(freeFill);
  page.visible = false;
  canvas.add(freeGrid as never);
  canvas.add(page as never);

  // 平移/缩放时通知外层（让"线上写基数"浮层跟着动）
  canvas.on("after:render", () => {
    const vpt = canvas.viewportTransform;
    const key = vpt ? `${vpt[0]}|${vpt[4]}|${vpt[5]}` : "";
    if (key !== lastVpt) {
      lastVpt = key;
      cb.onViewChanged?.();
    }
  });

  function syncLayerVisibility() {
    page.visible = pageShown;
    // 页面模式下由页面自身铺背景 / 网格；自由模式才显示整幅网格
    freeGrid.visible = !pageShown && appearance.grid !== "off";
  }

  function applyPage(box: PageBox | null) {
    pageShown = !!box;
    if (box) {
      page.set({ left: box.x, top: box.y, width: box.w, height: box.h });
      page.setCoords();
    }
    syncLayerVisibility();
    cb.onPageChanged?.(box ? { ...box } : null);
  }

  /** 应用画布外观：只改渲染层，不碰 elements / connections 数据 */
  function applyAppearance(next: CanvasAppearance) {
    appearance = normalizeAppearance(next);
    style = shapeStyleFor(appearance);
    canvas.backgroundColor = appearance.background;
    pageFill = makeGridPattern(appearance.background, appearance.grid, true) ?? appearance.background;
    freeFill = makeGridPattern(appearance.background, appearance.grid, false) ?? appearance.background;
    page.set({ fill: pageFill, stroke: pageBorderColorFor(appearance.background) });
    freeGrid.set({ fill: freeFill });
    syncLayerVisibility();
  }

  /** 统一层序：页面 → 归属线 → 连线 → 属性椭圆 → 图形 → 严重度外环 */
  function orderLayers() {
    let i = 0;
    const put = (o: FabricObject) => {
      canvas.moveObjectTo(o, i++);
    };
    if (freeGrid.visible) put(freeGrid as unknown as FabricObject);
    if (page.visible) put(page as unknown as FabricObject);
    for (const l of ownerLines) put(l as unknown as FabricObject);
    // 连线的严重度外环压在线下面，保证墨线清晰
    for (const list of connHalos.values()) {
      for (const o of list) put(o);
    }
    for (const vis of conns.values()) {
      for (const p of vis.parts) put(p.obj as unknown as FabricObject);
    }
    for (const av of attrNodes.values()) {
      for (const p of av.parts) put(p as unknown as FabricObject);
    }
    for (const vis of elems.values()) put(vis.group as unknown as FabricObject);
    for (const list of elemHalos.values()) {
      for (const o of list) put(o);
    }
    // 自由端预览线 / 编辑控制点永远在最上层
    if (freePreview) put(freePreview.line as unknown as FabricObject);
    if (freeHandle) put(freeHandle as unknown as FabricObject);
  }

  /** 元素内容级缩放（连线字号 / 描边 / 端点装饰跟起点元素共用） */
  function scaleOf(id: string) {
    const model = currentElements.find((e) => e.id === id);
    return model ? elementScale(model) : 1;
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
    const fingerprint = attrFingerprint(model, angle, style.key);
    const center = elementCenter(model.id) ?? model.position;
    const cur = attrNodes.get(model.id);
    if (cur) {
      if (cur.fingerprint === fingerprint) {
        layoutAttrNodes(cur, center.x, center.y);
        return;
      }
      for (const p of cur.parts) canvas.remove(p as never);
      attrNodes.delete(model.id);
    }
    const vis = createAttrNodes(model, angle, center.x, center.y, style);
    if (!vis) return;
    attrNodes.set(model.id, vis);
    for (const p of vis.parts) canvas.add(p as never);
  }

  function removeAttrNodes(id: string) {
    const vis = attrNodes.get(id);
    if (!vis) return;
    for (const p of vis.parts) canvas.remove(p as never);
    attrNodes.delete(id);
  }

  // ---------- 严重度外环 ----------
  function clearHalo(id: string) {
    for (const map of [elemHalos, connHalos]) {
      const list = map.get(id);
      if (!list) continue;
      for (const o of list) canvas.remove(o as never);
      map.delete(id);
    }
  }

  function addElementHalo(model: Element) {
    const color = haloColor(paintMap[model.id] ?? "pending");
    const vis = elems.get(model.id);
    if (!color || !vis) return;
    const c = vis.group.getCenterPoint();
    const s = scaleOf(model.id);
    const ring = outline(vis.shape, vis.w, vis.h, c.x, c.y, 5 * s, {
      stroke: color,
      strokeWidth: STROKE.halo * s,
    });
    canvas.add(ring as never);
    elemHalos.set(model.id, [ring as unknown as FabricObject]);
  }

  function addConnHalo(conn: Connection) {
    const state = paintMap[conn.id] ?? "pending";
    const color = haloColor(state);
    const vis = conns.get(conn.id);
    // 自由端连线保持干净：不加任何彩色外环 / 端点装饰
    if (!color || !vis || isFreeConnection(conn)) return;
    const list: FabricObject[] = [];
    for (const p of vis.parts) {
      if (p.tag !== "seg") continue;
      const l = p.obj as Line;
      const h = lineHalo(l.x1, l.y1, l.x2, l.y2, HALO_LINE[state as "error" | "warn"], 5 * vis.scale);
      canvas.add(h as never);
      list.push(h as unknown as FabricObject);
    }
    if (list.length) connHalos.set(conn.id, list);
  }

  function paintHalos() {
    for (const id of [...elemHalos.keys(), ...connHalos.keys()]) clearHalo(id);
    for (const model of currentElements) addElementHalo(model);
    for (const conn of currentConnections) addConnHalo(conn);
  }

  function refreshHalosFor(id: string) {
    clearHalo(id);
    const model = currentElements.find((e) => e.id === id);
    if (model) addElementHalo(model);
    for (const conn of currentConnections) {
      if (conn.from === id || conn.to === id) {
        clearHalo(conn.id);
        addConnHalo(conn);
      }
    }
  }

  function layoutFor(id: string) {
    for (const vis of conns.values()) {
      if (vis.data.from === id || vis.data.to === id) layoutConnection(vis, elems);
    }
    const attr = attrNodes.get(id);
    const center = elementCenter(id);
    if (attr && center) layoutAttrNodes(attr, center.x, center.y);
    syncOwnerLines(currentElements);
    refreshHalosFor(id);
    orderLayers();
    // 对齐辅助线永远显示在最上层（orderLayers 会把它压到图形下面）
    if (guideV?.visible) canvas.bringObjectToFront(guideV as never);
    if (guideH?.visible) canvas.bringObjectToFront(guideH as never);
    canvas.requestRenderAll();
  }

  function addElement(model: Element) {
    const vis = createElementGroup(model, style);
    elems.set(model.id, vis);
    canvas.add(vis.group);
    orderLayers();
  }

  function replaceElement(model: Element) {
    if (hoverRingId === model.id) clearHoverRing();
    const old = elems.get(model.id);
    if (!old) {
      addElement(model);
      return;
    }
    const active = canvas.getActiveObject() === old.group;
    canvas.remove(old.group);
    const vis = createElementGroup(model, style);
    elems.set(model.id, vis);
    canvas.add(vis.group);
    if (active) {
      const prev = silent;
      silent = true;
      canvas.setActiveObject(vis.group);
      silent = prev;
    }
    orderLayers();
  }

  function removeElement(id: string) {
    const vis = elems.get(id);
    removeAttrNodes(id);
    clearHalo(id);
    if (hoverRingId === id) clearHoverRing();
    if (!vis) return;
    if (canvas.getActiveObject() === vis.group) canvas.discardActiveObject();
    canvas.remove(vis.group);
    elems.delete(id);
  }

  function addConnection(model: Connection) {
    const vis = createConnectionVisual(canvas, model, style, scaleOf(model.from));
    conns.set(model.id, vis);
    layoutConnection(vis, elems);
    orderLayers();
  }

  function replaceConnection(model: Connection) {
    removeConnection(model.id);
    addConnection(model);
  }

  function removeConnection(id: string) {
    const vis = conns.get(id);
    if (!vis) return;
    if (vis.parts.some((p) => canvas.getActiveObject() === p.obj)) canvas.discardActiveObject();
    if (freeHandleId === id) hideFreeHandle();
    for (const p of vis.parts) canvas.remove(p.obj);
    conns.delete(id);
    clearHalo(id);
  }

  // ---------- 自由端连线：预览线 / 端点控制点 ----------
  function freeEndpoint(vis: ConnVisual) {
    if (vis.data.free_end) return { x: vis.data.free_end.x, y: vis.data.free_end.y };
    const from = elems.get(vis.data.from);
    const c = from ? from.group.getCenterPoint() : { x: 0, y: 0 };
    return { x: c.x + 140, y: c.y };
  }

  function hideFreeHandle() {
    if (freeHandle) {
      canvas.remove(freeHandle as never);
      freeHandle = null;
    }
    freeHandleId = "";
  }

  function showFreeHandle(id: string) {
    const vis = conns.get(id);
    if (!vis || !isFreeConnection(vis.data)) {
      hideFreeHandle();
      return;
    }
    const p = freeEndpoint(vis);
    if (freeHandle && freeHandleId === id) {
      freeHandle.set({ left: p.x, top: p.y });
      freeHandle.setCoords();
      canvas.bringObjectToFront(freeHandle as never);
      return;
    }
    hideFreeHandle();
    const s = scaleOf(vis.data.from);
    const handle = new Circle({
      left: p.x,
      top: p.y,
      radius: 5 * s,
      originX: "center",
      originY: "center",
      fill: "#FFFFFF",
      stroke: style.selection,
      strokeWidth: 1.5 * s,
      hasControls: false,
      hasBorders: false,
      selectable: true,
      evented: true,
      hoverCursor: "grab",
      moveCursor: "grabbing",
      objectCaching: false,
    });
    (handle as unknown as { erKind: string; erId: string }).erKind = "freeEnd";
    (handle as unknown as { erId: string }).erId = id;
    canvas.add(handle as never);
    canvas.bringObjectToFront(handle as never);
    freeHandle = handle;
    freeHandleId = id;
  }

  function clearFreePreview() {
    if (!freePreview) return;
    canvas.remove(freePreview.line as never);
    freePreview = null;
    canvas.requestRenderAll();
  }

  function beginFreePreview(fromId: string) {
    clearFreePreview();
    const from = elems.get(fromId);
    if (!from) return;
    const A = from.group.getCenterPoint();
    const s = scaleOf(fromId);
    const line = new Line([A.x, A.y, A.x + 1, A.y], {
      // 预览线用淡蓝色虚线；确认后由正式连线恢复标准墨色实线
      stroke: "#7C93FF",
      strokeWidth: 1.5 * s,
      strokeDashArray: [5 * s, 4 * s],
      selectable: false,
      evented: false,
      objectCaching: false,
    });
    canvas.add(line as never);
    canvas.bringObjectToFront(line as never);
    freePreview = { fromId, line };
    canvas.requestRenderAll();
  }

  function updateFreePreview(pointer: { x: number; y: number }) {
    if (!freePreview) return;
    const from = elems.get(freePreview.fromId);
    if (!from) return;
    const A = from.group.getCenterPoint();
    const p = borderPoint(from.shape, from.w, from.h, A.x, A.y, pointer.x, pointer.y);
    freePreview.line.set({ x1: p.x, y1: p.y, x2: pointer.x, y2: pointer.y });
    freePreview.line.setCoords();
    canvas.bringObjectToFront(freePreview.line as never);
    canvas.requestRenderAll();
  }

  // Chen ER 图规范：独立属性椭圆自动连到最近的实体（归属连线）
  // 最大归属距离（内容单位，按元素缩放换算）。自动布局会把独立属性椭圆
  // 排到参与者外侧，阈值太小会画不出归属线，看起来像孤立元素。
  const OWNER_LINE_MAX_DIST = 280;
  function syncOwnerLines(elements: Element[]) {
    for (const line of ownerLines) canvas.remove(line as never);
    ownerLines.length = 0;

    const ellipses = elements.filter((e) => e.shape === "ellipse");
    const rects = elements.filter((e) => e.shape === "rectangle");
    // 已经用连线显式连到实体的属性椭圆不再画归属线
    const linked = new Set<string>();
    for (const c of currentConnections) {
      if (isFreeConnection(c)) continue;
      linked.add(`${c.from}|${c.to}`);
      linked.add(`${c.to}|${c.from}`);
    }

    for (const ell of ellipses) {
      const ellVis = elems.get(ell.id);
      if (!ellVis) continue;
      const ec = ellVis.group.getCenterPoint();

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

      if (!bestRect) continue;
      const ownerScale = elementScale(rects.find((r) => r.id === bestRectId) ?? ell);
      if (bestDist > OWNER_LINE_MAX_DIST * ownerScale) continue;
      if (linked.has(`${ell.id}|${bestRectId}`)) continue;

      const rc = bestRect.group.getCenterPoint();
      const ep = borderPoint("ellipse", ellVis.w, ellVis.h, ec.x, ec.y, rc.x, rc.y);
      const rp = borderPoint("rectangle", bestRect.w, bestRect.h, rc.x, rc.y, ec.x, ec.y);

      const line = new Line([ep.x, ep.y, rp.x, rp.y], {
        stroke: style.ink,
        strokeWidth: 1 * ownerScale,
        // 可见描边必须随视口缩放，才能与文字 / 图形保持同一比例（strokeUniform 会让线宽冻结）
        opacity: 0.45,
        selectable: false,
        evented: false,
        objectCaching: false,
      });
      canvas.add(line as never);
      ownerLines.push(line);
    }
  }

  /** 把整张图（含属性椭圆）的包围盒 */
  function contentBounds(): Bounds | null {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    const grow = (x: number, y: number, w: number, h: number) => {
      minX = Math.min(minX, x - w / 2);
      maxX = Math.max(maxX, x + w / 2);
      minY = Math.min(minY, y - h / 2);
      maxY = Math.max(maxY, y + h / 2);
    };
    for (const vis of elems.values()) {
      const c = vis.group.getCenterPoint();
      grow(c.x, c.y, vis.w, vis.h);
    }
    for (const av of attrNodes.values()) {
      for (const n of av.nodes) {
        const c = n.ellipse.getCenterPoint();
        grow(c.x, c.y, n.w, n.h);
      }
    }
    // 自由端可能伸到图形包围盒之外，适应画布时要把它一起算进来
    for (const c of currentConnections) {
      if (c.mode === "free" && c.free_end) grow(c.free_end.x, c.free_end.y, 1, 1);
    }
    if (!Number.isFinite(minX)) return null;
    return { minX, minY, maxX, maxY };
  }

  function viewportFit(box: Bounds, pad = 48) {
    const cw = canvas.getWidth();
    const ch = canvas.getHeight();
    const w = Math.max(1, box.maxX - box.minX);
    const h = Math.max(1, box.maxY - box.minY);
    // 上界只防止空图被放到荒谬的倍数；下界必须足够小，
    // 否则超大页面（A4 纵向 / 复杂图）无法「完整显示」。
    const zoom = Math.max(0.02, Math.min(3, Math.min((cw - pad * 2) / w, (ch - pad * 2) / h)));
    const cx = (box.minX + box.maxX) / 2;
    const cy = (box.minY + box.maxY) / 2;
    // 必须走 setViewportTransform：它会重算每个对象的 oCoords，否则缩放后选中框 / 命中区域会错位
    canvas.setViewportTransform([zoom, 0, 0, zoom, cw / 2 - cx * zoom, ch / 2 - cy * zoom]);
    canvas.requestRenderAll();
    cb.onViewChanged?.();
  }

  /** 适应全部图形：只按实体 / 属性 / 联系 / 连线的包围盒计算视口 */
  function fitContent() {
    const box = contentBounds();
    if (!box) return false;
    viewportFit(box);
    return true;
  }

  /** 适应画布：只按页面（工作画布）计算视口；自由画布没有页面时不做任何事 */
  function fitPage() {
    if (!page.visible) return false;
    const box = {
      minX: page.left ?? 0,
      minY: page.top ?? 0,
      maxX: (page.left ?? 0) + (page.width ?? 0),
      maxY: (page.top ?? 0) + (page.height ?? 0),
    };
    viewportFit(box, 40);
    return true;
  }

  /**
   * 只设置工作画布的尺寸比例：页面盒按当前内容包围盒推导，不移动图形、不动视口。
   * 视口由 fitPage / fitContent / 用户手势单独控制，二者不再互相影响。
   */
  function setPageRatio(ratio: PageRatio) {
    pageRatio = ratio;
    const box = pageBoxFor(ratio, contentBounds());
    applyPage(box);
    orderLayers();
    canvas.requestRenderAll();
  }

  /** 智能布局算出的页面：直接采用，不再按内容包围盒二次推导；不改视口 */
  function setPageBox(box: PageBox | null) {
    applyPage(box);
    orderLayers();
    canvas.requestRenderAll();
  }

  function sync(
    elements: Element[],
    connections: Connection[],
    paint: Record<string, PaintState>,
  ) {
    // 重建图形时（属性扇形角度变化、改名等）会移除当前选中对象；
    // 静默处理 selection:cleared，让外层按 store 的选中状态重新选中新对象
    const wasSilent = silent;
    silent = true;
    currentElements = elements;
    currentConnections = connections;
    paintMap = paint;
    const eids = new Set(elements.map((e) => e.id));
    const cids = new Set(connections.map((c) => c.id));
    for (const id of [...elems.keys()]) if (!eids.has(id)) removeElement(id);
    for (const id of [...conns.keys()]) if (!cids.has(id)) removeConnection(id);
    for (const id of [...elemHalos.keys(), ...connHalos.keys()]) {
      if (!eids.has(id) && !cids.has(id)) clearHalo(id);
    }

    for (const model of elements) {
      const vis = elems.get(model.id);
      if (!vis) addElement(model);
      else if (vis.fingerprint !== elementFingerprint(model, style.key)) replaceElement(model);
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
      else if (
        Math.abs(vis.scale - scaleOf(c.from)) > 1e-4 ||
        connFingerprint(vis.data, style.key) !== connFingerprint(c, style.key)
      ) {
        replaceConnection(c);
      }
    }
    for (const model of elements) syncAttrNodes(model);
    for (const c of connections) {
      const vis = conns.get(c.id);
      if (vis) layoutConnection(vis, elems);
    }
    syncOwnerLines(elements);
    paintHalos();
    orderLayers();
    silent = wasSilent;
    canvas.requestRenderAll();
  }

  // ---------- 交互 ----------
  canvas.on("mouse:down", (opt) => {
    const e = opt.e as MouseEvent;
    const empty = !opt.target;
    const pt = canvas.getPointer(e);
    // 自由端连线：已固定起点时，点画布任意位置（包括别的图形上）都确认自由终点
    if (tool === "free" && freePreview) {
      cb.onFreePoint?.({ x: Math.round(pt.x), y: Math.round(pt.y) });
      clearFreePreview();
      suppressNodeDown = true;
      return;
    }
    if (e.button === 1 || spacePan || (e.button === 0 && empty && tool === "select")) {
      panning = { x: e.clientX, y: e.clientY };
      if (empty && !spacePan) canvas.discardActiveObject();
      return;
    }
    if (empty) {
      if (tool === "connect") {
        cb.onConnCancel();
        return;
      }
      // 落在整数像素上，新建的图形与文字才不会发虚
      cb.onBackgroundClick({ x: Math.round(pt.x), y: Math.round(pt.y) });
    }
  });
  canvas.on("mouse:move", (opt) => {
    const e = opt.e as MouseEvent;
    if (freePreview) updateFreePreview(canvas.getPointer(e));
    if (!panning) return;
    const dx = e.clientX - panning.x;
    const dy = e.clientY - panning.y;
    panning = { x: e.clientX, y: e.clientY };
    canvas.relativePan(new Point(dx, dy));
    canvas.requestRenderAll();
  });
  canvas.on("mouse:up", () => {
    panning = null;
    hideGuides();
  });

  canvas.on("mouse:wheel", (opt) => {
    const e = opt.e as WheelEvent;
    e.preventDefault();
    e.stopPropagation();
    const vpt = canvas.viewportTransform;
    if (!vpt) return;
    // 滚轮 = 缩放（以指针为中心）；Shift+滚轮 = 横向平移。
    // 平移仍可由拖动空白处 / 空格拖拽 / 中键完成，不依赖滚轮。
    if (e.shiftKey && !e.ctrlKey && !e.metaKey) {
      canvas.relativePan(new Point(-e.deltaY, 0));
      canvas.requestRenderAll();
    } else {
      const zoom = clamp(canvas.getZoom() * Math.pow(0.999, e.deltaY), 0.1, 4);
      canvas.zoomToPoint(new Point(e.offsetX, e.offsetY), zoom);
    }
    cb.onViewChanged?.();
  });

  function ensureGuides() {
    if (!guideV) {
      guideV = new Line([0, 0, 0, 1], {
        stroke: "#4F46E5",
        strokeWidth: 1,
        strokeDashArray: [4, 4],
        selectable: false,
        evented: false,
        objectCaching: false,
        visible: false,
        opacity: 0.6,
      });
      canvas.add(guideV as never);
    }
    if (!guideH) {
      guideH = new Line([0, 0, 1, 0], {
        stroke: "#4F46E5",
        strokeWidth: 1,
        strokeDashArray: [4, 4],
        selectable: false,
        evented: false,
        objectCaching: false,
        visible: false,
        opacity: 0.6,
      });
      canvas.add(guideH as never);
    }
  }

  function showGuides(x: number | null, y: number | null) {
    ensureGuides();
    if (x !== null && guideV) guideV.set({ x1: x, y1: -5000, x2: x, y2: 5000, visible: true });
    else if (guideV) guideV.set({ visible: false });
    if (y !== null && guideH) guideH.set({ x1: -5000, y1: y, x2: 5000, y2: y, visible: true });
    else if (guideH) guideH.set({ visible: false });
    if (guideV) canvas.bringObjectToFront(guideV as never);
    if (guideH) canvas.bringObjectToFront(guideH as never);
  }

  function hideGuides() {
    if (guideV) guideV.set({ visible: false });
    if (guideH) guideH.set({ visible: false });
  }

  /** 清除悬停高亮环 */
  function clearHoverRing() {
    if (hoverRing) {
      canvas.remove(hoverRing as never);
      hoverRing = null;
      hoverRingId = "";
    }
  }

  // 悬停元素：淡淡的靛蓝外框提示可交互（不覆盖教材的描边，也不拦截事件）
  canvas.on("mouse:over", (opt) => {
    const t = opt.target as ErTarget | undefined;
    if (t?.erKind !== "element" || !t.erId || t.erId === hoverRingId) return;
    clearHoverRing();
    const vis = elems.get(t.erId);
    if (!vis || canvas.getActiveObject() === vis.group) return;
    const c = vis.group.getCenterPoint();
    const s = scaleOf(t.erId);
    const ring = outline(vis.shape, vis.w, vis.h, c.x, c.y, 4 * s, {
      stroke: "#4F46E5",
      strokeWidth: 1.5 * s,
      opacity: 0.45,
    });
    canvas.add(ring as never);
    canvas.bringObjectToFront(ring as never);
    hoverRing = ring as unknown as FabricObject;
    hoverRingId = t.erId;
  });
  canvas.on("mouse:out", (opt) => {
    const t = opt.target as ErTarget | undefined;
    if (t?.erId === hoverRingId) clearHoverRing();
  });

  function emitSelection() {
    if (silent) return;
    const a = canvas.getActiveObject() as ErTarget | undefined;
    // 拖动自由端控制点时保持"连线"的选中语义，不要退化成空白选择
    if (a?.erKind === "freeEnd") return;
    if (a?.erKind === "attribute" && a.erAttrOwner !== undefined) {
      cb.onSelectAttribute(a.erAttrOwner, a.erAttrIndex ?? 0);
      return;
    }
    if (a?.erId && (a.erKind === "element" || a.erKind === "connection")) {
      const conn = a.erKind === "connection" ? currentConnections.find((c) => c.id === a.erId) : null;
      cb.onSelect(a.erKind, a.erId);
      if (conn && isFreeConnection(conn)) showFreeHandle(conn.id);
      return;
    }
    cb.onClearSelection();
  }

  canvas.on("selection:created", emitSelection);
  canvas.on("selection:updated", emitSelection);
  canvas.on("selection:cleared", () => {
    if (!silent) {
      hideFreeHandle();
      selectedVisual = null;
      cb.onClearSelection();
    }
  });
  canvas.on("mouse:down", (opt) => {
    // 自由端确认那一下已经消费了事件，避免又把它当成"点参与者"
    if (suppressNodeDown) {
      suppressNodeDown = false;
      return;
    }
    const t = opt.target as ErTarget | undefined;
    if (t?.erKind !== "element" || !t.erId) return;
    if (tool === "connect") {
      cb.onNodeClick(t.erId);
    } else if (tool === "free") {
      cb.onNodeClick(t.erId);
      beginFreePreview(t.erId);
    }
  });

  canvas.on("object:moving", (opt) => {
    const o = opt.target as ErTarget | undefined;
    if (!o) return;
    if (o.erKind === "freeEnd" && o.erId && o.getCenterPoint) {
      const vis = conns.get(o.erId);
      if (vis) {
        const p = o.getCenterPoint();
        // 只改这条线的本地终点，绝不吸附到任何图形
        vis.data.free_end = { x: p.x, y: p.y };
        layoutConnection(vis, elems);
        canvas.bringObjectToFront(o as never);
        canvas.requestRenderAll();
      }
      return;
    }
    if (o.erAttrOwner !== undefined && o.erAttrIndex !== undefined && o.getCenterPoint) {
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
    if (o.erKind !== "element" || !o.erId) return;
    const vis = elems.get(o.erId);
    if (!vis) return;
    if (snapEnabled) {
      const e = opt.e as MouseEvent;
      if (!e.altKey) {
        // 先吸附栅格，再让位给与其它元素中心的对齐线
        let cx = vis.group.left ?? 0;
        let cy = vis.group.top ?? 0;
        let alignX: number | null = null;
        let alignY: number | null = null;
        for (const other of elems.values()) {
          if (other === vis) continue;
          const p = other.group.getCenterPoint();
          if (Math.abs(cx - p.x) <= 6) alignX = p.x;
          if (Math.abs(cy - p.y) <= 6) alignY = p.y;
        }
        const nx = alignX ?? snapToGrid(cx, SNAP_STEP);
        const ny = alignY ?? snapToGrid(cy, SNAP_STEP);
        if (nx !== cx || ny !== cy) {
          vis.group.set({ left: nx, top: ny });
          vis.group.setCoords();
        }
        showGuides(alignX, alignY);
      } else {
        hideGuides();
      }
    }
    layoutFor(o.erId);
  });

  canvas.on("object:modified", (opt) => {
    const o = opt.target as ErTarget | undefined;
    if (!o) return;
    hideGuides();
    if (o.erKind === "freeEnd" && o.erId && o.getCenterPoint) {
      const p = o.getCenterPoint();
      cb.onFreeEndMoved?.(o.erId, Math.round(p.x), Math.round(p.y));
      return;
    }
    if (o.erAttrOwner !== undefined && o.erAttrIndex !== undefined && o.getCenterPoint) {
      const owner = elems.get(o.erAttrOwner);
      if (owner) {
        const c = owner.group.getCenterPoint();
        const p = o.getCenterPoint();
        cb.onAttrMoved?.(o.erAttrOwner, o.erAttrIndex, p.x - c.x, p.y - c.y);
      }
      return;
    }
    if (o.erKind !== "element" || !o.erId || !o.getCenterPoint) return;
    const vis = elems.get(o.erId);
    if (!vis) return;
    const g = vis.group;
    // 落点取整：图形与文字压在整数像素上才清晰
    const p = o.getCenterPoint();
    const x = Math.round(p.x);
    const y = Math.round(p.y);
    const scaleX = g.scaleX ?? 1;
    const scaleY = g.scaleY ?? 1;
    const scaled = Math.abs(scaleX - 1) > 0.01 || Math.abs(scaleY - 1) > 0.01;
    g.set({ left: x, top: y });
    if (scaled) g.set({ scaleX: 1, scaleY: 1 });
    g.setCoords();
    layoutFor(o.erId);
    const prev = currentElements.find((e) => e.id === o.erId)?.position;
    if (!prev || Math.abs(prev.x - x) > 0.5 || Math.abs(prev.y - y) > 0.5) {
      cb.onElementMoved(o.erId, x, y);
    }
    if (scaled) {
      cb.onElementResized?.(o.erId, Math.round(vis.w * scaleX), Math.round(vis.h * scaleY));
    }
  });

  function selectVisual(kind: "element" | "connection" | null, id: string | null, attrIndex?: number) {
    selectedVisual = kind && id ? { kind, id, attrIndex } : null;
    let wanted: FabricObject | null = null;
    if (kind === "element" && id) {
      hideFreeHandle();
      if (attrIndex !== undefined) {
        const node = attrNodes.get(id)?.nodes[attrIndex];
        if (node) wanted = node.ellipse as unknown as FabricObject;
      } else {
        const vis = elems.get(id);
        if (vis) wanted = vis.group as unknown as FabricObject;
      }
    } else if (kind === "connection" && id) {
      const vis = conns.get(id);
      const hit = vis?.parts.find((p) => p.tag === "hit");
      if (hit) wanted = hit.obj as unknown as FabricObject;
      if (!vis || !isFreeConnection(vis.data)) hideFreeHandle();
    } else {
      hideFreeHandle();
    }
    // 已经是同一个对象时不要 discard / setActiveObject：
    // 那会清掉 Fabric 正在进行的拖拽 _currentTransform，导致图形拖不动
    if (wanted && canvas.getActiveObject() === wanted) {
      if (kind === "connection" && id) {
        const vis = conns.get(id);
        if (vis && isFreeConnection(vis.data)) showFreeHandle(id);
      }
      canvas.requestRenderAll();
      return;
    }
    silent = true;
    clearHoverRing();
    canvas.discardActiveObject();
    if (wanted) canvas.setActiveObject(wanted);
    silent = false;
    if (kind === "connection" && id) {
      const vis = conns.get(id);
      if (vis && isFreeConnection(vis.data)) showFreeHandle(id);
    }
    canvas.requestRenderAll();
  }

  /** 把整张图缩放平移进视口 */
  function fitView(pad = 48) {
    if (page.visible) fitPage();
    else {
      const box = contentBounds();
      if (box) viewportFit(box, pad);
    }
  }

  function ensureVisible(x: number, y: number) {
    const vpt = canvas.viewportTransform;
    if (!vpt) return;
    const cw = canvas.getWidth();
    const ch = canvas.getHeight();
    const sx = x * vpt[0] + vpt[4];
    const sy = y * vpt[3] + vpt[5];
    const m = 90;
    if (sx < m || sx > cw - m || sy < m || sy > ch - m) {
      canvas.setViewportTransform([vpt[0], 0, 0, vpt[3], cw / 2 - x * vpt[0], ch / 2 - y * vpt[3]]);
      canvas.requestRenderAll();
      cb.onViewChanged?.();
    }
  }

  /** 诊断面板点击问题后：把目标带入视口，并让外环呼吸三次 */
  function flashHighlight(id: string) {
    const DUR = 1200;
    const objs: FabricObject[] = [];
    let center: { x: number; y: number } | null = null;
    let shape: ElementVisual["shape"] = "rectangle";
    let w = 0;
    let h = 0;

    const connVis = conns.get(id);
    if (connVis) {
      for (const p of connVis.parts) {
        if (p.tag !== "seg") continue;
        const ln = p.obj as Line;
        const glow = new Line([ln.x1, ln.y1, ln.x2, ln.y2], {
          stroke: "#4F46E5",
          strokeWidth: 8 * connVis.scale,
          strokeLineCap: "round",
          opacity: 0.55,
          selectable: false,
          evented: false,
          objectCaching: false,
        });
        canvas.add(glow as never);
        objs.push(glow as unknown as FabricObject);
      }
      center = connVis.mid;
    } else {
      const vis = elems.get(id);
      if (!vis) return;
      const c = vis.group.getCenterPoint();
      center = c;
      shape = vis.shape;
      w = vis.w;
      h = vis.h;
      const s = scaleOf(id);
      const ring = outline(shape, w, h, c.x, c.y, 8 * s, {
        stroke: "#4F46E5",
        strokeWidth: 3 * s,
      });
      canvas.add(ring as never);
      objs.push(ring as unknown as FabricObject);
    }

    if (!objs.length) return;
    if (center) ensureVisible(center.x, center.y);
    for (const o of objs) canvas.bringObjectToFront(o as never);
    const start = performance.now();
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / DUR);
      const pulse = 0.25 + 0.75 * Math.abs(Math.cos(t * Math.PI * 3));
      for (const o of objs) o.set({ opacity: Math.max(0.2, pulse * (1 - t * 0.3)) });
      canvas.requestRenderAll();
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        for (const o of objs) canvas.remove(o as never);
        canvas.requestRenderAll();
      }
    };
    requestAnimationFrame(step);
  }

  return {
    canvas,
    sync,
    /** 画布外观：只重绘，不写回 ER 数据 */
    setAppearance(next: CanvasAppearance) {
      applyAppearance(next);
      const keep = selectedVisual;
      sync(currentElements, currentConnections, paintMap);
      if (keep) selectVisual(keep.kind, keep.id, keep.attrIndex);
      canvas.requestRenderAll();
    },
    setTool(t: string) {
      tool = t;
      if (t !== "free") {
        clearFreePreview();
        suppressNodeDown = false;
      }
      canvas.defaultCursor = t === "select" ? "default" : "crosshair";
    },
    setSpacePan(on: boolean) {
      spacePan = on;
      // 空格拖拽时让 Fabric 不再命中目标，避免顺手选中 / 拖动图形
      canvas.skipTargetFind = on;
      canvas.defaultCursor = on ? "grab" : tool === "select" ? "default" : "crosshair";
    },
    setSnap(on: boolean) {
      snapEnabled = on;
    },
    setPageRatio,
    setPageBox,
    getPageBox: (): PageBox | null =>
      page.visible
        ? {
            x: page.left ?? 0,
            y: page.top ?? 0,
            w: page.width ?? 0,
            h: page.height ?? 0,
          }
        : null,
    getContentBounds: contentBounds,
    getPageRatio: () => pageRatio,
    fitPage,
    fitContent,
    selectVisual,
    flashHighlight,
    fitView,
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
      const vpt = canvas.viewportTransform;
      const oldW = canvas.getWidth();
      const oldH = canvas.getHeight();
      // 尺寸变化时保持视口中心的世界坐标，拖分隔条时内容不会"跳走"
      const cx = vpt ? (oldW / 2 - vpt[4]) / (vpt[0] || 1) : 0;
      const cy = vpt ? (oldH / 2 - vpt[5]) / (vpt[3] || 1) : 0;
      canvas.setDimensions({ width: snap(w), height: snap(h) });
      if (vpt) {
        canvas.setViewportTransform([
          vpt[0],
          0,
          0,
          vpt[3],
          canvas.getWidth() / 2 - cx * vpt[0],
          canvas.getHeight() / 2 - cy * vpt[3],
        ]);
      }
      canvas.requestRenderAll();
    },
    zoomBy(factor: number) {
      const vpt = canvas.viewportTransform;
      if (!vpt) return;
      const zoom = Math.max(0.1, Math.min(4, vpt[0] * factor));
      const cw = canvas.getWidth();
      const ch = canvas.getHeight();
      const sx = (cw / 2 - vpt[4]) / (vpt[0] || 1);
      const sy = (ch / 2 - vpt[5]) / (vpt[3] || 1);
      canvas.setViewportTransform([zoom, 0, 0, zoom, cw / 2 - sx * zoom, ch / 2 - sy * zoom]);
      canvas.requestRenderAll();
      cb.onViewChanged?.();
    },
    destroy() {
      canvas.dispose();
    },
  };
}

export type ErCanvasApi = ReturnType<typeof createErCanvas>;
