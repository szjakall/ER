# -*- coding: utf-8 -*-
"""
画布图模型 —— Chen 记法语义层
==============================

把 INTERFACE.md 的消息（elements + connections）解析成可判定的图模型。

核心语义（Chen 记法）：
    - rectangle  = 实体
    - ellipse    = 属性
    - diamond    = 联系
    - 联系不是"一条记录"，而是「菱形元素 + 若干条分支线」
      例： 实体A —1— ◇借阅 —N— 实体B
      数据上 = 1 个 diamond 元素 + 2 条 diamond_line 连线
      所以"基数是否齐全""联系连了几个实体"必须看菱形周围的连线集合。

属性前缀约定（来自前端 encode.ts 与 mock）：
    * 前缀 = 主键（primary key）
    # 前缀 = 弱实体的部分键（鉴别器）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

# ----------------------------------------------------------------------
# 形状常量
# ----------------------------------------------------------------------
SHAPE_RECT = "rectangle"
SHAPE_ELLIPSE = "ellipse"
SHAPE_DIAMOND = "diamond"

CONN_LINE = "line"
CONN_DIAMOND_LINE = "diamond_line"

# Chen 记法允许的基数符号：1 / N / M / P（P 用于三元联系的第三端）
VALID_CARDINALITIES = {"1", "N", "M", "P"}

PK_PREFIX = "*"
PARTIAL_PREFIX = "#"


# ----------------------------------------------------------------------
# 属性工具
# ----------------------------------------------------------------------
def strip_prefix(raw: str) -> str:
    """去掉主键/部分键前缀，得到裸属性名。"""
    s = str(raw).strip()
    while s.startswith(PK_PREFIX) or s.startswith(PARTIAL_PREFIX):
        s = s[1:].strip()
    return s


def has_pk_prefix(raw: str) -> bool:
    return str(raw).strip().startswith(PK_PREFIX)


def has_partial_prefix(raw: str) -> bool:
    return str(raw).strip().startswith(PARTIAL_PREFIX)


class Element:
    """画布元素（实体 / 属性 / 联系）。"""

    __slots__ = ("id", "shape", "label", "attributes", "is_weak", "position")

    def __init__(self, raw: dict) -> None:
        self.id: str = str(raw.get("id") or "")
        self.shape: str = str(raw.get("shape") or "")
        self.label: str = str(raw.get("label") or "")
        attrs = raw.get("attributes")
        if not isinstance(attrs, list):
            attrs = []
        self.attributes: List[str] = [str(a) for a in attrs]
        self.is_weak: bool = bool(raw.get("is_weak", False))
        pos = raw.get("position")
        self.position: Optional[dict] = pos if isinstance(pos, dict) else None

    # -- 便捷判定 ------------------------------------------------------
    @property
    def is_entity(self) -> bool:
        return self.shape == SHAPE_RECT

    @property
    def is_attribute(self) -> bool:
        return self.shape == SHAPE_ELLIPSE

    @property
    def is_relationship(self) -> bool:
        return self.shape == SHAPE_DIAMOND

    @property
    def name(self) -> str:
        return self.label.strip()

    def bare_attributes(self) -> List[str]:
        return [strip_prefix(a) for a in self.attributes]

    def primary_keys(self) -> List[str]:
        return [a for a in self.attributes if has_pk_prefix(a)]

    def partial_keys(self) -> List[str]:
        return [a for a in self.attributes if has_partial_prefix(a)]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Element {self.id} {self.shape} {self.label!r}>"


class Connection:
    """画布连线。"""

    __slots__ = ("id", "from_id", "to_id", "type", "label", "cardinality")

    def __init__(self, raw: dict) -> None:
        self.id: str = str(raw.get("id") or "")
        self.from_id: str = str(raw.get("from") or "")
        self.to_id: str = str(raw.get("to") or "")
        self.type: str = CONN_DIAMOND_LINE if raw.get("type") == CONN_DIAMOND_LINE else CONN_LINE
        self.label: str = str(raw.get("label") or "")
        card = raw.get("cardinality")
        self.cardinality: Optional[str] = None if card is None else str(card).strip()

    @property
    def is_relation_branch(self) -> bool:
        """是否为"联系分支线"（diamond_line）。"""
        return self.type == CONN_DIAMOND_LINE

    def touches(self, element_id: str) -> bool:
        return self.from_id == element_id or self.to_id == element_id

    def other_end(self, element_id: str) -> str:
        return self.to_id if self.from_id == element_id else self.from_id

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Connection {self.id} {self.from_id}->{self.to_id} {self.type}>"


class Diagram:
    """
    一张 ER 图的完整图模型。

    由 elements + connections 构建，并提供规则判定所需的全部图查询能力。
    """

    def __init__(self, elements: List[dict], connections: List[dict],
                 requirement_text: str = "") -> None:
        self.elements: Dict[str, Element] = {}
        for raw in elements or []:
            if not isinstance(raw, dict):
                continue
            el = Element(raw)
            if el.id:
                self.elements[el.id] = el

        self.connections: Dict[str, Connection] = {}
        for raw in connections or []:
            if not isinstance(raw, dict):
                continue
            c = Connection(raw)
            if c.id:
                self.connections[c.id] = c

        self.requirement_text: str = requirement_text or ""
        # 邻接索引缓存（惰性构建，见 _adjacency）
        self._adj: Optional[Dict[str, List[Connection]]] = None

        # 预计算派生集合，避免规则反复遍历（O(n) 一次算好）
        self._conn_types_seen: Optional[bool] = None

    # ------------------------------------------------------------------
    # 元素查询
    # ------------------------------------------------------------------
    def get(self, element_id: str) -> Optional[Element]:
        return self.elements.get(element_id)

    def by_shape(self, shape: str) -> List[Element]:
        return [e for e in self.elements.values() if e.shape == shape]

    @property
    def entities(self) -> List[Element]:
        return self.by_shape(SHAPE_RECT)

    @property
    def attributes_nodes(self) -> List[Element]:
        return self.by_shape(SHAPE_ELLIPSE)

    @property
    def relationships(self) -> List[Element]:
        return self.by_shape(SHAPE_DIAMOND)

    # ------------------------------------------------------------------
    # 连线查询
    # ------------------------------------------------------------------
    def _adjacency(self) -> Dict[str, List[Connection]]:
        """
        邻接索引：element_id -> 与之相连的连线列表。

        惰性构建并缓存。若不用索引，`connections_of` 每次都要扫全部连线，
        而 H12 这类规则会对每个实体调一次，整体退化成 O(实体数 × 连线数)；
        实测 800 实体时单条规则就要 116ms，是唯一超标来源。
        """
        if self._adj is None:
            adj: Dict[str, List[Connection]] = {}
            for c in self.connections.values():
                adj.setdefault(c.from_id, []).append(c)
                if c.to_id != c.from_id:
                    adj.setdefault(c.to_id, []).append(c)
            self._adj = adj
        return self._adj

    def connections_of(self, element_id: str) -> List[Connection]:
        return list(self._adjacency().get(element_id, []))

    def branches_of(self, diamond_id: str) -> List[Connection]:
        """某个菱形联系的所有分支线（diamond_line）。"""
        return [
            c for c in self.connections.values()
            if c.is_relation_branch and c.touches(diamond_id)
        ]

    def neighbor_shapes(self, element_id: str) -> List[str]:
        out = []
        for c in self.connections_of(element_id):
            other = self.get(c.other_end(element_id))
            if other is not None:
                out.append(other.shape)
        return out

    def entity_neighbors_of(self, element_id: str) -> List[Element]:
        """与某元素**直接相连**的实体。"""
        out = []
        for c in self.connections_of(element_id):
            other = self.get(c.other_end(element_id))
            if other is not None and other.is_entity:
                out.append(other)
        return out

    def entities_via_relationships(self, element_id: str,
                                   max_depth: int = 8) -> List[Element]:
        """
        经"联系（菱形）"间接可达的实体（**支持多级**）。

        Chen 记法中，弱实体通常这样连到强实体：
            弱实体 ──◇联系◇── 强实体
        即弱实体直接连的是菱形，而非另一个矩形。故判断"弱实体是否依赖强实体"时，
        必须跨过菱形去找对端的实体，否则会把标准弱实体图误判为错误。

        **多级弱实体**：弱实体也可以依赖另一个弱实体——
            职工 ──具有── 亲属(弱) ──拥有── 子女(弱)
        子女的强实体是职工（经亲属传递）。此前只跨一层菱形，
        会把"子女"误报为"未依赖任何强实体"。

        做法：广度优先，遇菱形则继续向外展开，遇实体则收集。
        max_depth 防环（也防病态深链导致的开销失控）。
        """
        out: List[Element] = []
        seen: Set[str] = {element_id}
        # 待展开队列（菱形与实体都要继续展开）
        #
        # 关键：实体**不能**因为"已收集"就停止展开。
        # 弱实体可以是依赖链上的中转站：
        #     职工 ──具有── 亲属(弱) ──拥有── 子女(弱)
        # 从"子女"出发会先遇到"亲属"，若就此停下，
        # 就找不到"职工"，会把合法的多级弱实体误报为"未依赖强实体"。
        frontier: List[str] = []
        for c in self.connections_of(element_id):
            other = self.get(c.other_end(element_id))
            if other is None or other.id in seen:
                continue
            seen.add(other.id)
            if other.is_entity:
                out.append(other)
            frontier.append(other.id)

        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            nxt: List[str] = []
            for nid in frontier:
                for c in self.connections_of(nid):
                    far = self.get(c.other_end(nid))
                    if far is None or far.id in seen:
                        continue
                    seen.add(far.id)
                    if far.is_entity:
                        out.append(far)
                    nxt.append(far.id)
            frontier = nxt
        return out

    def is_isolated(self, element_id: str) -> bool:
        return len(self.connections_of(element_id)) == 0

    # ------------------------------------------------------------------
    # 用于"删除后"判定的辅助
    # ------------------------------------------------------------------
    def dangling_connections(self) -> List[Connection]:
        """端点指向不存在元素的连线。"""
        out = []
        for c in self.connections.values():
            if c.from_id not in self.elements or c.to_id not in self.elements:
                out.append(c)
        return out

    def duplicate_element_names(self, shape: str) -> Dict[str, List[str]]:
        """同形状元素中重名的分组（名称 -> id 列表）。"""
        seen: Dict[str, List[str]] = {}
        for e in self.by_shape(shape):
            if e.name:
                seen.setdefault(e.name, []).append(e.id)
        return {k: v for k, v in seen.items() if len(v) > 1}

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<Diagram {len(self.elements)} elements, "
                f"{len(self.connections)} connections>")
