# -*- coding: utf-8 -*-
"""
修复逻辑的对抗性验证
====================

背景：上一轮修复了 R02（弱实体不要求独立主键）与 R23（跨菱形找强实体）。
      但**修复本身是新增逻辑，尚未被独立审查**。本脚本专测这些新逻辑：

      A. 修复是否造成"漏报"（本该报的错现在不报了）
      B. 跨菱形遍历在复杂拓扑下是否正确
      C. 邻接索引（性能优化）是否改变了判定结果
      D. 不支持负向误报：合法图不该报，非法图必须报

运行：python audit_regression.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
from typing import Dict, List

from model import Diagram
from rules import RuleContext, rule_R02, rule_R05, rule_R23

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


def E(eid, label, attrs=None, weak=False):
    return {"id": eid, "shape": "rectangle", "label": label,
            "attributes": attrs or [], "is_weak": weak}


def D(did, label):
    return {"id": did, "shape": "diamond", "label": label}


def C(cid, f, t, card="1"):
    return {"id": cid, "from": f, "to": t, "type": "diamond_line",
            "label": "", "cardinality": card}


def ctx(els, cons):
    return RuleContext(Diagram(els, cons))


def main() -> int:
    print("=" * 68)
    print("  修复逻辑对抗性验证（R02 / R23 / 邻接索引）")
    print("=" * 68)

    # ==============================================================
    # A. R02 漏报检查：非弱实体仍必须报缺主键
    # ==============================================================
    print("\n[A] R02 修复是否造成漏报")

    # A1 普通实体无主键 → 必须报
    r = rule_R02(ctx([E("e1", "学生", ["姓名", "性别"])], []))
    ok("A1 普通实体无主键仍报错", len(r) == 1 and r[0]["rule_id"] == "R02")

    # A2 普通实体无主键但有 # 前缀 → 仍应报（# 是弱实体专用，普通实体不能用 # 顶替主键）
    r = rule_R02(ctx([E("e1", "学生", ["#学号", "姓名"])], []))
    ok("A2 普通实体用 # 顶替主键仍报错", len(r) == 1,
       f"实际 {len(r)} 条 —— 若为 0 则属漏报")

    # A3 弱实体有 # → 不报（正确）
    r = rule_R02(ctx([E("e1", "亲属", ["#称呼", "姓名"], weak=True)], []))
    ok("A3 弱实体有部分键不报", len(r) == 0)

    # A4 弱实体既无 * 也无 # → R02 不报，由 R05 报（避免重复刷屏）
    els = [E("e1", "亲属", ["称呼", "姓名"], weak=True)]
    r02 = rule_R02(ctx(els, []))
    r05 = rule_R05(ctx(els, []))
    ok("A4 弱实体无任何键：R02 不报", len(r02) == 0)
    ok("A4 弱实体无任何键：R05 报缺部分键", len(r05) == 1)

    # A5 弱实体同时标 * 与 # → R05 报"不应另立独立主键"（v1.3 起）
    #    此前该情形无人报（R05 见 # 放行、R02 见 * 放行），属漏报。
    #    弱实体标识 = 强实体主键 + 自身部分键，不应自立独立主键。
    els = [E("e1", "亲属", ["*编号", "#称呼"], weak=True)]
    r02 = rule_R02(ctx(els, []))
    r05 = rule_R05(ctx(els, []))
    ok("A5 弱实体同时标主键与部分键：R02 不报（有 # 即合规）", len(r02) == 0)
    ok("A5 弱实体同时标主键与部分键：R05 报概念混淆", len(r05) == 1,
       f"实际 {len(r05)} 条")

    # A6 无属性 → 不报（局部图，学生还没加属性）
    ok("A6 无属性实体不报", len(rule_R02(ctx([E("e1", "学生", [])], []))) == 0)

    # A7 无名实体 → 不报（R01 负责）
    ok("A7 无名实体 R02 不报", len(rule_R02(ctx([E("e1", "", ["姓名"])], []))) == 0)

    # ==============================================================
    # B. R23 跨菱形遍历的正确性
    # ==============================================================
    print("\n[B] R23 跨菱形判定")

    # B1 弱实体—菱形—强实体（教科书标准）→ 不报
    els = [E("w1", "亲属", ["#称呼"], weak=True), E("s1", "职工", ["*编号"]),
           D("d1", "具有")]
    cons = [C("c1", "w1", "d1", "1"), C("c2", "d1", "s1", "N")]
    ok("B1 弱实体经菱形连强实体 → 不报", len(rule_R23(ctx(els, cons))) == 0)

    # B2 弱实体直连强实体 → 不报
    els = [E("w1", "亲属", ["#称呼"], weak=True), E("s1", "职工", ["*编号"])]
    cons = [{"id": "c1", "from": "w1", "to": "s1", "type": "line",
             "label": "", "cardinality": None}]
    ok("B2 弱实体直连强实体 → 不报", len(rule_R23(ctx(els, cons))) == 0)

    # B3 弱实体完全孤立 → 必须报
    els = [E("w1", "亲属", ["#称呼"], weak=True)]
    ok("B3 孤立弱实体 → 报错", len(rule_R23(ctx(els, []))) == 1)

    # B4 弱实体只连到另一个弱实体（且无强实体）→ 两个都应报
    els = [E("w1", "甲", ["#a"], weak=True), E("w2", "乙", ["#b"], weak=True)]
    cons = [{"id": "c1", "from": "w1", "to": "w2", "type": "line",
             "label": "", "cardinality": None}]
    n4 = len(rule_R23(ctx(els, cons)))
    ok("B4 弱实体仅连弱实体 → 两个各报一条", n4 == 2, f"实际 {n4} 条")

    # B5 三元联系：弱实体—菱形—强实体A + 菱形—强实体B → 不报
    els = [E("w1", "亲属", ["#称呼"], weak=True), E("s1", "职工", ["*编号"]),
           E("s2", "部门", ["*编号"]), D("d1", "归属")]
    cons = [C("c1", "w1", "d1", "1"), C("c2", "d1", "s1", "N"),
            C("c3", "d1", "s2", "N")]
    ok("B5 弱实体经三元菱形连强实体 → 不报",
       len(rule_R23(ctx(els, cons))) == 0)

    # B6 弱实体连菱形，菱形只连弱实体 → 两个弱实体各报一条
    els = [E("w1", "甲", ["#a"], weak=True), E("w2", "乙", ["#b"], weak=True),
           D("d1", "关联")]
    cons = [C("c1", "w1", "d1", "1"), C("c2", "d1", "w2", "N")]
    n6 = len(rule_R23(ctx(els, cons)))
    ok("B6 菱形两端都是弱实体 → 两个各报一条", n6 == 2, f"实际 {n6} 条")

    # B7 弱实体连到属性而非实体 → 必须报（属性不是依赖对象）
    els = [E("w1", "亲属", ["#称呼"], weak=True),
           {"id": "a1", "shape": "ellipse", "label": "电话", "attributes": []}]
    cons = [{"id": "c1", "from": "w1", "to": "a1", "type": "line",
             "label": "", "cardinality": None}]
    ok("B7 弱实体只连属性 → 报错", len(rule_R23(ctx(els, cons))) == 1)

    # B8 自环菱形不应导致死循环或错判
    els = [E("w1", "亲属", ["#称呼"], weak=True), D("d1", "自环")]
    cons = [{"id": "c1", "from": "d1", "to": "d1", "type": "line",
             "label": "", "cardinality": None},
            C("c2", "w1", "d1", "1")]
    try:
        res = rule_R23(ctx(els, cons))
        ok("B8 菱形自环不崩溃且判定为未依赖", len(res) == 1, f"实际 {len(res)}")
    except Exception as ex:
        ok("B8 菱形自环不崩溃", False, repr(ex))

    # ==============================================================
    # C. 邻接索引正确性（性能优化不得改变语义）
    # ==============================================================
    print("\n[C] 邻接索引正确性")

    # C1 自环：connections_of 应返回 1 条（不重复计）
    els = [E("e1", "A", ["*a"])]
    cons = [{"id": "c1", "from": "e1", "to": "e1", "type": "line",
             "label": "", "cardinality": None}]
    d = Diagram(els, cons)
    ok("C1 自环连线在邻接表中只记一次", len(d.connections_of("e1")) == 1,
       f"实际 {len(d.connections_of('e1'))}")

    # C2 悬空连线：端点不存在时仍可查到（用于 R10 判定）
    els = [E("e1", "A", ["*a"])]
    cons = [{"id": "c1", "from": "e1", "to": "幽灵", "type": "line",
             "label": "", "cardinality": None}]
    d = Diagram(els, cons)
    ok("C2 悬空连线仍能被查到", len(d.connections_of("e1")) == 1)
    ok("C2 悬空连线被识别", len(d.dangling_connections()) == 1)

    # C3 重复连线（同两端）应各自独立
    els = [E("e1", "A", ["*a"]), E("e2", "B", ["*b"])]
    cons = [{"id": "c1", "from": "e1", "to": "e2", "type": "line",
             "label": "", "cardinality": None},
            {"id": "c2", "from": "e1", "to": "e2", "type": "line",
             "label": "", "cardinality": None}]
    d = Diagram(els, cons)
    ok("C3 重复连线各自可查", len(d.connections_of("e1")) == 2,
       f"实际 {len(d.connections_of('e1'))}")

    # C4 索引结果与暴力扫描一致（随机图交叉验证）
    import random
    random.seed(42)
    mismatch = 0
    for trial in range(30):
        n = random.randint(2, 8)
        els = [E(f"e{i}", f"E{i}", ["*a"]) for i in range(n)]
        cons = []
        for k in range(random.randint(0, 10)):
            a, b = random.choice(els)["id"], random.choice(els)["id"]
            cons.append({"id": f"c{k}", "from": a, "to": b, "type": "line",
                         "label": "", "cardinality": None})
        d = Diagram(els, cons)
        for e in els:
            fast = {c.id for c in d.connections_of(e["id"])}
            slow = {c.id for c in d.connections.values()
                    if c.from_id == e["id"] or c.to_id == e["id"]}
            if fast != slow:
                mismatch += 1
    ok("C4 索引与暴力扫描结果一致（30 张随机图）", mismatch == 0,
       f"{mismatch} 处不一致")

    # C5 索引构建后修改 Diagram 不应产生脏读（当前设计是不可变使用）
    d = Diagram(els, cons)
    _ = d.connections_of("e0")
    ok("C5 邻接索引可重复查询稳定",
       len(d.connections_of("e0")) == len(d.connections_of("e0")))

    # ==============================================================
    # D. 端到端：修复前后行为对照（关键回归）
    # ==============================================================
    print("\n[D] 关键场景回归")
    from engine import Session, check_batch

    # D1 教科书弱实体图整体：应 0 刚性错误
    wf = {
        "elements": [
            {"id": "rect_001", "shape": "rectangle", "label": "职工",
             "attributes": ["*职工编号", "姓名", "性别"], "position": {"x": 1, "y": 1}},
            {"id": "rect_002", "shape": "rectangle", "label": "亲属",
             "is_weak": True, "attributes": ["#称呼", "姓名", "年龄"],
             "position": {"x": 2, "y": 2}},
            {"id": "dia_001", "shape": "diamond", "label": "具有",
             "attributes": [], "position": {"x": 3, "y": 3}},
        ],
        "connections": [
            {"id": "c1", "from": "rect_001", "to": "dia_001",
             "type": "diamond_line", "label": "", "cardinality": "1"},
            {"id": "c2", "from": "dia_001", "to": "rect_002",
             "type": "diamond_line", "label": "", "cardinality": "N"},
        ],
    }
    br = check_batch(Session(), {"action": "batch_check", "diagram": wf})
    rigid = {v["rule_id"] for r in br["results"].values()
             for v in r["violations"]}
    ok("D1 教科书弱实体图 0 刚性错误", not rigid, f"实际 {rigid}")

    # D2 人为破坏：把弱实体标记去掉但保留 # → 应报 R02（因为普通实体不能只靠 #）
    bad = {"elements": [
        {"id": "e1", "shape": "rectangle", "label": "学生",
         "attributes": ["#学号", "姓名"]},
        {"id": "e2", "shape": "rectangle", "label": "课程",
         "attributes": ["*课程号"]}],
        "connections": []}
    br = check_batch(Session(), {"action": "batch_check", "diagram": bad})
    rigid = {v["rule_id"] for r in br["results"].values()
             for v in r["violations"]}
    ok("D2 非弱实体用 # 顶替主键 → 报 R02", "R02" in rigid, f"实际 {rigid}")

    # D3 真孤立弱实体 → 报 R23
    bad2 = {"elements": [
        {"id": "w1", "shape": "rectangle", "label": "孤儿",
         "attributes": ["#a"], "is_weak": True},
        {"id": "s1", "shape": "rectangle", "label": "强", "attributes": ["*b"]}],
        "connections": []}
    br = check_batch(Session(), {"action": "batch_check", "diagram": bad2})
    rigid = {v["rule_id"] for r in br["results"].values()
             for v in r["violations"]}
    ok("D3 孤立弱实体 → 报 R23", "R23" in rigid, f"实际 {rigid}")

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题清单：")
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
