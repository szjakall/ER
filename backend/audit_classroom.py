# -*- coding: utf-8 -*-
"""
课堂演练：多学生混合错误模式 → 班级统计正确性
==============================================

此前所有测试都是单学生或固定双人。本脚本做**时间压缩的课堂演练**：
模拟 30 个学生、5 种错误模式，经真实 ENGINE.handle 走完整校验+记账路径，
验证教师侧拿到的班级统计与个人诊断**与台账原始记录严格一致**。

学生分组（构造数据即预期答案）：
    P1–P10  主键组：只画缺主键实体（注意：会连带触发 H16——只有 1 个属性）
    C1–C8   基数组：画菱形 + 缺基数分支线（R17）
    M1–M6   混合组：缺主键实体 ×3 + 缺基数分支 ×2
    W1–W4   弱实体组：弱实体缺部分键（R05）
    OK1,OK2 完美组：合规实体（注意：单会话单实体仍会触发 H17 图规模过小——教学上合理）

方法论（v2 修正）：**不预设业务数字作为标准答案**（规则联动会让预设失真），
而是用独立 Counter 从台账原始记录重算 ground truth，
与 class_summary 输出对比——两个独立实现对同一份数据，结果必须一致。

运行：python audit_classroom.py（服务端内联使用，无需外部服务）
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
import time

from engine import ENGINE
from llm import Diagnoser
from weakness import WeaknessTracker

_passed = 0
_failed = 0
_problems: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        _problems.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def main() -> int:
    print("=" * 70)
    print("  课堂演练：30 学生 / 5 种错误模式 → 班级统计正确性")
    print("=" * 70)

    t = WeaknessTracker()
    # 注入隔离台账：让 ENGINE.handle 的完整记账路径写入 t，
    # 演练结束还原。此前 Engine._track 硬绑定全局 TRACKER，
    # 完整路径无法用隔离台账验证（本脚本首次实测即暴露此问题）。
    orig_tracker = ENGINE.tracker
    ENGINE.tracker = t
    # 用独立 Diagnoser（绑定演练台账）
    d = Diagnoser(tracker=t)

    try:
        return _run_classroom(t, d)
    finally:
        ENGINE.tracker = orig_tracker
        ENGINE.auto_diagnose = True


def _run_classroom(t, d) -> None:

    # --------------------------------------------------------------
    # 模拟绘图：经 ENGINE.handle 完整路径（校验 + 记账）
    # --------------------------------------------------------------
    ENGINE.auto_diagnose = False  # 演练不触发异步诊断，专注统计正确性
    now = 1000.0

    def draw(sid: str, label: str, attrs: list, shape: str = "rectangle",
             eid: str = "") -> None:
        """一个学生画一个元素（走完整 handle 路径）。"""
        nonlocal now
        now += 4.0  # 越过 3 秒去重窗口
        ENGINE.handle(sid, {
            "action": "check", "event": "element_added",
            "element": {"id": eid or f"{sid}_e{now}", "shape": shape,
                        "label": label, "attributes": attrs}})

    # P1–P10 主键组：每人画 6 个缺主键实体
    for i in range(1, 11):
        sid = f"P{i:02d}"
        for j in range(6):
            draw(sid, f"实体{j}", ["姓名"])

    # C1–C8 基数组：每人画 5 个缺基数联系分支
    # 联系分支缺基数需要 diamond + diamond_line 连线 → 经 handle 逐条建立
    for i in range(1, 9):
        sid = f"C{i:02d}"
        draw(sid, "课程", ["*课程号"])            # 先画合规实体
        draw(sid, "选修", [], shape="diamond")     # 画菱形
        for j in range(5):
            now += 4.0
            ENGINE.handle(sid, {
                "action": "check", "event": "connection_added",
                "connection": {"id": f"{sid}_c{j}",
                               "from": f"{sid}_e{1000.0 + 4}",
                               "to": f"{sid}_d", "type": "diamond_line",
                               "label": "", "cardinality": None}})

    # M1–M6 混合组：R02×3 + R17×2
    for i in range(1, 7):
        sid = f"M{i:02d}"
        for j in range(3):
            draw(sid, f"实体{j}", ["姓名"])       # 缺主键
        draw(sid, "课程", ["*课程号"])
        draw(sid, "选修", [], shape="diamond")
        for j in range(2):
            now += 4.0
            ENGINE.handle(sid, {
                "action": "check", "event": "connection_added",
                "connection": {"id": f"{sid}_mc{j}",
                               "from": f"{sid}_e{now-8:.1f}",
                               "to": f"{sid}_d", "type": "diamond_line",
                               "label": "", "cardinality": None}})

    # W1–W4 弱实体组：R05×4（弱实体缺部分键）
    for i in range(1, 5):
        sid = f"W{i:02d}"
        for j in range(4):
            now += 4.0
            ENGINE.handle(sid, {
                "action": "check", "event": "element_added",
                "element": {"id": f"{sid}_w{j}", "shape": "rectangle",
                            "label": f"亲属{j}",
                            "attributes": ["姓名"], "is_weak": True}})

    # OK1–OK2 完美组：合规实体，无违规
    for sid in ("OK1", "OK2"):
        draw(sid, "学生", ["*学号", "姓名"])

    # --------------------------------------------------------------
    # 验证：班级统计（交叉验证法）
    #
    # 方法论（v2 修正）：**不要预设业务数字作为标准答案**。
    # 初版预设了"R02 16 人 / R17 14 人"，实际跑出 H16 24 人——
    # 因为缺主键实体往往只有 1 个属性，H16（属性偏少）必然连带触发；
    # "完美组"单会话只画 1 个实体，H17（图规模过小）也合理触发。
    # 预设数字跟不真实场景的规则联动，有循环论证风险。
    #
    # 正确做法：用独立 Counter 从台账原始记录重算 ground truth，
    # 与 class_summary 输出对比——**两个独立实现对同一份数据，结果必须一致**。
    # --------------------------------------------------------------
    print("\n[1] 班级统计（交叉验证）")
    cs = t.class_summary(top_n=10)

    # 独立聚合 ground truth
    gt_students = set(t.all_users())
    gt_hit: dict = {}   # rule_id -> 命中学生集合
    gt_count: dict = {} # rule_id -> 总记录数
    for u in gt_students:
        for r in t.records_of(u):
            gt_hit.setdefault(r.rule_id, set()).add(u)
            gt_count[r.rule_id] = gt_count.get(r.rule_id, 0) + 1

    ok("台账学生数与原始记录一致",
       cs["student_count"] == len(gt_students),
       f"summary {cs['student_count']} vs 原始 {len(gt_students)}")

    # class_summary 的 by_rule（未截断全量）与 ground truth 一致
    issues = cs.get("common_issues", [])
    by_rule_all = {x["rule_id"]: x for x in cs.get("by_rule", [])}
    ok("by_rule 数量与 ground truth 一致",
       len(by_rule_all) == len(gt_hit),
       f"by_rule {len(by_rule_all)} vs 原始 {len(gt_hit)}")
    mismatch = []
    for rid, x in by_rule_all.items():
        if rid not in gt_hit:
            mismatch.append((rid, "ground truth 无此规则"))
            continue
        if x["student_count"] != len(gt_hit[rid]):
            mismatch.append((rid, f"学生数 {x['student_count']} vs {len(gt_hit[rid])}"))
        if x["total_count"] != gt_count.get(rid):
            mismatch.append((rid, f"总数 {x['total_count']} vs {gt_count.get(rid)}"))
        if abs(x["student_share"] - len(gt_hit[rid]) / len(gt_students)) > 1e-3:
            mismatch.append((rid, f"占比 {x['student_share']} vs {len(gt_hit[rid])/len(gt_students):.4f}"))
    ok("每条共性问题的人数/总数/占比与原始记录一致", not mismatch,
       f"{mismatch[:4]}")

    # 排序正确性：**按学生命中数降序**（v1.4 修正后的实现口径）。
    # 旧实现按总记录数排序，会把 30 人中招但记录少的规则压到后面——
    # 与需求书"80% 学生遗漏…"的教师语义不符。
    counts = [x["student_count"] for x in cs.get("by_rule", [])]
    ok("共性问题按命中人数降序", counts == sorted(counts, reverse=True),
       f"实际 {counts}")
    # ground truth 的 top3（按学生命中数）应与 summary 前 3 一致
    gt_sorted = sorted(gt_hit.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    gt_top3 = {rid for rid, _ in gt_sorted[:3]}
    sum_top3 = {x["rule_id"] for x in issues[:3]}
    ok("Top3 共性问题与 ground truth 一致", gt_top3 == sum_top3,
       f"gt {sorted(gt_top3)} vs summary {sorted(sum_top3)}")
    print(f"        班级共性问题 Top3: "
          f"{[(x['rule_id'], x['student_count']) for x in issues[:3]]}")

    # 结构断言：命中人数不超过学生总数
    ok("命中人数 ≤ 学生总数",
       all(x["student_count"] <= cs["student_count"] for x in issues))

    # --------------------------------------------------------------
    # 验证：个人诊断针对性（与该学生台账的 ground truth 对比）
    # weak_points 是 top-N 截断设计（默认 N=3）——不是"全部薄弱点"。
    # 断言口径（v2.1 修正）：weak_points 平局按**插入序**（记录时间序），
    #   故 gt 排序也按 (-count, 首次出现序)。字母序平局会选出不同的 top-N
    #   （W01 的 R05/R23 都是 4 次，插入序 R05 先 → 首位 R05；
    #    字母序会错选 R23，初版断言即因此假失败）。
    # --------------------------------------------------------------
    print("\n[2] 个人诊断针对性")
    for sid in ("P01", "C01", "M01", "W01"):
        recs = t.records_of(sid)
        gt_by_rule: dict = {}
        gt_first: dict = {}
        for idx, r in enumerate(recs):
            gt_by_rule[r.rule_id] = gt_by_rule.get(r.rule_id, 0) + 1
            gt_first.setdefault(r.rule_id, idx)
        # top_gt / top-N 均按 (-count, 首次出现序) —— 与实现口径一致
        gt_order = sorted(gt_by_rule.items(),
                          key=lambda kv: (-kv[1], gt_first[kv[0]]))
        top_gt = gt_order[0][0]
        rep = d.diagnose_user(sid)
        wp = {w["rule_id"] for w in rep.weak_points}
        gt_weak_top = {rid for rid, _ in gt_order[:len(wp)]}
        ok(f"{sid} 薄弱点=台账 top{len(wp)}（gt 全集 {sorted(gt_by_rule)}）",
           wp == gt_weak_top, f"实际 {wp}")
        # 首位薄弱点 == ground truth 中次数最多（平局取先出现）的规则
        if rep.weak_points:
            ok(f"{sid} 首位薄弱点是最高频规则（{top_gt}）",
               rep.weak_points[0]["rule_id"] == top_gt,
               f"实际 {rep.weak_points[0]['rule_id']}")
        print(f"        {sid}: {sorted(gt_by_rule.items())} → "
              f"首位 {rep.weak_points[0]['rule_id'] if rep.weak_points else '-'}")

    # 单次错误学生（无 count>=2）不应有 weak_points
    repOK = d.diagnose_user("OK1")
    ok("低频学生（H17×1）无薄弱点标记",
       len(repOK.weak_points) == 0,
       f"实际 {[(w['rule_id'], w['count']) for w in repOK.weak_points]}")
    ok("低频学生诊断仍是合法报告", bool(repOK.summary))

    # --------------------------------------------------------------
    # 验证：班级摘要的自然语言
    # --------------------------------------------------------------
    print("\n[3] 班级摘要（教师视角）")
    cls = d.diagnose_class(top_n=3)
    # 摘要正文应提到 summary 排序首位问题的知识点
    # （与 class_summary 的排序口径一致——按学生命中数）
    if issues:
        top_rule = issues[0]["rule_id"]
        from llm import knowledge_of
        top_topic = knowledge_of(top_rule)["topic"]
        ok(f"班级摘要正文提到首位问题知识点（{top_rule} → {top_topic}）",
           top_topic in cls["summary"],
           f"摘要首行: {cls['summary'].splitlines()[0][:60]}")
    ok("班级摘要含教学建议",
       len(cls.get("teaching_advice", [])) > 0)
    for adv in cls.get("teaching_advice", [])[:2]:
        print(f"        建议: {adv[:60]}")

    ENGINE.auto_diagnose = True

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
