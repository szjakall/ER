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
  Cardinality,
  CardSymbol,
  CheckResult,
  Connection,
  ConnType,
  Element,
  Issue,
  PaintState,
  Shape,
} from "../protocol/types";
import { ErCheckClient, type WsStatus } from "../protocol/ws";
import { detectOverlaps } from "../canvas/overlap";

export type Tool = "select" | "entity" | "attribute" | "relationship" | "connect";

export interface Notice {
  id: number;
  level: "error" | "info" | "ok" | "warn";
  text: string;
}

export interface ModelSnapshot {
  elements: Element[];
  connections: Connection[];
}

function emptyResult(): CheckResult {
  return { violations: [], suggestions: [] };
}

function cloneModel(elements: Element[], connections: Connection[]): ModelSnapshot {
  return {
    elements: elements.map((e) => ({
      ...e,
      attributes: [...e.attributes],
      position: { ...e.position },
    })),
    connections: connections.map((c) => ({ ...c })),
  };
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
    pendingFromId: null as string | null,
    wsStatus: "closed" as WsStatus,
    notices: [] as Notice[],
    undoStack: [] as ModelSnapshot[],
    redoStack: [] as ModelSnapshot[],
    canvasTick: 0,
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
      for (const c of state.connections) push(c.id, "connection");
      return rows;
    },
    paintStats(state) {
      const s = { error: 0, warn: 0, ok: 0, pending: 0 };
      const overlaps = detectOverlaps(state.elements, state.connections);
      const count = (id: string) => {
        if (overlaps.get(id)?.length) {
          s.error += 1;
          return;
        }
        s[severityOf(state.results[id], !!state.painted[id])] += 1;
      };
      state.elements.forEach((e) => count(e.id));
      state.connections.forEach((c) => count(c.id));
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
    pushUndo() {
      this.undoStack.push(cloneModel(this.elements, this.connections));
      if (this.undoStack.length > 80) this.undoStack.shift();
      this.redoStack = [];
    },
    restore(snap: ModelSnapshot) {
      this.elements = cloneModel(snap.elements, snap.connections).elements;
      this.connections = cloneModel(snap.elements, snap.connections).connections;
      this.results = {};
      this.painted = {};
      this.pendingFromId = null;
      this.bump();
      this.batchCheck();
    },
    undo() {
      const prev = this.undoStack.pop();
      if (!prev) return;
      this.redoStack.push(cloneModel(this.elements, this.connections));
      this.restore(prev);
    },
    redo() {
      const next = this.redoStack.pop();
      if (!next) return;
      this.undoStack.push(cloneModel(this.elements, this.connections));
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
      if (this.tool !== "connect") this.pendingFromId = null;
    },
    select(kind: "element" | "connection" | null, id: string | null) {
      this.selectedKind = kind;
      this.selectedId = id;
    },
    clearSelection() {
      this.selectedKind = null;
      this.selectedId = null;
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
      if (event === "element_added") c.sendCheck(encodeElementAdded(element));
      else if (event === "element_deleted") c.sendCheck(encodeElementDeleted(element));
      else c.sendCheck(encodeElementModified(element, changes ?? { attributes_changed: false, label_changed: false }));
    },
    sendConnectionCheck(event: "connection_added" | "connection_modified", connection: Connection) {
      this.markPending(connection.id);
      const c = this.ensureClient();
      if (event === "connection_added") c.sendCheck(encodeConnectionAdded(connection));
      else c.sendCheck(encodeConnectionModified(connection));
    },
    batchCheck() {
      for (const e of this.elements) this.painted[e.id] = false;
      for (const c of this.connections) this.painted[c.id] = false;
      this.bump();
      this.ensureClient().sendBatch(encodeBatchCheck(this.elements, this.connections));
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
      patch: { label?: string; attributes?: string[]; is_weak?: boolean },
    ) {
      const el = this.findElement(id);
      if (!el) return;
      const changes = { label_changed: false, attributes_changed: false };
      if (patch.label !== undefined && patch.label !== el.label) changes.label_changed = true;
      if (patch.attributes !== undefined && JSON.stringify(patch.attributes) !== JSON.stringify(el.attributes)) {
        changes.attributes_changed = true;
      }
      const weakChanged = patch.is_weak !== undefined && (patch.is_weak ?? false) !== (el.is_weak ?? false);
      if (!changes.label_changed && !changes.attributes_changed && !weakChanged) return;
      this.pushUndo();
      if (changes.label_changed) el.label = patch.label ?? el.label;
      if (changes.attributes_changed) el.attributes = [...(patch.attributes ?? [])];
      if (weakChanged) el.is_weak = patch.is_weak;
      this.bump();
      this.sendElementCheck("element_modified", el, changes);
    },
    updatePosition(id: string, x: number, y: number) {
      const el = this.findElement(id);
      if (!el) return;
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
    updateConnection(
      id: string,
      patch: { type?: ConnType; label?: string; cardinality?: Cardinality },
    ) {
      const c = this.findConnection(id);
      if (!c) return;
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
        return {
          id,
          shape,
          label: String(e.label ?? ""),
          attributes: Array.isArray(e.attributes) ? e.attributes.map((a) => String(a)) : [],
          is_weak: e.is_weak === true,
          attr_offsets: (e.attr_offsets as Record<string, { x: number; y: number }> | undefined) ?? {},
          position: {
            x: typeof pos.x === "number" ? pos.x : 140 + (index % 4) * 280,
            y: typeof pos.y === "number" ? pos.y : 140 + Math.floor(index / 4) * 200,
          },
        };
      });
      const connections: Connection[] = (Array.isArray(raw.connections) ? raw.connections : []).map(
        (item, index) => {
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
          return {
            id,
            from: String(c.from ?? ""),
            to: String(c.to ?? ""),
            type: c.type === "diamond_line" ? "diamond_line" : "line",
            label: String(c.label ?? ""),
            cardinality,
          };
        },
      );
      this.elements = elements;
      this.connections = connections;
      this.results = {};
      this.painted = {};
      this.clearSelection();
      this.bump();
      this.toast("ok", `已导入 ${elements.length} 个元素、${connections.length} 条连线`);
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
          attr_offsets: e.attr_offsets ?? {},
          position: { x: Math.round(e.position.x), y: Math.round(e.position.y) },
        })),
        connections: this.connections.map((c) => ({
          id: c.id,
          from: c.from,
          to: c.to,
          type: c.type,
          label: c.label,
          cardinality: c.cardinality,
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
      resetIds();
      this.bump();
    },
  },
});
