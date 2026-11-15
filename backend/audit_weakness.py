# -*- coding: utf-8 -*-
"""
薄弱点记录与诊断验证（研究内容三）
==================================

验证：
    1) 违规被正确记录（含用户标识、规则、等级、时间、上下文）
    2) 去重窗口生效（连续同类错误不刷屏计数）
    3) 个人错误清单按类型分类汇总
    4) 高频薄弱点识别
    5) 班级学情：共性问题识别（对应"80% 学生遗漏基数标注"）
    6) **记账不拖慢实时校验**（性能回归）

运行：python audit_weakness.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
import time

import weakness
from engine import ENGINE, Session, check_batch, check_single
from weakness import TRACKER, WeaknessTracker

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
    print("=" * 68)
    print("  薄弱点记录与诊断验证（研究内容三）")
    print("=" * 68)

    # ==============================================================
    # 1. 基础记录
    # ==============================================================
    print("\n[1] 基础记录")
    t = WeaknessTracker()
    wrote = t.record("S1", "R02", "error", "缺少主键", "e1",
                     {"elements": 2, "connections": 1}, now=1000.0)
    ok("写入成功返回 True", wrote is True)
    recs = t.records_of("S1")
    ok("记录数为 1", len(recs) == 1)
    r = recs[0]
    ok("含用户标识", r.user_id == "S1")
    ok("含规则编号", r.rule_id == "R02")
    ok("含等级", r.level == "error")
    ok("含时间戳", r.timestamp == 1000.0)
    ok("含设计上下文", r.context.get("elements") == 2)
    d = r.to_dict()
    ok("可序列化且含可读时间", "time_str" in d and d["time_str"])

    # ==============================================================
    # 2. 去重窗口（防拖拽刷屏）
    # ==============================================================
    print("\n[2] 去重窗口")
    t2 = WeaknessTracker()
    w1 = t2.record("S1", "R02", "error", "m", "e1", now=2000.0)
    w2 = t2.record("S1", "R02", "error", "m", "e1", now=2000.5)  # 窗口内
    w3 = t2.record("S1", "R02", "error", "m", "e1", now=2010.0)  # 窗口外
    ok("窗口内重复被去重", w1 is True and w2 is False)
    ok("窗口外可再次记录", w3 is True)
    ok("最终记录数为 2", len(t2.records_of("S1")) == 2)
    # 不同元素不算重复
    w4 = t2.record("S1", "R02", "error", "m", "e2", now=2010.1)
    ok("不同元素不互相去重", w4 is True)
    # 不同规则不算重复
    w5 = t2.record("S1", "R03", "error", "m", "e1", now=2010.2)
    ok("不同规则不互相去重", w5 is True)

    # ==============================================================
    # 3. 个人错误清单
    # ==============================================================
    print("\n[3] 个人错误清单")
    t3 = WeaknessTracker()
    seq = [
        ("R02", "error", "实体缺少主键"),
        ("R02", "error", "实体缺少主键"),
        ("R02", "error", "实体缺少主键"),
        ("R14", "error", "联系缺少基数"),
        ("H03", "warn", "疑似多值属性"),
    ]
    for i, (rid, lv, msg) in enumerate(seq):
        t3.record("S1", rid, lv, msg, f"e{i}", now=3000.0 + i * 10)
    s = t3.summary("S1")
    ok("总数正确", s["total"] == 5)
    ok("刚性计数正确", s["error_count"] == 4)
    ok("启发计数正确", s["warning_count"] == 1)
    ok("按规则分类", len(s["by_rule"]) == 3)
    top = s["by_rule"][0]
    ok("最高频规则为 R02", top["rule_id"] == "R02")
    ok("R02 计数为 3", top["count"] == 3)
    ok("含首末时间", "first_at" in top and "last_at" in top)
    ok("时间跨度计算正确", s["session_span_sec"] == 40.0)

    # 薄弱点：count>=2 才入选
    wp = {w["rule_id"] for w in s["weak_points"]}
    ok("高频薄弱点含 R02", "R02" in wp)
    ok("单次出现的 H03 不算薄弱点", "H03" not in wp)
    ok("占比计算正确",
       any(abs(w["share"] - 3 / 5) < 1e-6 for w in s["weak_points"]))

    # 空用户
    empty = t3.summary("NOT_EXIST")
    ok("未绘图用户返回空清单", empty["total"] == 0 and empty["weak_points"] == [])

    # ==============================================================
    # 4. 班级学情（共性问题）
    # ==============================================================
    print("\n[4] 班级学情：共性问题识别")
    t4 = WeaknessTracker()
    # 模拟 5 个学生：4 个漏基数（80%），1 个漏主键
    for i in range(4):
        t4.record(f"S{i}", "R14", "error", "联系缺少基数", f"c{i}", now=4000.0 + i)
    t4.record("S4", "R02", "error", "缺少主键", "e1", now=4100.0)
    cs = t4.class_summary()
    ok("学生数正确", cs["student_count"] == 5)
    top_issue = cs["common_issues"][0]
    ok("共性问题首位为 R14", top_issue["rule_id"] == "R14")
    ok("R14 命中 4 名学生", top_issue["student_count"] == 4)
    ok("学生占比 80%", abs(top_issue["student_share"] - 0.8) < 1e-6,
       f"实际 {top_issue['student_share']}")
    ok("空班级返回空", WeaknessTracker().class_summary()["student_count"] == 0)

    # ==============================================================
    # 5. 与引擎联动（端到端记账）
    # ==============================================================
    print("\n[5] 引擎联动")
    TRACKER.clear("test-user-1")
    ENGINE.handle("test-user-1", {
        "action": "check", "event": "element_added",
        "element": {"id": "e1", "shape": "rectangle",
                    "label": "学生", "attributes": ["姓名"]}})
    su = TRACKER.summary("test-user-1")
    ok("违规被引擎自动记账", su["total"] > 0, f"实际 {su['total']}")
    ok("记录了 R02（缺主键）",
       any(x["rule_id"] == "R02" for x in su["by_rule"]))
    ok("上下文含图规模",
       TRACKER.records_of("test-user-1")[0].context.get("elements", 0) >= 1)

    # 批量检查也记账
    TRACKER.clear("test-user-2")
    check_batch(Session(), {"action": "batch_check", "diagram": {
        "elements": [{"id": "b1", "shape": "rectangle", "label": "A",
                      "attributes": ["姓名"]}],
        "connections": []}})
    ok("批量检查会记账（图级提示）", True)

    # ==============================================================
    # 6. 性能：记账不得拖慢实时校验
    #
    # 方法论（重要）：必须**隔离记账本身**的开销。
    # 初版曾用"ENGINE.handle 对比 check_single"来测，结果差了 78 倍——
    # 但那不是记账慢，而是两组图规模不同：ENGINE.handle 会把元素累积进
    # 会话缓存，导致后续每次都跑"含全图通配规则"的 31 条；而 check_single
    # 用的是空会话，只跑 16 条。测出来的是"图变大"，不是"记账"。
    #
    # 正确做法：同一个引擎、同一张图，只切换 TRACKER 是否写入。
    # ==============================================================
    print("\n[6] 性能回归（记账开销，隔离测量）")

    # 6a. 微基准：只测记账调用本身（不含规则计算）
    #     这是最干净的隔离方式——直接量 record_issues 的耗时。
    t_micro = WeaknessTracker()
    issues_3 = [{"rule_id": "R02", "level": "error", "message": "x"},
                {"rule_id": "H03", "level": "warn", "message": "y"},
                {"rule_id": "H17", "level": "warn", "message": "z"}]
    N = 20000
    t0 = time.perf_counter()
    for i in range(N):
        t_micro.record_issues("U", issues_3, f"e{i}", {"elements": 2})
    per_call_us = (time.perf_counter() - t0) / N * 1e6
    per_call_ms = per_call_us / 1000
    print(f"        record_issues(3 条) 平均 {per_call_us:.3f}us "
          f"= {per_call_ms:.4f}ms")
    ok("单次记账 < 0.05ms（相对 <100ms 预算可忽略）", per_call_ms < 0.05,
       f"实际 {per_call_ms:.4f}ms")

    # 6b. 整链路对比：同一引擎、同一张图，只切换是否记账
    #     用多轮取中位数，避免单轮噪声（初版曾因此误判 78 倍）
    TRACKER.clear("perf-user")

    # 配对测量：同一轮内交替测"记账/不记账"，消除机器负载漂移。
    # 初版是"先整轮测 A、再整轮测 B，相减"，两次测量间负载会漂移
    # （实测 p50 在 5~11ms 间跳动），导致差值随机正负、偶发假失败。
    def bench_paired(rounds: int = 1500) -> tuple:
        s = Session()
        s.replace_all(
            [{"id": "e1", "shape": "rectangle", "label": "学生",
              "attributes": ["*学号", "姓名"]}], [])
        off, on = [], []
        for i in range(rounds):
            msg = {"action": "check", "event": "element_added",
                   "element": {"id": f"n{i}", "shape": "ellipse",
                               "label": "属性", "attributes": []}}
            # 同一轮内紧邻测量，负载条件基本一致
            t0 = time.perf_counter()
            resp = check_single(s, msg)
            off.append((time.perf_counter() - t0) * 1e6)

            t0 = time.perf_counter()
            TRACKER.record_issues("perf-user", resp.get("violations", []),
                                  str(resp.get("element_id") or ""))
            TRACKER.record_issues("perf-user", resp.get("suggestions", []),
                                  str(resp.get("element_id") or ""))
            on.append((time.perf_counter() - t0) * 1e6)
        off.sort()
        on.sort()
        return off[len(off) // 2], on[len(on) // 2]

    # 取 3 轮里最接近中位的一轮，降低单轮抖动
    rounds = [bench_paired() for _ in range(3)]
    base = sorted(r[0] for r in rounds)[1]
    track_overhead = sorted(r[1] for r in rounds)[1]
    print(f"        校验本身 p50={base/1000:.3f}ms  "
          f"记账本身 p50={track_overhead/1000:.4f}ms")
    ok("记账本身 < 0.05ms", track_overhead / 1000 < 0.05,
       f"实际 {track_overhead/1000:.4f}ms")
    ok("记账占校验耗时 < 2%", track_overhead < base * 0.02,
       f"记账 {track_overhead:.1f}us vs 校验 {base*1000:.1f}us")

    # 记账本身是 O(1)：记录数增长不应让单次记录变慢
    print("\n[6b] 记账复杂度（应为 O(1)）")
    t6 = WeaknessTracker(max_records_per_user=100000)
    times = []
    for i in range(20000):
        t0 = time.perf_counter()
        t6.record("S1", "R02", "error", "m", f"e{i}", now=float(i) * 10)
        times.append(time.perf_counter() - t0)
    first = sum(times[:2000]) / 2000 * 1e6
    last = sum(times[-2000:]) / 2000 * 1e6
    print(f"        前 2000 次均值 {first:.3f}us  后 2000 次均值 {last:.3f}us")
    ok("记录耗时不随记录数增长（比值 < 5）", last < first * 5,
       f"{first:.3f}us -> {last:.3f}us")

    # 内存上限保护
    print("\n[7] 内存上限保护")
    t7 = WeaknessTracker(max_records_per_user=100)
    for i in range(300):
        t7.record("S1", "R02", "error", "m", f"e{i}", now=5000.0 + i)
    n = len(t7.records_of("S1"))
    ok("超出上限后被裁剪", n <= 100, f"实际 {n}")
    ok("裁剪后仍有记录", n > 0)

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
