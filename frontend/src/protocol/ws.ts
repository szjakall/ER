import type { CheckMessage, IncomingMessage, OutgoingMessage } from "./types";

export type WsStatus = "closed" | "connecting" | "open" | "error";

const DEFAULT_URL = "ws://localhost:8000/ws";
const TIMEOUT_MS = 2000;

type Pending = { timer: ReturnType<typeof setTimeout>; seq: number };

export interface ErCheckClientHandlers {
  onStatus?: (status: WsStatus) => void;
  onResult?: (elementId: string, violations: unknown, suggestions: unknown, seq: number) => void;
  onBatchResult?: (results: Record<string, unknown>, seq: number) => void;
  onError?: (message: string, elementId?: string | null) => void;
  onOpen?: () => void;
}

export class ErCheckClient {
  private ws: WebSocket | null = null;
  private pending = new Map<string, Pending>();
  private seqById = new Map<string, number>();
  private batchSeq = 0;
  private retryMs = 1000;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private url: string;

  constructor(
    private handlers: ErCheckClientHandlers = {},
    url = DEFAULT_URL,
  ) {
    this.url = url;
  }

  connect() {
    this.stopped = false;
    this.open();
  }

  disconnect() {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.ws?.close();
    this.ws = null;
  }

  private open() {
    if (this.stopped) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.handlers.onStatus?.("connecting");
    let sock: WebSocket;
    try {
      sock = new WebSocket(this.url);
    } catch {
      this.handlers.onStatus?.("error");
      this.scheduleRetry();
      return;
    }
    this.ws = sock;
    sock.onopen = () => {
      this.retryMs = 1000;
      this.handlers.onStatus?.("open");
      this.handlers.onOpen?.();
    };
    sock.onmessage = (ev) => this.onMessage(String(ev.data));
    sock.onerror = () => this.handlers.onStatus?.("error");
    sock.onclose = () => {
      if (this.ws !== sock) return;
      this.ws = null;
      this.handlers.onStatus?.("closed");
      this.scheduleRetry();
    };
  }

  private scheduleRetry() {
    if (this.stopped) return;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    const wait = this.retryMs;
    this.retryMs = Math.min(this.retryMs * 2, 16000);
    this.retryTimer = setTimeout(() => this.open(), wait);
  }

  /** 发完立刻返回；未连接则丢弃。不阻塞画布。 */
  sendCheck(payload: CheckMessage): number {
    const id =
      payload.event === "connection_added" || payload.event === "connection_modified"
        ? payload.connection.id
        : payload.element.id;
    if (!id) return 0;
    const seq = (this.seqById.get(id) ?? 0) + 1;
    this.seqById.set(id, seq);
    const old = this.pending.get(id);
    if (old) clearTimeout(old.timer);
    this.trySend(payload);
    const timer = setTimeout(() => {
      const cur = this.pending.get(id);
      if (cur && cur.seq === seq) this.pending.delete(id);
    }, TIMEOUT_MS);
    this.pending.set(id, { timer, seq });
    return seq;
  }

  sendBatch(payload: OutgoingMessage): number {
    this.batchSeq += 1;
    const seq = this.batchSeq;
    const old = this.pending.get("*batch*");
    if (old) clearTimeout(old.timer);
    this.trySend(payload);
    const timer = setTimeout(() => {
      const cur = this.pending.get("*batch*");
      if (cur && cur.seq === seq) this.pending.delete("*batch*");
    }, TIMEOUT_MS);
    this.pending.set("*batch*", { timer, seq });
    return seq;
  }

  private trySend(payload: OutgoingMessage) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(payload));
  }

  private onMessage(raw: string) {
    let msg: IncomingMessage;
    try {
      msg = JSON.parse(raw) as IncomingMessage;
    } catch {
      return;
    }
    if (msg.action === "result") {
      const id = msg.element_id;
      const slot = this.pending.get(id);
      if (slot) {
        clearTimeout(slot.timer);
        this.pending.delete(id);
        this.handlers.onResult?.(id, msg.violations, msg.suggestions, slot.seq);
      }
      return;
    }
    if (msg.action === "batch_result") {
      const slot = this.pending.get("*batch*");
      if (slot) {
        clearTimeout(slot.timer);
        this.pending.delete("*batch*");
        this.handlers.onBatchResult?.(msg.results ?? {}, slot.seq);
      }
      return;
    }
    if (msg.action === "error") {
      this.handlers.onError?.(msg.message || "后端错误", msg.element_id);
    }
  }
}
