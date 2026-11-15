# -*- coding: utf-8 -*-
"""
规则真实性审计
==============

目的：独立于 test_engine.py，反查"规则是否真的在工作"。

背景：开发中曾发现 9 条规则因误写 `return []` 而静默失效——
     测试全绿但规则从未生效。故此处用**另一种方式**再验一遍：
     直接调用每条规则函数，断言：(1) 能返回非空；(2) 不抛异常。

方法：为每条规则构造"最小触发场景"，并同时构造"干净场景"，
     要求触发场景命中、干净场景不命中。任一不满足即报告。

运行：python audit_rules.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import inspect
import sys
from typing import Callable, List, Tuple

import rules as R
from model import Diagram
from rules import RuleContext


def ctx(elements, connections=None, req=""):
    return RuleContext(Diagram(elements, connections or [], req))


def E(eid, shape, label, attrs=None, weak=False):
    return {"id": eid, "shape": shape, "label": label,
            "attributes": attrs or [], "is_weak": weak}


def C(cid, f, t, typ="line", card=None, label=""):
    return {"id": cid, "from": f, "to": t, "type": typ,
            "label": label, "cardinality": card}


# 每个规则：(触发场景, 干净场景)
# 干净场景用于抓"误报"——规则不该在正常图上乱报。
CASES: dict[str, Tuple[Callable, Callable]] = {}

CASES["R01"] = (
    lambda: ctx([E("e1", "rectangle", ""), E("e2", "rectangle", "B", ["*b"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])]),
)
CASES["R02"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["姓名"]), E("e2", "rectangle", "B", ["*b"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])]),
)
CASES["R03"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("a1", "ellipse", "")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("a1", "ellipse", "属性")]),
)
CASES["R04"] = (
    lambda: ctx([E("d1", "diamond", "")]),
    lambda: ctx([E("d1", "diamond", "选修")]),
)
CASES["R05"] = (
    lambda: ctx([E("e1", "rectangle", "弱", ["*a"], weak=True)]),
    lambda: ctx([E("e1", "rectangle", "弱", ["#a"], weak=True)]),
)
CASES["R06"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "  "])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "b"])]),
)
CASES["R07"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "*b"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "b"])]),
)
CASES["R08"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "x", "x"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "x", "y"])]),
)
CASES["R09"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "A"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "b"])]),
)
CASES["R10"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"])], [C("c1", "e1", "e999", "diamond_line", "1")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e1x", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e1x", "diamond_line", "1")]),
)
CASES["R11"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"])], [C("c1", "e1", "e1")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2")]),
)
CASES["R12"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2"), C("c2", "e1", "e2")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2")]),
)
CASES["R13"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "line")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("a1", "ellipse", "属性")],
                [C("c1", "e1", "a1", "line")]),
)
CASES["R14"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("d1", "diamond", "联系")],
                [C("c1", "e1", "d1", "diamond_line", None)]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("d1", "diamond", "联系")],
                [C("c1", "e1", "d1", "diamond_line", "1")]),
)
CASES["R15"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("d1", "diamond", "联系")],
                [C("c1", "e1", "d1", "diamond_line", "X")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("d1", "diamond", "联系")],
                [C("c1", "e1", "d1", "diamond_line", "N")]),
)
CASES["R16"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "line", "1")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "line", None)]),
)
_c = [E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"]),
      E("d1", "diamond", "选修")]
CASES["R17"] = (
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", None)]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["R18"] = (
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1")]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["R19"] = (
    lambda: ctx(_c, []),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["R20"] = (
    lambda: ctx([E("d1", "diamond", "选修"), E("d2", "diamond", "选修")]),
    lambda: ctx([E("d1", "diamond", "选修"), E("d2", "diamond", "授课")]),
)
CASES["R21"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "A", ["*b"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])]),
)
CASES["R22"] = (
    lambda: ctx([E("d1", "diamond", "联系")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"])]),
)
CASES["R23"] = (
    lambda: ctx([E("e1", "rectangle", "弱", ["#a"], weak=True)]),
    lambda: ctx([E("e1", "rectangle", "弱", ["#a"], weak=True),
                 E("e2", "rectangle", "强", ["*b"])],
                [C("c1", "e1", "e2")]),
)

CASES["H01"] = (
    lambda: ctx([E("e1", "rectangle", "学生们", ["*a"])]),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])]),
)
CASES["H02"] = (
    lambda: ctx([E("d1", "diamond", "东西")]),
    lambda: ctx([E("d1", "diamond", "选修")]),
)
CASES["H03"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "电话"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "姓名"])]),
)
CASES["H04"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "年龄"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "出生日期"])]),
)
# H05 已收窄为"同类元素内部混用"才提示（见 rules.py 说明）。
# 触发用例：实体名之间中英并存。
# 干净用例：实体名全中文 + 属性名全英文 —— 跨类混用，教学中很常见，不应提示。
CASES["H05"] = (
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"]),
                 E("e2", "rectangle", "Student", ["*b"])]),
    lambda: ctx([E("e1", "rectangle", "学生", ["*student_id", "name"])]),
)
CASES["H06"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*i"] + [f"p{i}" for i in range(13)])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*i", "p1"])]),
)
CASES["H07"] = (
    lambda: ctx([E("e1", "rectangle", "学 生", ["*a"])]),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])]),
)
CASES["H08"] = (
    lambda: ctx([E("e1", "rectangle", "超长名称" * 6, ["*a"])]),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])]),
)
CASES["H09"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "diamond_line", "M")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "line", None)]),
)
CASES["H10"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("a1", "ellipse", "属性")],
                [C("c1", "e1", "a1", "line")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("a1", "ellipse", "属性")],
                [C("c1", "a1", "e1", "line")]),
)
CASES["H11"] = (
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1")]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["H12"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"]),
                 E("e3", "rectangle", "孤", ["*c"])],
                [C("c1", "e1", "e2", "line")]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])],
                [C("c1", "e1", "e2", "line")]),
)
CASES["H13"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["H14"] = (
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "1")]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["H15"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"]),
                 E("e3", "rectangle", "C", ["*c"]), E("d1", "diamond", "联系")],
                [C("c1", "e1", "d1", "diamond_line", "M"),
                 C("c2", "e2", "d1", "diamond_line", "N"),
                 C("c3", "e3", "d1", "diamond_line", "N")]),
    lambda: ctx(_c, [C("c1", "e1", "d1", "diamond_line", "1"),
                     C("c2", "e2", "d1", "diamond_line", "N")]),
)
CASES["H16"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a", "b"])]),
)
CASES["H17"] = (
    lambda: ctx([E("e1", "rectangle", "A", ["*a"])]),
    lambda: ctx([E("e1", "rectangle", "A", ["*a"]), E("e2", "rectangle", "B", ["*b"])]),
)
CASES["H18"] = (
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], "教师可以授课"),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], ""),
)
CASES["H19"] = (
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], "学生可以借阅图书"),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], ""),
)
CASES["H20"] = (
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], "需要记录成绩"),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], ""),
)
CASES["H21"] = (
    lambda: ctx([E("e1", "rectangle", "学员", ["*a"])], [], "学生可以选修"),
    lambda: ctx([E("e1", "rectangle", "学生", ["*a"])], [], "学生可以选修"),
)


def main() -> int:
    print("=" * 66)
    print("  规则真实性审计（每条规则：能触发 + 不误报 + 不抛异常）")
    print("=" * 66)

    all_ids = R.RULE_IDS
    fn_of = {rid: fn for rid, fn, _ in R.RULE_SPECS}

    no_case, empty, false_pos, raised = [], [], [], []
    level_drift: list = []

    for rid in all_ids:
        if rid not in CASES:
            no_case.append(rid)
            continue
        fn = fn_of[rid]
        make_hit, make_clean = CASES[rid]

        # 1) 触发场景
        try:
            got = fn(make_hit())
        except Exception as ex:
            raised.append((rid, "触发场景", repr(ex)))
            continue
        if not got:
            empty.append(rid)
        else:
            # 命中项 rule_id 应等于规则自身编号
            for it in got:
                if it["rule_id"] != rid:
                    false_pos.append((rid, f"回包 rule_id={it['rule_id']} 不匹配"))
                # 等级必须与 level_of 声明一致（v1.3 起前缀≠等级）
                want_lv = R.level_of(rid)
                if it["level"] != want_lv:
                    level_drift.append((rid, it["level"], want_lv))

        # 2) 干净场景（不该报）
        try:
            got2 = fn(make_clean())
        except Exception as ex:
            raised.append((rid, "干净场景", repr(ex)))
            continue
        if got2:
            false_pos.append(
                (rid, f"干净场景误报 {len(got2)} 条: {[i['rule_id'] for i in got2]}"))

    print(f"\n  规则总数: {len(all_ids)}")
    print(f"  有审计用例: {len(CASES)}")
    print(f"  缺用例: {len(no_case)} {no_case if no_case else ''}")
    print(f"  触发为空(疑似失效): {len(empty)} {empty if empty else ''}")
    print(f"  误报: {len(false_pos)}")
    for rid, d in false_pos:
        print(f"      [{rid}] {d}")
    print(f"  抛异常: {len(raised)}")
    for rid, where, d in raised:
        print(f"      [{rid}] {where}: {d}")
    print(f"  等级偏离(触发时 level ≠ level_of 声明): {len(level_drift)}")
    for rid, actual, want in level_drift:
        print(f"      [{rid}] 实际 {actual}，声明 {want}")

    bad = len(no_case) + len(empty) + len(false_pos) + len(raised) + len(level_drift)
    print("\n" + "=" * 66)
    if bad == 0:
        print("  结论：全部规则均真实生效，等级与声明一致，无误报、无异常 ✓")
    else:
        print(f"  结论：发现 {bad} 个问题")
    print("=" * 66)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
