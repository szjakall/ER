/**
 * 本地校验回显：字段名与 INTERFACE.md 一致。
 * 启动：npm run mock  →  ws://localhost:8000/ws
 *
 * 陈氏（Chen）记法：
 * - 基数是一个单字符 1 / N / M，写在"联系分支线"（菱形联系 ↔ 矩形实体）上；
 * - 联系名写在菱形元素里；
 * - 实体 ↔ 属性、联系 ↔ 自身属性的连线不写基数，也不校验基数/名称。
 */
import { WebSocketServer } from "ws";

const PORT = 8000;

function issue(rule_id, level, message) {
  return { rule_id, level, message };
}

// id -> element，用于判断连线类型与联系名
const elements = new Map();

function shapeOf(id) {
  return elements.get(id)?.shape;
}

function isRelationBranch(c) {
  const a = shapeOf(c?.from);
  const b = shapeOf(c?.to);
  return (
    (a === "diamond" && b === "rectangle") ||
    (a === "rectangle" && b === "diamond")
  );
}

function remember(el) {
  if (el?.id) elements.set(el.id, el);
}

function forget(id) {
  if (id) elements.delete(id);
}

function checkElement(el) {
  const violations = [];
  const suggestions = [];
  const label = String(el?.label ?? "").trim();
  const attrs = Array.isArray(el?.attributes) ? el.attributes.map((a) => String(a)) : [];
  const shape = el?.shape;

  if (shape === "rectangle") {
    if (!label) violations.push(issue("R10", "error", "实体名称不能为空"));
    // 局部 ER 图：没有属性时不判缺主键；加了属性才要求有主键
    if (label && attrs.length > 0) {
      const hasPk = attrs.some((a) => a.trim().startsWith("*"));
      if (!hasPk) {
        violations.push(
          issue("R01", "error", `实体'${label}'缺少主键标注 —— 请在属性名前加 * 号`),
        );
      }
    }
    // 弱实体必须有部分键（# 前缀）
    if (el?.is_weak) {
      const hasPartial = attrs.some((a) => a.trim().startsWith("#"));
      if (!hasPartial) {
        violations.push(
          issue("R11", "error", `弱实体'${label}'缺少部分键（请在属性名前加 # 号）`),
        );
      }
    }
    for (const raw of attrs) {
      const name = raw.trim().replace(/^\*+/, "").replace(/^#+/, "").trim();
      if (name === "电话") {
        suggestions.push(
          issue("H03", "warn", `属性'${name}'可能为多值属性，建议拆分为独立实体或关联表`),
        );
      }
    }
  } else if (shape === "ellipse") {
    if (!label) violations.push(issue("R12", "error", "属性必须填写名称"));
  } else if (shape === "diamond") {
    if (!label) violations.push(issue("R13", "error", "联系必须标注名称（如借阅、属于）"));
  }
  return { violations, suggestions };
}

function checkConnection(c) {
  const violations = [];
  const suggestions = [];
  // 属性连线 / 普通连线：不校验名称与基数
  if (!isRelationBranch(c)) return { violations, suggestions };
  // 联系名写在菱形元素上
  const diamondId = shapeOf(c.from) === "diamond" ? c.from : c.to;
  const diamondLabel = String(elements.get(diamondId)?.label ?? "").trim();
  if (!diamondLabel) {
    violations.push(issue("R06", "error", "联系必须标注名称（如'借阅'、'属于'）"));
  }
  if (!c?.cardinality) {
    violations.push(issue("R05", "error", "联系连线缺少基数符号（请在线上写 1 / N / M / P）"));
  }
  return { violations, suggestions };
}

function reply(ws, obj) {
  setTimeout(() => {
    if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(obj));
  }, 80);
}

function handle(ws, raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch (err) {
    reply(ws, { action: "error", element_id: null, message: `消息格式错误: JSON 解析失败` });
    return;
  }
  if (msg.action === "batch_check") {
    const diagram = msg.diagram || {};
    for (const el of diagram.elements || []) remember(el);
    const results = {};
    for (const el of diagram.elements || []) results[el.id] = checkElement(el);
    for (const c of diagram.connections || []) results[c.id] = checkConnection(c);
    reply(ws, { action: "batch_result", results });
    return;
  }
  if (msg.action !== "check") {
    reply(ws, { action: "error", element_id: null, message: `不支持的消息：action=${msg.action}` });
    return;
  }
  const el = msg.element;
  const conn = msg.connection;
  if (el && el.attributes !== undefined && !Array.isArray(el.attributes)) {
    reply(ws, {
      action: "error",
      element_id: el.id,
      message: `消息格式错误: 'attributes' 字段应为数组，收到了 ${typeof el.attributes}`,
    });
    return;
  }
  if (msg.event === "element_added" || msg.event === "element_modified") {
    remember(el);
    reply(ws, { action: "result", element_id: el?.id, ...checkElement(el) });
  } else if (msg.event === "element_deleted") {
    forget(el?.id);
    reply(ws, { action: "result", element_id: el?.id, violations: [], suggestions: [] });
  } else if (msg.event === "connection_added" || msg.event === "connection_modified") {
    reply(ws, { action: "result", element_id: conn?.id, ...checkConnection(conn) });
  } else {
    reply(ws, { action: "error", element_id: el?.id || conn?.id, message: `不支持的事件：${msg.event}` });
  }
}

const wss = new WebSocketServer({ port: PORT, path: "/ws" });
wss.on("connection", (ws) => {
  ws.on("message", (raw) => handle(ws, raw.toString()));
});
console.log(`mock ws://localhost:${PORT}/ws`);
