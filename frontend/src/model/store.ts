import { defineStore } from "pinia";
import { claimId, nextConnectionId, nextElementId, resetIds } from "./ids";
import {
  encodeBatchCheck,
  encodeConnectionAdded,
  encodeConnectionModified,
  encodeElementAdded,
  encodeElementDeleted,
  encodeElementModified,
} from "../protocol/encode";
import type {
  AttrShape,
  Cardinality,
  CardSymbol,
  CheckResult,
  Connection,
  ConnType,
  Element,
  Issue,
  PaintState,
  Position,
  Shape,
} from "../protocol/types";
import { isFreeConnection } from "../protocol/types";
import { ErCheckClient, type WsStatus } from "../protocol/ws";
import { detectOverlaps } from "../canvas/overlap";
import {
  computeAutoLayout,
  type AutoLayoutResult,
  type AutoLayoutStats,
} from "../canvas/layout";
import {
  ratioLabel,
  readStoredRatio,
  saveStoredRatio,
  type PageBox,
  type PageRatio,
} from "../canvas/page";
import { attrBaseAngle, attrNodeBoxes, computeSize } from "../canvas/shapes";
import { SCALE } from "../canvas/theme";

export type Tool = "select" | "entity" | "attribute" | "relationship" | "connect" | "free";

export interface Notice {
  id: number;
  level: "error" | "info" | "ok" | "warn";
  text: string;
}

export interface ModelSnapshot {
  elements: Element[];
  connections: Connection[];
  /** 页面与内容缩放也进入快照：撤销自动布局时页面一起回退 */
  pageRatio?: PageRatio;
  pageBox?: PageBox | null;
  contentScale?: number;
}

function emptyResult(): CheckResult {
  return { violations: [], suggestions: [] };
}

function cloneOffsets(src?: Record<string, Position>) {
  if (!src) return undefined;
  const out: Record<string, Position> = {};
  for (const [k, v] of Object.entries(src)) out[k] = { x: v.x, y: v.y };
  return out;
}

function cloneModel(elements: Element[], connections: Connection[]): ModelSnapshot {
  return {
    elements: elements.map((e) => ({
      ...e,
      attributes: [...e.attributes],
      position: { ...e.position },
      // 嵌套对象必须深拷贝，否则多个撤销快照共享同一个引用
      attr_offsets: cloneOffsets(e.attr_offsets),
      attr_style: e.attr_style ? { ...e.attr_style } : undefined,
      size: e.size ? { w: e.size.w, h: e.size.h } : undefined,
      layout_scale: e.layout_scale,
    })),
    connections: connections.map((c) => ({
      ...c,
      free_end: c.free_end ? { x: c.free_end.x, y: c.free_end.y } : undefined,
    })),
  };
}

/** 属性名去掉前缀，用于「删除中间一行后把排版数据跟着名字搬」 */
function attrNameKey(raw: string) {
  return String(raw ?? "").trim().replace(/^\*+/, "").replace(/^#+/, "").trim();
}

/** 按属性名把旧下标的排版数据重映射到新下标 */
function remapByIndex<T>(
  oldAttrs: string[],
  newAttrs: string[],
  map?: Record<string, T>,
): Record<string, T> | undefined {
  if (!map) return undefined;
  const out: Record<string, T> = {};
  const used = new Set<number>();
  newAttrs.forEach((raw, ni) => {
    const key = attrNameKey(raw);
    const oi = oldAttrs.findIndex((o, i) => !used.has(i) && attrNameKey(o) === key);
    if (oi < 0) return;
    used.add(oi);
    const value = map[String(oi)];
    if (value !== undefined) out[String(ni)] = value;
  });
  return out;
}

/** 连续编辑时合并发送，避免 Backend 同时收到多个 element_modified 造成结果乱序 */
const checkTimers = new Map<string, ReturnType<typeof setTimeout>>();
function cancelCheck(id: string) {
  const t = checkTimers.get(id);
  if (t) {
    clearTimeout(t);
    checkTimers.delete(id);
  }
}

function normIssues(raw: unknown): CheckResult {
  const list = (v: unknown): Issue[] => {
    if (!Array.isArray(v)) return [];
    return v
      .map((it) => {
        const o = (it ?? {}) as Record<string, unknown>;
        return {
          rule_id: String(o.rule_id ?? o.ruleId ?? ""),
          level: (o.level === "warn" ? "warn" : "error") as Issue["level"],
          message: String(o.message ?? ""),
        };
      })
      .filter((it) => it.message);
  };
  if (!raw || typeof raw !== "object") return emptyResult();
  const obj = raw as Record<string, unknown>;
  return { violations: list(obj.violations), suggestions: list(obj.suggestions) };
}

export function severityOf(r: CheckResult | undefined, painted: boolean): PaintState {
  if (!painted || !r) return "pending";
  if (r.violations.length) return "error";
  if (r.suggestions.length) return "warn";
  return "ok";
}

let noticeSeq = 1;
let client: ErCheckClient | null = null;

export const useErStore = defineStore("er", {
  state: () => ({
    elements: [] as Element[],
    connections: [] as Connection[],
    results: {} as Record<string, CheckResult>,
    painted: {} as Record<string, boolean>,
    tool: "select" as Tool,
    continuous: false,
    selectedKind: null as "element" | "connection" | null,
    selectedId: null as string | null,
    /** 选中的属性（实体 id + 属性下标），用于检查器高亮与 Delete 删单个属性 */
    selectedAttr: null as { ownerId: string; index: number } | null,
    pendingFromId: null as string | null,
    wsStatus: "closed" as WsStatus,
    notices: [] as Notice[],
    undoStack: [] as ModelSnapshot[],
    redoStack: [] as ModelSnapshot[],
    canvasTick: 0,
    highlightId: null as string | null,
    highlightTick: 0,
    fitTick: 0,
    /** 显式视口命令：适应画布（页面） / 适应全部图形。二者互不混用。 */
    fitPageTick: 0,
    fitContentTick: 0,
    /** 页面比例 / 页面盒 / 内容级缩放：自动布局的持久状态 */
    pageRatio: readStoredRatio(),
    pageBox: null as PageBox | null,
    contentScale: 1,
    layoutStats: null as AutoLayoutStats | null,
    layoutWarnings: [] as string[],
    /** 最近一次自动布局在撤销栈里的位置；-1 表示不可撤销布局 */
    layoutMark: -1,
    /** 页面变化计数：画布据此应用新页面并适应视口 */
    pageTick: 0,
  }),
  getters: {
    selectedElement(state): Element | null {
      if (state.selectedKind !== "element" || !state.selectedId) return null;
      return state.elements.find((e) => e.id === state.selectedId) ?? null;
    },
    selectedConnection(state): Connection | null {
      if (state.selectedKind !== "connection" || !state.selectedId) return null;
      return state.connections.find((c) => c.id === state.selectedId) ?? null;
    },
    allIssues(state) {
      const rows: Array<{ id: string; kind: "element" | "connection"; issue: Issue }> = [];
      const overlaps = detectOverlaps(state.elements, state.connections);
      const push = (id: string, kind: "element" | "connection") => {
        const r = state.results[id];
        if (r && state.painted[id]) {
          for (const issue of r.violations) rows.push({ id, kind, issue });
          for (const issue of r.suggestions) rows.push({ id, kind, issue });
        }
        // 几何重叠是前端本地规则：不管后端有没有回包都要显示
        for (const issue of overlaps.get(id) ?? []) rows.push({ id, kind, issue });
      };
      for (const e of state.elements) push(e.id, "element");
      for (const c of state.connections) {
        if (isFreeConnection(c)) {
          // 后端协议没有自由端连线：本地标记为草稿，绝不伪造后端结果
          rows.push({
            id: c.id,
            kind: "connection",
            issue: {
              rule_id: "D01",
              level: "warn",
              message: "草稿：自由端连线只保存在前端，未提交后端校验。",
            },
          });
          continue;
        }
        push(c.id, "connection");
      }
      return rows;
    },
    paintStats(state) {
      const s = { error: 0, warn: 0, ok: 0, pending: 0 };
      const overlaps = detectOverlaps(state.elements, state.connections);
      const count = (id: string, free = false) => {
        if (free) {
          // 自由端连线没有后端结果，用"建议"颜色表示草稿状态
          s.warn += 1;
          return;
        }
        if (overlaps.get(id)?.length) {
          s.error += 1;
          return;
        }
        s[severityOf(state.results[id], !!state.painted[id])] += 1;
      };
      state.elements.forEach((e) => count(e.id));
      state.connections.forEach((c) => count(c.id, isFreeConnection(c)));
      return s;
    },
  },
  actions: {
    bump() {
      this.canvasTick += 1;
    },
    toast(level: Notice["level"], text: string) {
      const id = noticeSeq++;
      this.notices.push({ id, level, text });
      setTimeout(() => {
        this.notices = this.notices.filter((n) => n.id !== id);
      }, 4500);
    },
    /**
     * 智能自动布局（独立操作入口）。
     * 只写 position / size / attr_offsets / layout_scale / free_end；
     * 实体、属性、联系、基数、类型等业务数据完全不动，且整次操作可撤销。
     */
    autoLayout(
      ratio?: PageRatio,
      opts: { silent?: boolean; persist?: boolean } = {},
    ): AutoLayoutResult | null {
      const target = ratio ?? this.pageRatio;
      if (!this.elements.length) {
        this.layoutStats = null;
        this.layoutWarnings = [];
        this.setPageRatio(target, { relayout: false, silent: opts.silent, persist: opts.persist });
        return null;
      }
      const result = computeAutoLayout(this.elements, this.connections, target, this.pageBox);
      if (!result) return null;
      this.pushUndo();
      this.layoutMark = this.undoStack.length;
      for (const el of this.elements) {
        const pos = result.positions[el.id];
        const size = result.sizes[el.id];
        if (pos) el.position = { x: pos.x, y: pos.y };
        if (size) el.size = { w: size.w, h: size.h };
        // 自动布局重排属性扇形：清掉用户旧的手动偏移，保证统一节奏
        el.attr_offsets = { ...(result.offsets[el.id] ?? {}) };
        el.layout_scale = result.scale;
      }
      for (const c of this.connections) {
        const end = result.freeEnds[c.id];
        if (end && isFreeConnection(c)) c.free_end = { x: end.x, y: end.y };
      }
      this.pageRatio = target;
      this.pageBox = result.pageBox ? { ...result.pageBox } : null;
      this.contentScale = result.scale;
      this.layoutStats = result.stats;
      this.layoutWarnings = [...result.warnings];
      if (opts.persist !== false) saveStoredRatio(target);
      this.bump();
      this.pageTick += 1;
      // 自动布局只改图形排列与内容级缩放；不改比例、不改画布宽高、不重置视口。
      // 有当前页面盒时内容装进该页面；自由画布才以旧内容中心为锚。
      if (!opts.silent) {
        const pct = Math.round(result.stats.fill * 100);
        if (result.warnings.length) {
          this.toast("warn", result.warnings[0]);
        } else if (result.pageBox) {
          this.toast(
            "ok",
            `已按 ${ratioLabel(target)} 自动布局 · ${result.stats.nodes} 个参与者 · 页面利用 ${pct}% · 字号 ${Math.round(result.stats.minFont)}px`,
          );
        } else {
          this.toast(
            "ok",
            `已按自由画布重新排列 · ${result.stats.nodes} 个参与者 · 字号 ${Math.round(result.stats.minFont)}px`,
          );
        }
      }
      return result;
    },
    /**
     * 切换画布比例：只改变工作画布的尺寸约束，不移动图形。
     * relayout=true 仅用于回归 / 明确要求"按新比例重排"的调用；普通 UI 选择不重排。
     * 显式切换比例会让视口重新适应新页面（用户刚改了画布尺寸），但不会改动图形数据。
     */
    setPageRatio(
      ratio: PageRatio,
      opts: { relayout?: boolean; silent?: boolean; persist?: boolean } = {},
    ) {
      const changed = this.pageRatio !== ratio;
      // 纯比例切换进入撤销栈；带 relayout 的调用由 autoLayout 统一压栈，
      // 避免一次操作生成两个撤销步骤。
      if (changed && opts.relayout !== true) this.pushUndo();
      this.pageRatio = ratio;
      if (opts.persist !== false) saveStoredRatio(ratio);
      // 只有显式 relayout=true 才重排；普通比例切换只改画布尺寸。
      if (opts.relayout === true && this.elements.length) {
        this.autoLayout(ratio, { silent: opts.silent, persist: opts.persist });
        // 用户明确换了画布比例：把新页面完整装进视口，避免页面停在屏幕外。
        this.fitTick += 1;
        return;
      }
      // 没有新布局时清空旧页面盒，让画布按当前内容重新推导页面。
      this.pageBox = null;
      this.layoutStats = null;
      this.layoutWarnings = [];
      this.pageTick += 1;
      // 比例是显式视口尺寸变化：适应画布（页面），但不重排图形。
      this.fitTick += 1;
    },
    /** 「重新排列」：保持当前页面比例，重排一次；不改比例 / 视口 */
    relayout() {
      return this.autoLayout(this.pageRatio, { silent: false });
    },
    /** 「撤销布局」：只有最近一次操作就是自动布局时才回退，避免误撤别的编辑 */
    undoLayout() {
      if (this.layoutMark > 0 && this.layoutMark === this.undoStack.length) {
        this.undo();
        this.layoutMark = -1;
        this.toast("info", "已撤销上次自动布局");
        return true;
      }
      this.toast("info", "没有可撤销的自动布局（可能之后又做过其它编辑）");
      return false;
    },
    /** 「适应画布」：只把页面（工作画布）完整装进视口 */
    fitPageNow() {
      this.fitPageTick += 1;
    },
    /**
     * 画布上报实际页面盒（比例切换 / 导入 / 首次挂载都会触发）。
     * 只同步几何状态，用来让下一次自动布局知道当前画布尺寸；
     * 不触发 pageTick，避免和画布互相回调形成循环。
     */
    syncPageBox(box: PageBox | null) {
      const next = box ? { ...box } : null;
      const cur = this.pageBox;
      if (!next && !cur) return;
      if (
        next &&
        cur &&
        next.x === cur.x &&
        next.y === cur.y &&
        next.w === cur.w &&
        next.h === cur.h
      ) {
        return;
      }
      this.pageBox = next;
    },
    /** 「适应全部图形」：只把所有实体 / 属性 / 联系 / 连线装进视口 */
    fitContentNow() {
      this.fitContentTick += 1;
    },
    takenIds() {
      return new Set([...this.elements.map((e) => e.id), ...this.connections.map((c) => c.id)]);
    },
    findElement(id: string) {
      return this.elements.find((e) => e.id === id) ?? null;
    },
    findConnection(id: string) {
      return this.connections.find((c) => c.id === id) ?? null;
    },
    /** 该连线是否是"联系分支"（菱形联系 ↔ 矩形实体），只有这种线才能写基数 */
    isRelationBranch(id: string) {
      const c = this.findConnection(id);
      if (!c) return false;
      const a = this.findElement(c.from);
      const b = this.findElement(c.to);
      return (
        (a?.shape === "diamond" && b?.shape === "rectangle") ||
        (a?.shape === "rectangle" && b?.shape === "diamond")
      );
    },
    /** 当前模型 + 页面状态的完整快照（撤销 / 重做共用） */
    snapshot(): ModelSnapshot {
      return {
        ...cloneModel(this.elements, this.connections),
        pageRatio: this.pageRatio,
        pageBox: this.pageBox ? { ...this.pageBox } : null,
        contentScale: this.contentScale,
      };
    },
    pushUndo() {
      this.undoStack.push(this.snapshot());
      if (this.undoStack.length > 80) this.undoStack.shift();
      this.redoStack = [];
    },
    restore(snap: ModelSnapshot) {
      const model = cloneModel(snap.elements, snap.connections);
      this.elements = model.elements;
      this.connections = model.connections;
      this.results = {};
      this.painted = {};
      this.pendingFromId = null;
      this.pageRatio = snap.pageRatio ?? this.pageRatio;
      this.pageBox = snap.pageBox ? { ...snap.pageBox } : null;
      this.contentScale = snap.contentScale ?? this.contentScale;
      this.layoutStats = null;
      this.layoutWarnings = [];
      this.layoutMark = -1;
      this.bump();
      this.fitTick += 1;
      this.pageTick += 1;
      this.batchCheck();
    },
    undo() {
      const prev = this.undoStack.pop();
      if (!prev) return;
      // 重做栈也必须保存页面状态，否则重做比例切换 / 自动布局会丢掉 pageRatio / pageBox
      this.redoStack.push(this.snapshot());
      this.restore(prev);
    },
    redo() {
      const next = this.redoStack.pop();
      if (!next) return;
      this.undoStack.push(this.snapshot());
      this.restore(next);
    },
    setTool(tool: Tool, continuous = false) {
      if (tool === "select") {
        this.tool = "select";
        this.continuous = false;
        this.pendingFromId = null;
        return;
      }
      if (continuous) {
        // 双击：连续创建模式（可以一直画，Esc 或再点该工具退出）
        this.tool = tool;
        this.continuous = true;
      } else if (this.tool === tool) {
        // 单击已激活的工具 = 退出创建
        this.tool = "select";
        this.continuous = false;
      } else {
        // 单击其它工具 = 单次创建（画完一个自动回到选择）
        this.tool = tool;
        this.continuous = false;
      }
      if (this.tool !== "connect" && this.tool !== "free") this.pendingFromId = null;
    },
    select(kind: "element" | "connection" | null, id: string | null) {
      this.selectedKind = kind;
      this.selectedId = id;
      this.selectedAttr = null;
    },
    /** 选中某个实体的某个属性椭圆：检查器沿用实体，同时高亮对应属性行 */
    selectAttribute(ownerId: string, index: number) {
      this.selectedKind = "element";
      this.selectedId = ownerId;
      this.selectedAttr = { ownerId, index };
    },
    clearSelection() {
      this.selectedKind = null;
      this.selectedId = null;
      this.selectedAttr = null;
    },
    /** 诊断面板点击问题：选中该元素/连线，并请求画布闪烁高亮 */
    focus(kind: "element" | "connection" | null, id: string | null) {
      this.select(kind, id);
      if (id) {
        this.highlightId = id;
        this.highlightTick += 1;
      }
    },
    /** 工具轨「适应画布」：请求整图缩放进视口 */
    fitToView() {
      this.fitTick += 1;
    },
    /**
     * 整理布局：元素吸附 8px 栅格，再把互相压住的元素（含属性扇形）推开。
     * 只动位置，不连线、不改语义，可撤销。
     */
    arrange() {
      if (!this.elements.length) return;
      this.pushUndo();
      this.layoutMark = this.undoStack.length;
      const gap = 28 * (this.contentScale || 1);
      const snapStep = 8 * (this.contentScale || 1);
      const bounds = () => {
        return this.elements.map((e) => {
          const { W, H } = computeSize(e);
          let minX = e.position.x - W / 2;
          let maxX = e.position.x + W / 2;
          let minY = e.position.y - H / 2;
          let maxY = e.position.y + H / 2;
          for (const box of attrNodeBoxes(e, attrBaseAngle(e, this.elements, this.connections))) {
            minX = Math.min(minX, box.cx - box.w / 2);
            maxX = Math.max(maxX, box.cx + box.w / 2);
            minY = Math.min(minY, box.cy - box.h / 2);
            maxY = Math.max(maxY, box.cy + box.h / 2);
          }
          return { minX, maxX, minY, maxY };
        });
      };
      for (let iter = 0; iter < 40; iter++) {
        const boxes = bounds();
        let moved = false;
        for (let i = 0; i < this.elements.length; i++) {
          for (let j = i + 1; j < this.elements.length; j++) {
            const A = boxes[i];
            const B = boxes[j];
            const ox = Math.min(A.maxX, B.maxX) - Math.max(A.minX, B.minX) + gap;
            const oy = Math.min(A.maxY, B.maxY) - Math.max(A.minY, B.minY) + gap;
            if (ox <= 0 || oy <= 0) continue;
            const a = this.elements[i];
            const b = this.elements[j];
            if (ox < oy) {
              const dir = a.position.x <= b.position.x ? -1 : 1;
              a.position.x += (dir * ox) / 2;
              b.position.x -= (dir * ox) / 2;
            } else {
              const dir = a.position.y <= b.position.y ? -1 : 1;
              a.position.y += (dir * oy) / 2;
              b.position.y -= (dir * oy) / 2;
            }
            moved = true;
          }
        }
        if (!moved) break;
      }
      for (const e of this.elements) {
        e.position = {
          x: Math.round(e.position.x / snapStep) * snapStep,
          y: Math.round(e.position.y / snapStep) * snapStep,
        };
      }
      this.bump();
      this.fitTick += 1;
    },
    markPending(id: string) {
      this.painted[id] = false;
      this.results[id] = emptyResult();
      this.bump();
    },
    applyResult(id: string, raw: unknown) {
      if (!this.findElement(id) && !this.findConnection(id)) return;
      this.results[id] = normIssues(raw);
      this.painted[id] = true;
      this.bump();
    },
    ensureClient() {
      if (client) return client;
      client = new ErCheckClient({
        onStatus: (s) => {
          this.wsStatus = s;
        },
        onOpen: () => {
          if (this.elements.length || this.connections.length) this.batchCheck();
        },
        onResult: (id, violations, suggestions) => {
          this.applyResult(id, { violations, suggestions });
        },
        onBatchResult: (results) => {
          for (const [id, payload] of Object.entries(results)) {
            this.applyResult(id, payload);
          }
        },
        onError: (message) => {
          this.toast("error", message);
        },
      });
      client.connect();
      return client;
    },
    sendElementCheck(
      event: "element_added" | "element_modified" | "element_deleted",
      element: Element,
      changes?: { attributes_changed: boolean; label_changed: boolean },
    ) {
      this.markPending(element.id);
      const c = this.ensureClient();
      if (event === "element_modified") {
        // 尾随合并：连续改名 / 改属性只把最后一次状态发给后端
        cancelCheck(element.id);
        checkTimers.set(
          element.id,
          setTimeout(() => {
            checkTimers.delete(element.id);
            const cur = this.findElement(element.id);
            if (!cur) return;
            c.sendCheck(
              encodeElementModified(cur, changes ?? { attributes_changed: false, label_changed: false }),
            );
          }, 150),
        );
        return;
      }
      cancelCheck(element.id);
      if (event === "element_added") c.sendCheck(encodeElementAdded(element));
      else c.sendCheck(encodeElementDeleted(element));
    },
    sendConnectionCheck(event: "connection_added" | "connection_modified", connection: Connection) {
      // 自由端连线只存在于前端；不伪造后端连接数据，也不发 empty `to` 的报文
      if (isFreeConnection(connection)) return;
      this.markPending(connection.id);
      const c = this.ensureClient();
      if (event === "connection_modified") {
        cancelCheck(connection.id);
        checkTimers.set(
          connection.id,
          setTimeout(() => {
            checkTimers.delete(connection.id);
            const cur = this.findConnection(connection.id);
            if (!cur) return;
            c.sendCheck(encodeConnectionModified(cur));
          }, 150),
        );
        return;
      }
      cancelCheck(connection.id);
      c.sendCheck(encodeConnectionAdded(connection));
    },
    batchCheck() {
      for (const e of this.elements) this.painted[e.id] = false;
      for (const c of this.connections) {
        if (!isFreeConnection(c)) this.painted[c.id] = false;
      }
      this.bump();
      this.ensureClient().sendBatch(
        encodeBatchCheck(
          this.elements,
          this.connections.filter((c) => !isFreeConnection(c)),
        ),
      );
    },
    addElement(shape: Shape, position: { x: number; y: number }) {
      this.pushUndo();
      const id = nextElementId(shape, this.takenIds());
      const n = this.elements.filter((e) => e.shape === shape).length + 1;
      const label =
        shape === "rectangle" ? `实体${n}` : shape === "ellipse" ? `属性${n}` : `联系${n}`;
      const el: Element = {
        id,
        shape,
        label,
        attributes: [],
        position: { x: position.x, y: position.y },
        // 新建元素继承当前页面的内容级缩放，避免同屏出现两种字号节奏
        layout_scale: this.contentScale,
      };
      this.elements.push(el);
      this.select("element", id);
      this.bump();
      this.sendElementCheck("element_added", el);
      if (!this.continuous) this.tool = "select";
      return el;
    },
    updateElement(
      id: string,
      patch: {
        label?: string;
        attributes?: string[];
        is_weak?: boolean;
        is_identifying?: boolean;
        attr_style?: Record<string, AttrShape>;
      },
    ) {
      const el = this.findElement(id);
      if (!el) return;
      const changes = { label_changed: false, attributes_changed: false };
      if (patch.label !== undefined && patch.label !== el.label) changes.label_changed = true;
      if (patch.attributes !== undefined && JSON.stringify(patch.attributes) !== JSON.stringify(el.attributes)) {
        changes.attributes_changed = true;
      }
      const weakChanged = patch.is_weak !== undefined && (patch.is_weak ?? false) !== (el.is_weak ?? false);
      const identChanged =
        patch.is_identifying !== undefined && (patch.is_identifying ?? false) !== (el.is_identifying ?? false);
      const styleChanged =
        patch.attr_style !== undefined && JSON.stringify(patch.attr_style) !== JSON.stringify(el.attr_style ?? {});
      if (!changes.label_changed && !changes.attributes_changed && !weakChanged && !identChanged && !styleChanged) {
        return;
      }
      this.pushUndo();
      if (changes.label_changed) el.label = patch.label ?? el.label;
      if (changes.attributes_changed) {
        const nextAttrs = patch.attributes ?? [];
        // 删除 / 重排属性后，把排版数据按下标搬到新位置，避免椭圆乱跳
        el.attr_offsets = remapByIndex(el.attributes, nextAttrs, el.attr_offsets);
        el.attr_style = patch.attr_style ?? remapByIndex(el.attributes, nextAttrs, el.attr_style);
        el.attributes = [...nextAttrs];
      } else if (patch.attr_style !== undefined) {
        el.attr_style = { ...patch.attr_style };
      }
      if (weakChanged) el.is_weak = patch.is_weak;
      if (identChanged) el.is_identifying = patch.is_identifying;
      this.bump();
      // 尺寸 / 双线 / 属性画法都是排版信息，不进协议；只有名字 / 属性 / 弱实体要重查
      if (changes.label_changed || changes.attributes_changed || weakChanged) {
        this.sendElementCheck("element_modified", el, changes);
      }
    },
    /** 拖拽控制点改尺寸：只影响画布排版，不上送后端 */
    resizeElement(id: string, w: number, h: number) {
      const el = this.findElement(id);
      if (!el) return;
      const nextW = Math.max(1, Math.round(w));
      const nextH = Math.max(1, Math.round(h));
      if (el.size && el.size.w === nextW && el.size.h === nextH) return;
      this.pushUndo();
      el.size = { w: nextW, h: nextH };
      this.bump();
    },
    setAttrShape(id: string, index: number, shape: AttrShape) {
      const el = this.findElement(id);
      if (!el) return;
      const next = { ...(el.attr_style ?? {}) };
      if (shape === "normal") delete next[String(index)];
      else next[String(index)] = shape;
      this.updateElement(id, { attr_style: next });
    },
    updatePosition(id: string, x: number, y: number) {
      const el = this.findElement(id);
      if (!el) return;
      if (el.position.x === x && el.position.y === y) return;
      this.pushUndo();
      el.position = { x, y };
    },
    updateAttrOffset(id: string, index: number, x: number, y: number) {
      const el = this.findElement(id);
      if (!el) return;
      this.pushUndo();
      const offs = { ...(el.attr_offsets ?? {}) };
      offs[String(index)] = { x: Math.round(x), y: Math.round(y) };
      el.attr_offsets = offs;
      this.bump();
    },
    removeSelected() {
      // 选中某个属性椭圆时，Delete 只删这一条属性
      if (this.selectedAttr) {
        const { ownerId, index } = this.selectedAttr;
        const el = this.findElement(ownerId);
        if (el) {
          this.updateElement(ownerId, { attributes: el.attributes.filter((_, i) => i !== index) });
          this.selectedAttr = null;
        }
        return;
      }
      if (this.selectedKind === "connection" && this.selectedId) {
        this.removeConnection(this.selectedId);
        return;
      }
      if (this.selectedKind === "element" && this.selectedId) {
        this.removeElement(this.selectedId);
      }
    },
    removeElement(id: string) {
      const el = this.findElement(id);
      if (!el) return;
      cancelCheck(id);
      this.pushUndo();
      this.connections = this.connections.filter((c) => c.from !== id && c.to !== id);
      this.elements = this.elements.filter((e) => e.id !== id);
      delete this.results[id];
      delete this.painted[id];
      if (this.selectedId === id) this.clearSelection();
      if (this.pendingFromId === id) this.pendingFromId = null;
      this.bump();
      this.sendElementCheck("element_deleted", el);
    },
    inferConnType(fromId: string, toId: string): ConnType {
      const a = this.findElement(fromId);
      const b = this.findElement(toId);
      if (a?.shape === "diamond" || b?.shape === "diamond") return "diamond_line";
      return "line";
    },
    addConnection(from: string, to: string) {
      if (from === to) {
        this.toast("warn", "不能连接同一元素");
        return null;
      }
      if (!this.findElement(from) || !this.findElement(to)) return null;
      if (this.connections.some((c) => (c.from === from && c.to === to) || (c.from === to && c.to === from))) {
        this.toast("info", "这两点之间已有连线");
        return null;
      }
      this.pushUndo();
      const conn: Connection = {
        id: nextConnectionId(this.takenIds()),
        from,
        to,
        type: this.inferConnType(from, to),
        label: "",
        cardinality: null,
      };
      this.connections.push(conn);
      this.select("connection", conn.id);
      this.pendingFromId = null;
      this.bump();
      this.sendConnectionCheck("connection_added", conn);
      if (!this.continuous) this.tool = "select";
      return conn;
    },
    /**
     * 自由端连线：起点连接参与者，终点是画布上的任意坐标。
     * 它是纯前端本地模型（mode="free"），不发送后端、也不伪造 Connection 协议字段。
     */
    addFreeConnection(from: string, point: { x: number; y: number }) {
      const el = this.findElement(from);
      if (!el) return null;
      const x = Math.round(point.x);
      const y = Math.round(point.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      this.pushUndo();
      const conn: Connection = {
        id: nextConnectionId(this.takenIds()),
        from,
        to: "",
        type: "line",
        label: "",
        cardinality: null,
        mode: "free",
        free_end: { x, y },
      };
      this.connections.push(conn);
      this.select("connection", conn.id);
      this.pendingFromId = null;
      this.bump();
      if (!this.continuous) this.tool = "select";
      return conn;
    },
    /** 拖动自由端控制点后写回坐标；只调整这一条本地连线 */
    updateFreeEndpoint(id: string, x: number, y: number) {
      const c = this.findConnection(id);
      if (!c || !isFreeConnection(c)) return;
      const nx = Math.round(x);
      const ny = Math.round(y);
      if (!Number.isFinite(nx) || !Number.isFinite(ny)) return;
      if (c.free_end && c.free_end.x === nx && c.free_end.y === ny) return;
      this.pushUndo();
      c.free_end = { x: nx, y: ny };
      this.bump();
    },
    updateConnection(
      id: string,
      patch: { type?: ConnType; label?: string; cardinality?: Cardinality },
    ) {
      const c = this.findConnection(id);
      if (!c) return;
      // 自由端连线没有基数 / 联系语义，避免误改出伪协议数据
      if (isFreeConnection(c)) return;
      let changed = false;
      if (patch.type !== undefined && patch.type !== c.type) changed = true;
      if (patch.label !== undefined && patch.label !== c.label) changed = true;
      if (patch.cardinality !== undefined && (patch.cardinality ?? null) !== (c.cardinality ?? null)) {
        changed = true;
      }
      if (!changed) return;
      this.pushUndo();
      if (patch.type !== undefined) c.type = patch.type;
      if (patch.label !== undefined) c.label = patch.label;
      if (patch.cardinality !== undefined) c.cardinality = patch.cardinality;
      this.bump();
      this.sendConnectionCheck("connection_modified", c);
    },
    removeConnection(id: string) {
      if (!this.findConnection(id)) return;
      this.pushUndo();
      this.connections = this.connections.filter((c) => c.id !== id);
      delete this.results[id];
      delete this.painted[id];
      if (this.selectedId === id) this.clearSelection();
      this.bump();
    },
    clickConnectEndpoint(id: string) {
      if (this.tool === "free") {
        this.pendingFromId = id;
        this.select("element", id);
        return;
      }
      if (!this.pendingFromId) {
        this.pendingFromId = id;
        return;
      }
      const from = this.pendingFromId;
      this.pendingFromId = null;
      this.addConnection(from, id);
    },
    importDiagram(data: unknown) {
      const raw = data as { elements?: unknown; connections?: unknown };
      if (!raw || !Array.isArray(raw.elements)) {
        this.toast("error", "导入失败：缺少 elements 数组");
        return false;
      }
      this.pushUndo();
      resetIds();
      const elements: Element[] = raw.elements.map((item, index) => {
        const e = (item ?? {}) as Record<string, unknown>;
        const id = String(e.id || `rect_${String(index + 1).padStart(3, "0")}`);
        claimId(id);
        const shape: Shape = ["rectangle", "ellipse", "diamond"].includes(String(e.shape))
          ? (e.shape as Shape)
          : "rectangle";
        const pos = (e.position ?? {}) as Record<string, unknown>;
        const attrStyle: Record<string, AttrShape> = {};
        if (e.attr_style && typeof e.attr_style === "object") {
          for (const [k, v] of Object.entries(e.attr_style as Record<string, unknown>)) {
            if (v === "multi" || v === "derived") attrStyle[k] = v;
          }
        }
        const rawSize = (e.size ?? {}) as Record<string, unknown>;
        const size =
          typeof rawSize.w === "number" && typeof rawSize.h === "number" && rawSize.w > 0 && rawSize.h > 0
            ? { w: Math.round(rawSize.w), h: Math.round(rawSize.h) }
            : undefined;
        const layoutScale =
          typeof e.layout_scale === "number" && Number.isFinite(e.layout_scale) && e.layout_scale > 0
            ? Math.max(SCALE.min, Math.min(SCALE.max, e.layout_scale))
            : undefined;
        // 兼容旧文件 / 手工编辑：只接受带有限 x/y 的属性偏移，
        // 否则 `{}` 会被当成"已手动定位"，导致椭圆坐标变成 NaN。
        const offsets: Record<string, { x: number; y: number }> = {};
        if (e.attr_offsets && typeof e.attr_offsets === "object") {
          for (const [k, v] of Object.entries(e.attr_offsets as Record<string, unknown>)) {
            const p = (v ?? {}) as Record<string, unknown>;
            if (typeof p.x === "number" && typeof p.y === "number" && Number.isFinite(p.x) && Number.isFinite(p.y)) {
              offsets[k] = { x: p.x, y: p.y };
            }
          }
        }
        return {
          id,
          shape,
          label: String(e.label ?? ""),
          attributes: Array.isArray(e.attributes) ? e.attributes.map((a) => String(a)) : [],
          is_weak: e.is_weak === true,
          is_identifying: e.is_identifying === true,
          attr_offsets: offsets,
          attr_style: Object.keys(attrStyle).length ? attrStyle : undefined,
          size,
          layout_scale: layoutScale,
          position: {
            x: typeof pos.x === "number" ? pos.x : 140 + (index % 4) * 280,
            y: typeof pos.y === "number" ? pos.y : 140 + Math.floor(index / 4) * 200,
          },
        };
      });
      const elementIds = new Set(elements.map((e) => e.id));
      const connections: Connection[] = (Array.isArray(raw.connections) ? raw.connections : [])
        .map((item, index) => {
          const c = (item ?? {}) as Record<string, unknown>;
          const id = String(c.id || `conn_${String(index + 1).padStart(3, "0")}`);
          claimId(id);
          const card = c.cardinality;
          // 兼容旧格式 "M:N"/"1:N"（取第一个符号）与新的单字符 "1"/"N"/"M"/"P"
          const legacy = card === "1:1" || card === "1:N" || card === "M:N" || card === "N:M" || card === "M:N:P";
          const cardinality: Cardinality =
            card === "1" || card === "N" || card === "M" || card === "P"
              ? card
              : legacy
                ? (String(card).split(":")[0] as CardSymbol)
                : null;
          const free = c.mode === "free";
          const fp = (c.free_end ?? {}) as Record<string, unknown>;
          const freeEnd =
            free && typeof fp.x === "number" && typeof fp.y === "number"
              ? { x: fp.x, y: fp.y }
              : undefined;
          return {
            id,
            from: String(c.from ?? ""),
            to: free ? "" : String(c.to ?? ""),
            type: c.type === "diamond_line" ? ("diamond_line" as const) : ("line" as const),
            label: String(c.label ?? ""),
            cardinality,
            mode: free ? ("free" as const) : ("smart" as const),
            free_end: freeEnd,
          };
        })
        .filter((c) => {
          if (!elementIds.has(c.from)) return false;
          if (isFreeConnection(c)) return !!c.free_end;
          return !!c.to && elementIds.has(c.to);
        });
      this.elements = elements;
      this.connections = connections;
      this.results = {};
      this.painted = {};
      this.contentScale = elements.find((e) => e.layout_scale)?.layout_scale ?? 1;
      // 导入的位置数据可能来自别的页面比例：丢掉旧页面盒，按当前内容重新推导
      this.pageBox = null;
      this.layoutStats = null;
      this.layoutWarnings = [];
      this.clearSelection();
      this.bump();
      this.pageTick += 1;
      this.toast("ok", `已导入 ${elements.length} 个元素、${connections.length} 条连线`);
      this.fitTick += 1;
      this.batchCheck();
      return true;
    },
    exportDiagram() {
      return {
        elements: this.elements.map((e) => ({
          id: e.id,
          shape: e.shape,
          label: e.label,
          attributes: [...e.attributes],
          is_weak: e.is_weak ?? false,
          is_identifying: e.is_identifying ?? false,
          // 导出必须是纯对象：Vue 的响应式 Proxy 在部分宿主 / 测试环境里会被序列化成 {}
          attr_offsets: Object.fromEntries(
            Object.entries(e.attr_offsets ?? {}).map(([k, v]) => [k, { x: v.x, y: v.y }]),
          ),
          attr_style: { ...(e.attr_style ?? {}) },
          size: e.size ? { w: e.size.w, h: e.size.h } : null,
          layout_scale: e.layout_scale ?? 1,
          position: { x: Math.round(e.position.x), y: Math.round(e.position.y) },
        })),
        connections: this.connections.map((c) => ({
          id: c.id,
          from: c.from,
          to: c.to,
          type: c.type,
          label: c.label,
          cardinality: c.cardinality,
          mode: c.mode ?? "smart",
          free_end: c.free_end ? { x: Math.round(c.free_end.x), y: Math.round(c.free_end.y) } : undefined,
        })),
      };
    },
    clearAll() {
      this.pushUndo();
      this.elements = [];
      this.connections = [];
      this.results = {};
      this.painted = {};
      this.clearSelection();
      this.pendingFromId = null;
      this.contentScale = 1;
      this.pageBox = null;
      this.layoutStats = null;
      this.layoutWarnings = [];
      this.layoutMark = -1;
      resetIds();
      this.bump();
      this.pageTick += 1;
    },
  },
});
