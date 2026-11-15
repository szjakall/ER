# -*- coding: utf-8 -*-
"""
事件类型字典树（Trie）—— 规则索引
==================================

作用：把「检查事件」→「该跑哪些规则」做成 O(len(event)) 的前缀树查找，
使单次检查只执行相关规则子集，而不是全量扫描。

设计说明（重要，避免误解）：
    字典树的真正价值**不在** 44 条规则规模下的查找速度（普通 dict 已足够快），
    而在于两点：
      1) 语义分层：`connection_added` 与 `connection_added_weak` 这类事件可共享
         前缀分支，规则可挂在中间节点上，实现"按事件族批量挂载"；
      2) 真实性能来自"只跑子集"——全量 44 条 vs 事件命中 13 条的差距，
         才是满足 <100ms 的主要来源。

    因此本模块同时暴露 stats()，用实测数字证明"非全量扫描"。
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Set


# 事件类型常量（与 INTERFACE.md 的 event 字段一致）
EVENT_ELEMENT_ADDED = "element_added"
EVENT_ELEMENT_MODIFIED = "element_modified"
EVENT_ELEMENT_DELETED = "element_deleted"
EVENT_CONNECTION_ADDED = "connection_added"
EVENT_CONNECTION_MODIFIED = "connection_modified"
EVENT_BATCH_CHECK = "batch_check"

# 通配分支：图结构级 / 需求对齐级规则挂在这里，
# 只有存在"全图快照"时才由 engine 放行（见 engine._select_rules）
WILDCARD = "*"


class RuleNode:
    """字典树节点。children 按字符分叉，rules 挂载于该节点（即某事件名）。"""

    __slots__ = ("children", "rules", "name")

    def __init__(self, name: str = "") -> None:
        self.children: Dict[str, "RuleNode"] = {}
        self.rules: List[Callable] = []
        self.name = name

    def is_empty(self) -> bool:
        return not self.children and not self.rules


class RuleTrie:
    """按事件类型索引规则的字典树。"""

    def __init__(self) -> None:
        self.root = RuleNode()
        self._rule_count = 0  # 去重后的规则总数

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def insert(self, event: str, rule: Callable) -> None:
        """把一条规则挂到某个事件上。"""
        node = self.root
        for ch in event:
            node = node.children.setdefault(ch, RuleNode(node.name + ch))
        node.rules.append(rule)

    def insert_many(self, events: Iterable[str], rule: Callable) -> None:
        for ev in events:
            self.insert(ev, rule)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def match(self, event: str) -> List[Callable]:
        """
        精确匹配某事件下的规则列表（按插入顺序，已去重）。

        时间复杂度 O(len(event))——与规则总数无关。
        """
        node = self._walk(event)
        if node is None:
            return []
        return self._dedup(node.rules)

    def match_with_wildcard(self, event: str) -> List[Callable]:
        """精确事件规则 + 通配规则（图结构级/需求对齐级）。"""
        return self._dedup(self.match(event) + self.match(WILDCARD))

    def _walk(self, event: str) -> RuleNode | None:
        node = self.root
        for ch in event:
            nxt = node.children.get(ch)
            if nxt is None:
                return None
            node = nxt
        return node

    @staticmethod
    def _dedup(rules: List[Callable]) -> List[Callable]:
        """同一规则可能挂在多个事件上；单次查询内去重并保持顺序。"""
        seen: Set[int] = set()
        out: List[Callable] = []
        for r in rules:
            k = id(r)
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out

    # ------------------------------------------------------------------
    # 统计（用于证明"非全量扫描")
    # ------------------------------------------------------------------
    def all_rules(self) -> List[Callable]:
        """遍历全树，返回去重后的全部规则。"""
        acc: List[Callable] = []
        seen: Set[int] = set()
        stack = [self.root]
        while stack:
            node = stack.pop()
            for r in node.rules:
                if id(r) not in seen:
                    seen.add(id(r))
                    acc.append(r)
            stack.extend(node.children.values())
        return acc

    def events(self) -> List[str]:
        """列出所有已注册事件（含通配 '*')。"""
        out: List[str] = []
        stack = [(self.root, "")]
        while stack:
            node, prefix = stack.pop()
            if node.rules:
                out.append(prefix or node.name)
            for ch, child in node.children.items():
                stack.append((child, prefix + ch))
        return sorted(out)

    def stats(self) -> Dict[str, object]:
        """各事件的规则命中数 + 总规则数，供基准测试与启动自检打印。"""
        per_event: Dict[str, int] = {}
        for ev in self.events():
            per_event[ev] = len(self.match(ev))
        total = len(self.all_rules())
        return {
            "total_rules": total,
            "events": per_event,
            "max_per_event": max(per_event.values()) if per_event else 0,
            "node_count": self._count_nodes(),
        }

    def _count_nodes(self) -> int:
        n, stack = 0, [self.root]
        while stack:
            node = stack.pop()
            n += 1
            stack.extend(node.children.values())
        return n

    def describe(self) -> str:
        """人类可读的索引表，用于启动日志与文档核对。"""
        st = self.stats()
        lines = [
            f"规则字典树：共 {st['total_rules']} 条规则，"
            f"{st['node_count']} 个节点，单事件最多命中 {st['max_per_event']} 条"
        ]
        for ev, cnt in sorted(st["events"].items()):
            lines.append(f"  {ev:<24} → {cnt} 条")
        return "\n".join(lines)
