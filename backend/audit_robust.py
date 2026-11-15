# -*- coding: utf-8 -*-
"""
健壮性测试：畸形输入 / 边界值 / 压力
====================================

教学现场最怕"学生随便点一下服务就挂"。本脚本专测边界：
    1) 字段缺失、类型错误、None、空值
    2) 畸形消息（非 JSON、非对象、未知 action/event）
    3) 超大图（性能与正确性）
    4) 自环、悬空、重复 id 等病态拓扑
    5) 中文/emoji/超长字符串
    6) 服务不崩溃：任何输入都必须返回一条合法响应

运行：python audit_robust.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import json
import sys
import time
from typing import Any, Dict, List

from engine import ENGINE, Session, check_batch, check_single

_passed = 0
_failed = 0
_problems: List[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        _problems.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def safe_handle(msg: Any, tag: str) -> Dict:
    """任何输入都必须得到合法 dict 响应，不允许抛异常。"""
    global _passed, _failed
    try:
        resp = ENGINE.handle(f"rob-{tag}", msg)
    except Exception as ex:
        _failed += 1
        _problems.append(f"{tag} 抛异常: {ex!r}")
        print(f"  [FAIL] {tag} 抛异常: {ex!r}")
        return {}
    ok(f"{tag} 返回 dict", isinstance(resp, dict))
    ok(f"{tag} 含 action", "action" in resp)
    return resp


def main() -> int:
    print("=" * 68)
    print("  健壮性测试：畸形输入 / 边界值 / 压力")
    print("=" * 68)

    # ---------------- 1. 畸形顶层消息 ----------------
    print("\n[1] 畸形顶层消息")
    for msg, tag in [
        ({"action": "check"}, "无 event"),
        ({"event": "element_added"}, "无 action"),
        ({"action": "check", "event": "element_added"}, "无 element"),
        ({"action": "check", "event": "element_added", "element": None}, "element=null"),
        ({"action": "check", "event": "element_added", "element": {}}, "element={}"),
        ({"action": "check", "event": "element_added", "element": {"id": None}}, "id=null"),
        ({"action": "batch_check"}, "batch 无 diagram"),
        ({"action": "batch_check", "diagram": None}, "diagram=null"),
        ({"action": "batch_check", "diagram": {}}, "diagram={}"),
        ({"action": "batch_check", "diagram": {"elements": None}}, "elements=null"),
        ({"action": "batch_check", "diagram": {"elements": [], "connections": None}},
         "connections=null"),
        ({"action": ""}, "空 action"),
        ({"action": None}, "action=null"),
        ({"action": 123}, "action=数字"),
        ({}, "空对象"),
    ]:
        r = safe_handle(msg, tag)
        ok(f"{tag} → result 或 error",
           r.get("action") in ("result", "batch_result", "error"),
           f"实际 {r.get('action')}")

    # ---------------- 2. 字段类型错误 ----------------
    print("\n[2] 字段类型错误")
    for el, tag in [
        ({"id": "x", "shape": "rectangle", "label": "A", "attributes": "不是数组"}, "attributes=字符串"),
        ({"id": "x", "shape": "rectangle", "label": "A", "attributes": {"a": 1}}, "attributes=对象"),
        ({"id": "x", "shape": "rectangle", "label": "A", "attributes": [1, 2, None]}, "attributes=混合类型"),
        ({"id": "x", "shape": "rectangle", "label": None, "attributes": []}, "label=null"),
        ({"id": "x", "shape": None, "label": "A", "attributes": []}, "shape=null"),
        ({"id": "x", "shape": "五边形", "label": "A", "attributes": []}, "未知 shape"),
        ({"id": "x", "shape": "rectangle", "label": "A", "attributes": [], "is_weak": "yes"}, "is_weak=字符串"),
        ({"id": "x", "shape": "rectangle", "label": "A", "attributes": [], "position": "bad"}, "position=字符串"),
        ({"id": 123, "shape": "rectangle", "label": "A", "attributes": []}, "id=数字"),
    ]:
        r = safe_handle({"action": "check", "event": "element_added", "element": el}, tag)
        ok(f"{tag} 不崩", r.get("action") in ("result", "error"))

    # connection 类型错误
    for c, tag in [
        ({"id": "c", "from": "a", "to": "b", "type": "奇怪的", "cardinality": "!!"}, "type 异常+基数异常"),
        ({"id": "c", "from": None, "to": None}, "from/to=null"),
        ({"id": "c", "from": "", "to": "", "type": "line"}, "from/to=空串"),
        ({"id": "c", "from": "x", "to": "y", "cardinality": 123}, "cardinality=数字"),
        ({"id": "c", "from": ["x"], "to": "y"}, "from=数组"),
        ({}, "空连线对象"),
    ]:
        r = safe_handle({"action": "check", "event": "connection_added",
                         "connection": c}, tag)
        ok(f"{tag} 不崩", r.get("action") in ("result", "error"))

    # ---------------- 3. 病态拓扑 ----------------
    print("\n[3] 病态拓扑")
    s = Session()
    r = check_single(s, {"action": "check", "event": "element_added",
                         "element": {"id": "a", "shape": "rectangle",
                                     "label": "A", "attributes": ["*a"]}})
    # 自环
    r = check_single(s, {"action": "check", "event": "connection_added",
                         "connection": {"id": "c1", "from": "a", "to": "a",
                                        "type": "line", "cardinality": None}})
    ok("自环连线被识别", any(v["rule_id"] == "R11" for v in r["violations"]))

    # 悬空
    r = check_single(s, {"action": "check", "event": "connection_added",
                         "connection": {"id": "c2", "from": "a", "to": "幽灵",
                                        "type": "line", "cardinality": None}})
    ok("悬空连线被识别", any(v["rule_id"] == "R10" for v in r["violations"]))

    # 重复元素 id（upsert 应覆盖而非重复）
    before = len(s.elements)
    check_single(s, {"action": "check", "event": "element_added",
                     "element": {"id": "a", "shape": "rectangle",
                                 "label": "A改名", "attributes": ["*a"]}})
    ok("重复 id 不产生重复元素", len(s.elements) == before,
       f"{before} -> {len(s.elements)}")

    # ---------------- 4. 特殊字符串 ----------------
    print("\n[4] 特殊字符串")
    for label, tag in [
        ("🎉📚", "emoji"),
        ("A" * 500, "超长(500)"),
        ("   ", "纯空格"),
        ("\n\t", "换行制表"),
        ("'; DROP TABLE--", "SQL 注入样式"),
        ("<script>alert(1)</script>", "XSS 样式"),
        ("*" * 20 + "名", "全星号前缀"),
        ("中文English混排123", "混排"),
    ]:
        r = safe_handle({"action": "check", "event": "element_added",
                         "element": {"id": "s1", "shape": "rectangle",
                                     "label": label, "attributes": ["*学号"]}}, tag)
        ok(f"{tag} 不崩", r.get("action") in ("result", "error"))

    # ---------------- 5. 压力：大图 ----------------
    print("\n[5] 压力测试")
    for n in [50, 200, 500]:
        els = []
        cons = []
        for i in range(n):
            els.append({"id": f"e{i}", "shape": "rectangle",
                        "label": f"实体{i}", "attributes": ["*id", "名称", "备注"]})
        for i in range(n - 1):
            cons.append({"id": f"c{i}", "from": f"e{i}", "to": f"e{i+1}",
                         "type": "line", "cardinality": None})
        t0 = time.perf_counter()
        try:
            resp = check_batch(Session(), {"action": "batch_check",
                                           "diagram": {"elements": els,
                                                       "connections": cons}})
            dt = (time.perf_counter() - t0) * 1000
            ok(f"{n} 实体图 不崩", resp.get("action") == "batch_result")
            ok(f"{n} 实体图 覆盖全部", len(resp["results"]) == len(els) + len(cons))
            print(f"        {n} 实体 + {len(cons)} 连线 → {dt:.1f}ms")
        except Exception as ex:
            ok(f"{n} 实体图 不崩", False, repr(ex))

    # 空图
    r = check_batch(Session(), {"action": "batch_check",
                                "diagram": {"elements": [], "connections": []}})
    ok("空图 → batch_result", r.get("action") == "batch_result")
    ok("空图 results 为空", r["results"] == {})

    # ---------------- 6. 会话隔离 / 状态污染 ----------------
    print("\n[6] 会话隔离")
    ENGINE.handle("sess-A", {"action": "check", "event": "element_added",
                             "element": {"id": "A1", "shape": "rectangle",
                                         "label": "甲", "attributes": ["*a"]}})
    ENGINE.handle("sess-B", {"action": "check", "event": "element_added",
                             "element": {"id": "B1", "shape": "rectangle",
                                         "label": "乙", "attributes": ["*b"]}})
    sa, sb = ENGINE.session("sess-A"), ENGINE.session("sess-B")
    ok("A 会话不含 B 的元素", "B1" not in sa.elements)
    ok("B 会话不含 A 的元素", "A1" not in sb.elements)
    ENGINE.drop_session("sess-A")
    ENGINE.drop_session("sess-B")
    ok("会话可正常清除", "sess-A" not in ENGINE.sessions)

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题清单：")
        for p in _problems[:20]:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
