import type {
  BatchCheckMessage,
  CheckConnectionMessage,
  CheckElementMessage,
  Connection,
  Element,
  ElementChanges,
} from "./types";

export function encodeElementAdded(element: Element): CheckElementMessage {
  return { action: "check", event: "element_added", element: cloneElement(element) };
}

export function encodeElementModified(
  element: Element,
  changes: ElementChanges,
): CheckElementMessage {
  return {
    action: "check",
    event: "element_modified",
    element: cloneElement(element),
    changes: {
      attributes_changed: !!changes.attributes_changed,
      label_changed: !!changes.label_changed,
    },
  };
}

export function encodeElementDeleted(element: Element): CheckElementMessage {
  return { action: "check", event: "element_deleted", element: cloneElement(element) };
}

export function encodeConnectionAdded(connection: Connection): CheckConnectionMessage {
  return {
    action: "check",
    event: "connection_added",
    connection: cloneConnection(connection),
  };
}

export function encodeConnectionModified(connection: Connection): CheckConnectionMessage {
  return {
    action: "check",
    event: "connection_modified",
    connection: cloneConnection(connection),
  };
}

export function encodeBatchCheck(
  elements: Element[],
  connections: Connection[],
): BatchCheckMessage {
  return {
    action: "batch_check",
    diagram: {
      elements: elements.map((e) => ({
        id: e.id,
        shape: e.shape,
        label: e.label ?? "",
        attributes: Array.isArray(e.attributes) ? [...e.attributes] : [],
        is_weak: e.is_weak ?? false,
      })),
      connections: connections.map(cloneConnection),
    },
  };
}

function cloneElement(e: Element): Element {
  return {
    id: e.id,
    shape: e.shape,
    label: e.label ?? "",
    attributes: Array.isArray(e.attributes) ? [...e.attributes] : [],
    is_weak: e.is_weak ?? false,
    position: {
      x: Math.round(e.position?.x ?? 0),
      y: Math.round(e.position?.y ?? 0),
    },
  };
}

function cloneConnection(c: Connection): Connection {
  return {
    id: c.id,
    from: c.from,
    to: c.to,
    type: c.type === "diamond_line" ? "diamond_line" : "line",
    label: c.label ?? "",
    cardinality: c.cardinality ?? null,
  };
}
