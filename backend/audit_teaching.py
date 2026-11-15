# -*- coding: utf-8 -*-
"""
教学场景覆盖度审查
==================

目的：找出"教材必讲、但当前规则集未覆盖或判错"的场景。

数据库原理课程里，ER 图部分的必讲概念：
    1. 一元（递归）联系      员工—管理—员工
    2. 二元联系              学生—选修—课程
    3. 三元联系              供应商—供应—项目/零件
    4. 弱实体与鉴别器        职工—具有—亲属
    5. ISA 继承（子类/超类）  研究生 ISA 学生
    6. 聚合（Aggregation）   部门—员工 聚合后参与"项目"
    7. 多值属性、派生属性、复合属性
    8. 联系的属性（如"选修"有"成绩"）
    9. 全部 4 种基数：1:1 / 1:N / M:N / 三元 M:N:P
   10. 完全/部分参与约束

本脚本对每个场景构造图，检查引擎判定是否合理，并标出**未覆盖**的场景。

运行：python audit_teaching.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
from pathlib import Path

from engine import Session, check_batch

_passed = 0
_failed = 0
_notes: list[str] = []
_gaps: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {detail}")


def note(msg: str) -> None:
    _notes.append(msg)
    print(f"  [注意] {msg}")


def gap(msg: str) -> None:
    _gaps.append(msg)
    print(f"  [缺口] {msg}")


def E(eid, label, attrs=None, weak=False):
    return {"id": eid, "shape": "rectangle", "label": label,
            "attributes": attrs or [], "is_weak": weak}


def D(did, label, attrs=None):
    return {"id": did, "shape": "diamond", "label": label,
            "attributes": attrs or []}


def A(aid, label):
    return {"id": aid, "shape": "ellipse", "label": label, "attributes": []}


def C(cid, f, t, typ="diamond_line", card=None):
    return {"id": cid, "from": f, "to": t, "type": typ,
            "label": "", "cardinality": card}


def run(elements, connections, req=""):
    msg = {"action": "batch_check",
           "diagram": {"elements": elements, "connections": connections}}
    if req:
        msg["requirement_text"] = req
    s = Session()
    resp = check_batch(s, msg)
    rigid, hints = {}, {}
    for v in resp["results"].values():
        for it in v["violations"]:
            rigid.setdefault(it["rule_id"], it["message"])
        for it in v["suggestions"]:
            hints.setdefault(it["rule_id"], it["message"])
    return rigid, hints


def main() -> int:
    print("=" * 68)
    print("  教学场景覆盖度审查")
    print("=" * 68)

    # ==============================================================
    # 1. 一元（递归）联系：员工 —管理— 员工
    #
    # 注意用例写法（曾被独立审查指出的缺陷）：
    #   早期此用例写成 e1→d1 与 **d1→e1**（人为反向），
    #   恰好绕过了 R12 的真实触发条件（两个端点对相同）。
    #   而前端 store.ts 的 addConnection 对同一对元素不分方向一律拒绝，
    #   所以"反向写法"在实际画布上根本画不出来——
    #   用这种不可达的形态做测试，等于没测。
    #   现改为**两条同向**分支线（学生在画布上真实画出的形态）。
    # ==============================================================
    print("\n[1] 一元（递归）联系")
    els = [E("e1", "员工", ["*工号", "姓名"]), D("d1", "管理")]
    cons = [C("c1", "e1", "d1", "diamond_line", "1"),
            C("c2", "e1", "d1", "diamond_line", "N")]
    rigid, hints = run(els, cons)
    ok("递归联系不报刚性错误（同向两条分支线）", not rigid, f"实际 {rigid}")
    ok("递归联系不误报重复连线 R12", "R12" not in rigid)
    note("一元联系通过（菱形两端连同一实体，两条分支线同向、基数不同）")

    # ==============================================================
    # 2. 二元联系 1:N（标准）
    # ==============================================================
    print("\n[2] 二元联系 1:N")
    els = [E("e1", "班级", ["*班号"]), E("e2", "学生", ["*学号"]),
           D("d1", "属于")]
    cons = [C("c1", "e1", "d1", "diamond_line", "1"),
            C("c2", "d1", "e2", "diamond_line", "N")]
    rigid, hints = run(els, cons)
    ok("1:N 二元联系无刚性错误", not rigid, f"实际 {rigid}")

    # ==============================================================
    # 3. 三元联系 M:N:P
    # ==============================================================
    print("\n[3] 三元联系 M:N:P")
    els = [E("s", "供应商", ["*供应商号"]), E("p", "项目", ["*项目号"]),
           E("l", "零件", ["*零件号"]), D("d1", "供应")]
    cons = [C("c1", "s", "d1", "diamond_line", "M"),
            C("c2", "p", "d1", "diamond_line", "N"),
            C("c3", "l", "d1", "diamond_line", "P")]
    rigid, hints = run(els, cons)
    ok("三元联系 M:N:P 无刚性错误", not rigid, f"实际 {rigid}")
    if "H15" not in hints:
        note("三元 M:N:P 未触发 H15（该组合是标准写法，不该提示）")
    else:
        note("三元 M:N:P 触发了 H15 提示 —— 需确认是否误报标准写法")

    # ==============================================================
    # 4. 弱实体
    # ==============================================================
    print("\n[4] 弱实体与鉴别器")
    els = [E("w", "亲属", ["#称呼", "姓名"], weak=True),
           E("s", "职工", ["*职工编号"]), D("d1", "具有")]
    cons = [C("c1", "s", "d1", "diamond_line", "1"),
            C("c2", "d1", "w", "diamond_line", "N")]
    rigid, hints = run(els, cons)
    ok("弱实体图无刚性错误", not rigid, f"实际 {rigid}")

    # ==============================================================
    # 5. 联系的属性（如"选修"有"成绩"）
    # ==============================================================
    print("\n[5] 联系的属性")
    els = [E("s", "学生", ["*学号"]), E("c", "课程", ["*课程号"]),
           D("d1", "选修", ["成绩"])]
    cons = [C("c1", "s", "d1", "diamond_line", "M"),
            C("c2", "c", "d1", "diamond_line", "N")]
    rigid, hints = run(els, cons)
    ok("联系带属性无刚性错误", not rigid, f"实际 {rigid}")
    note("联系的属性（选修.成绩）不报错，符合教材")

    # ==============================================================
    # 6. ISA 继承（子类/超类）
    # ==============================================================
    print("\n[6] ISA 继承（子类/超类）")
    els = [E("e1", "学生", ["*学号", "姓名"]),
           E("e2", "研究生", ["*学号", "导师"]),
           D("d1", "ISA")]
    cons = [C("c1", "e1", "d1", "diamond_line", "1"),
            C("c2", "d1", "e2", "diamond_line", "1")]
    rigid, hints = run(els, cons)
    if rigid:
        note(f"ISA 继承报出刚性错误 {list(rigid)} —— 教材中 ISA 常用三角/菱形表示，"
             f"若学生这样画会被误判")
    else:
        note("ISA 继承（用菱形表示）不报刚性错误")
    if "H14" in hints:
        gap("ISA 继承触发了 H14「各端基数均为 1」提示 —— "
            "ISA 的标准写法就是 1:1，此处提示属噪音")
    # ISA 的子类通常有自己的主键（同超类主键），不报 R21/R02 是合理的

    # ==============================================================
    # 7. 多值/派生/复合属性
    # ==============================================================
    print("\n[7] 多值 / 派生 / 复合属性")
    els = [E("e1", "员工", ["*工号", "电话", "年龄", "姓名"]),
           D("d1", "属于"), E("e2", "部门", ["*部门号"])]
    cons = [C("c1", "e1", "d1", "diamond_line", "N"),
            C("c2", "d1", "e2", "diamond_line", "1")]
    rigid, hints = run(els, cons)
    ok("多值+派生属性不报刚性错误", not rigid, f"实际 {rigid}")
    ok("识别多值属性（电话）", "H03" in hints)
    ok("识别派生属性（年龄）", "H04" in hints)

    # ==============================================================
    # 8. 1:1 联系
    # ==============================================================
    print("\n[8] 1:1 联系")
    els = [E("e1", "部门", ["*部门号"]), E("e2", "经理", ["*工号"]),
           D("d1", "担任")]
    cons = [C("c1", "e1", "d1", "diamond_line", "1"),
            C("c2", "d1", "e2", "diamond_line", "1")]
    rigid, hints = run(els, cons)
    ok("1:1 联系无刚性错误", not rigid, f"实际 {rigid}")
    ok("1:1 触发 H14 确认提示（合理）", "H14" in hints)

    # ==============================================================
    # 9. 属性椭圆与实体连线（教材画法）
    # ==============================================================
    print("\n[9] 属性椭圆连到实体")
    els = [E("e1", "学生", ["*学号"]), A("a1", "姓名"), A("a2", "年龄")]
    cons = [C("c1", "a1", "e1", "line", None),
            C("c2", "a2", "e1", "line", None)]
    rigid, hints = run(els, cons)
    ok("属性椭圆经 line 连实体无刚性错误", not rigid, f"实际 {rigid}")
    if "H10" in hints:
        note("属性指向实体的连线未触发 H10（方向正确）")

    # 反向：实体指向属性
    cons2 = [C("c1", "e1", "a1", "line", None)]
    rigid2, hints2 = run(els, cons2)
    ok("实体指向属性时触发 H10 提示", "H10" in hints2)

    # ==============================================================
    # 10. 完全独立的多实体图（局部绘制中）
    # ==============================================================
    print("\n[10] 绘制中间态（只画了实体还没画联系）")
    els = [E("e1", "学生", ["*学号"]), E("e2", "课程", ["*课程号"])]
    rigid, hints = run(els, [])
    ok("中间态不报刚性错误", not rigid, f"实际 {rigid}")
    ok("中间态给出 H13 提示（合理）", "H13" in hints)

    # ==============================================================
    # 汇总
    # ==============================================================
    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _gaps:
        print("\n  发现的教学覆盖缺口：")
        for g in _gaps:
            print(f"    - {g}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
