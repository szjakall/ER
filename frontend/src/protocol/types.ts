/** 与 INTERFACE.md 字段名 1:1，禁止改成 camelCase */

export type Shape = "rectangle" | "ellipse" | "diamond";
export type ConnType = "line" | "diamond_line";
/**
 * Chen 记法：一条连线上只写一个基数符号。
 * 联系两端各是一条线，两条线合起来才是 M:N / 1:N 这样的"对应关系"；
 * 三元联系（如 供应商—供应—项目/零件）是 M:N:P，所以多一个 P。
 */
export type CardSymbol = "1" | "N" | "M" | "P";
export type Cardinality = CardSymbol | null;

/** 该连线是否是"联系分支"（菱形联系 ↔ 矩形实体）——只有这种线才允许写基数 */
export function isRelationBranch(
  conn: { from: string; to: string },
  shapes: Map<string, Shape>,
): boolean {
  const a = shapes.get(conn.from);
  const b = shapes.get(conn.to);
  return (
    (a === "diamond" && b === "rectangle") ||
    (a === "rectangle" && b === "diamond")
  );
}
export type CheckEvent =
  | "element_added"
  | "element_modified"
  | "connection_added"
  | "connection_modified"
  | "element_deleted";

export interface Position {
  x: number;
  y: number;
}

export interface Element {
  id: string;
  shape: Shape;
  label: string;
  attributes: string[];
  position: Position;
  /** 弱实体（教材里画双线矩形） */
  is_weak?: boolean;
  /** 标识联系（教材里画双线菱形） */
  is_identifying?: boolean;
  /**
   * 用户手动拖动属性椭圆后的偏移（相对所属实体中心），按属性下标存。
   * 只影响画布排版，不参与校验，所以不发给后端。
   */
  attr_offsets?: Record<string, Position>;
  /** 属性椭圆的形状：多值 = 双椭圆，派生 = 虚椭圆。仅排版，不上送。 */
  attr_style?: Record<string, AttrShape>;
  /** 用户拖拽控制点后的自定义尺寸。仅排版，不上送。 */
  size?: { w: number; h: number };
  /**
   * 智能页面布局写入的内容级缩放：图形、字号、描边、连线、基数共用同一个比例。
   * 仅前端排版字段，encode.ts 白名单会剥离，不进入后端协议。
   */
  layout_scale?: number;
}

/** 属性的画法：普通椭圆 / 双椭圆（多值）/ 虚椭圆（派生） */
export type AttrShape = "normal" | "multi" | "derived";

export interface Connection {
  id: string;
  from: string;
  /**
   * 智能连线的目标元素 id。
   * 自由端连线没有目标元素，这里固定为空串（后端协议不使用该条记录）。
   */
  to: string;
  type: ConnType;
  label: string;
  cardinality: Cardinality;
  /**
   * 连线模式：缺省 = "smart"（两端连接，兼容现有数据与后端协议）；
   * "free" = 一端连接参与者、另一端自由的本地草稿连线。
   * 该字段与 free_end 都只在本前端保存，encode.ts 会剥离，不上送后端。
   */
  mode?: "smart" | "free";
  /** 仅 free：自由端的绝对画布坐标 */
  free_end?: Position;
}

/** 自由端连线：前端本地模型，不参与后端校验 */
export function isFreeConnection(
  conn: Pick<Connection, "mode"> | null | undefined,
): boolean {
  return conn?.mode === "free";
}

export interface Issue {
  rule_id: string;
  level: "error" | "warn";
  message: string;
}

export interface CheckResult {
  violations: Issue[];
  suggestions: Issue[];
}

export type Severity = "ok" | "warn" | "error";
export type PaintState = "pending" | Severity;

export interface ElementChanges {
  attributes_changed: boolean;
  label_changed: boolean;
}

export interface CheckElementMessage {
  action: "check";
  event: "element_added" | "element_modified" | "element_deleted";
  element: Element;
  changes?: ElementChanges;
}

export interface CheckConnectionMessage {
  action: "check";
  event: "connection_added" | "connection_modified";
  connection: Connection;
}

export type CheckMessage = CheckElementMessage | CheckConnectionMessage;

export interface BatchCheckMessage {
  action: "batch_check";
  diagram: {
    elements: Array<Omit<Element, "position"> & { position?: Position }>;
    connections: Connection[];
  };
}

export type OutgoingMessage = CheckMessage | BatchCheckMessage;

export interface ResultMessage {
  action: "result";
  element_id: string;
  violations: Issue[];
  suggestions: Issue[];
}

export interface BatchResultMessage {
  action: "batch_result";
  results: Record<string, CheckResult>;
}

export interface ErrorMessage {
  action: "error";
  element_id?: string | null;
  message: string;
}

export type IncomingMessage = ResultMessage | BatchResultMessage | ErrorMessage;
