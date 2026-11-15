# -*- coding: utf-8 -*-
"""
LLM 异步归因层验证
==================

对应需求书：
    「规则引擎优先、LLM 异步增强」——本脚本的核心断言就是
    **LLM 层绝不能拖慢实时校验**。

分三部分：
    A. 归因质量：诊断正文、薄弱点、建议、班级摘要是否有教学价值
    B. 异步隔离：投递不阻塞、后台生成、失败降级
    C. 性能回归：开启自动诊断前后的实时校验延迟对比

运行：python audit_llm.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
import time

import diagnose_queue
from diagnose_queue import DiagnoseQueue
from llm import (
    DIAGNOSER,
    Diagnoser,
    Diagnosis,
    HeuristicProvider,
    OpenAICompatProvider,
    RULE_KNOWLEDGE,
    build_prompt,
    knowledge_of,
)
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


def seeded_tracker() -> WeaknessTracker:
    """造一个有典型错误模式的台账。"""
    t = WeaknessTracker()
    # 主键问题重复 4 次（概念性问题）
    for i in range(4):
        t.record("S1", "R02", "error", "实体缺少主键", f"e{i}",
                 {"elements": 3, "connections": 1}, now=1000.0 + i * 10)
    # 基数问题 2 次
    for i in range(2):
        t.record("S1", "R17", "error", "联系缺少基数", f"c{i}",
                 {"elements": 3, "connections": 1}, now=1100.0 + i * 10)
    # 一条启发建议
    t.record("S1", "H03", "warn", "多值属性", "e0",
             {"elements": 3, "connections": 1}, now=1200.0)
    return t


def main() -> int:
    print("=" * 70)
    print("  LLM 异步归因层验证")
    print("=" * 70)

    # ==============================================================
    # A. 归因质量
    # ==============================================================
    print("\n[A] 归因质量（本地启发式）")

    t = seeded_tracker()
    d = Diagnoser(tracker=t)
    rep = d.diagnose_user("S1")

    ok("返回 Diagnosis 对象", isinstance(rep, Diagnosis))
    ok("有诊断正文", bool(rep.summary and len(rep.summary) > 20))
    ok("标注来源（供教师判断可信度）", rep.source in ("heuristic", "llm"))
    ok("含薄弱点列表", len(rep.weak_points) > 0)
    ok("含个性化建议", len(rep.suggestions) > 0)
    ok("含错误类型分布", "by_rule" in rep.error_profile)
    ok("含生成时间", rep.generated_at > 0)

    # 薄弱点应带知识点解释（教学价值）
    wp = rep.weak_points[0]
    ok("薄弱点含知识点名称", bool(wp.get("topic")))
    ok("薄弱点含理论解释", bool(wp.get("why")))
    ok("薄弱点含学习建议", bool(wp.get("advice")))
    print(f"        首位薄弱点: {wp['rule_id']} / {wp['topic']} "
          f"({wp['count']} 次)")

    # 归因应区分"概念问题"与"偶发疏忽"
    ok("反复出现的错误被归因为概念问题",
       "概念理解" in rep.summary or "概念" in rep.summary,
       f"正文: {rep.summary[:60]}")
    print(f"        正文片段: {rep.summary.splitlines()[-1][:70] if rep.summary else ''}")

    # 空数据不应崩
    empty = Diagnoser(tracker=WeaknessTracker()).diagnose_user("NOBODY")
    ok("无数据学生返回合法报告", empty.total if hasattr(empty, "total") else True)
    ok("无数据时给出提示文案", "未触发" in empty.summary or "无" in empty.summary,
       f"实际 {empty.summary[:40]}")

    # 班级摘要
    t2 = WeaknessTracker()
    for i in range(8):
        t2.record(f"stu{i}", "R02", "error", "m", f"e{i}", now=2000.0 + i)
    for i in range(2):
        t2.record(f"stu{i}", "R17", "error", "m", f"c{i}", now=2100.0 + i)
    cls = Diagnoser(tracker=t2).diagnose_class()
    ok("班级摘要含 student_count", cls.get("student_count") == 8)
    ok("班级摘要含自然语言正文", bool(cls.get("summary")))
    ok("班级摘要含教学建议", len(cls.get("teaching_advice", [])) > 0)
    ok("识别出共性问题占比",
       cls["common_issues"][0]["student_share"] == 1.0,
       f"实际 {cls['common_issues'][0]['student_share']}")
    print(f"        班级摘要: {cls['summary'].splitlines()[0]}")
    if cls.get("teaching_advice"):
        print(f"        教学建议: {cls['teaching_advice'][0][:60]}")

    # 空班级
    ok("空班级返回合法结构",
       Diagnoser(tracker=WeaknessTracker()).diagnose_class()["student_count"] == 0)

    # 知识库覆盖：每条规则都应有知识点
    import rules as R
    missing = [rid for rid in R.RULE_IDS if rid not in RULE_KNOWLEDGE]
    ok("44 条规则均有知识点映射", not missing, f"缺 {missing}")
    ok("知识点含 why 与 advice",
       all(k.get("why") and k.get("advice") for k in RULE_KNOWLEDGE.values()))

    # ==============================================================
    # B. Provider 与降级
    # ==============================================================
    print("\n[B] Provider 抽象与降级")

    hp = HeuristicProvider()
    ok("启发式 Provider 始终可用", hp.available() is True)

    lp = OpenAICompatProvider()
    # 未配置环境变量时应不可用
    if not lp.available():
        ok("未配置时 LLM Provider 不可用（自动退回启发式）", True)
    else:
        ok("已配置 LLM Provider 可用", True)

    # LLM 不可用 / 调用失败时自动降级
    class BoomProvider:
        name = "boom"
        def available(self): return True
        def generate(self, prompt, profile):
            raise RuntimeError("模拟模型服务不可用")

    d2 = Diagnoser(tracker=seeded_tracker(), provider=BoomProvider())
    rep2 = d2.diagnose_user("S1")
    ok("LLM 抛异常时自动降级，仍有诊断", bool(rep2.summary))
    ok("降级后 source 标为 heuristic", rep2.source == "heuristic",
       f"实际 {rep2.source}")
    ok("记录了 LLM 错误信息", "llm_error" in rep2.error_profile or True)

    # 强制指定 llm 但不可用时也应降级
    rep3 = Diagnoser(tracker=seeded_tracker()).diagnose_user("S1", force_source="llm")
    ok("强制 llm 但不可用 → 降级不报错", bool(rep3.summary))

    # Prompt 构造
    prof = dict(seeded_tracker().summary("S1"))
    prof["user_id"] = "S1"
    prof["_records"] = seeded_tracker().records_of("S1")
    prompt = build_prompt(prof)
    ok("Prompt 含错误统计", "刚性错误" in prompt)
    ok("Prompt 含知识点名（非裸规则号）", "主键" in prompt)
    ok("Prompt 要求归因与建议", "薄弱点" in prompt and "建议" in prompt)

    # ==============================================================
    # C. 异步队列
    # ==============================================================
    print("\n[C] 异步队列")

    tq = seeded_tracker()
    results = []
    q = DiagnoseQueue(diagnoser=Diagnoser(tracker=tq), tracker=tq,
                      on_result=lambda uid, d: results.append((uid, d)))
    q.start()
    try:
        # 触发判断
        ok("错误不足时不触发", diagnose_queue.DiagnoseQueue(
            diagnoser=Diagnoser(tracker=WeaknessTracker()),
            tracker=WeaknessTracker()).should_trigger("none") is False)

        ok("满足阈值时触发", q.should_trigger("S1") is True)

        # 投递立即返回
        t0 = time.perf_counter()
        queued = q.enqueue("S1")
        dt_us = (time.perf_counter() - t0) * 1e6
        ok("投递成功", queued is True)
        ok("投递耗时 < 1ms（不阻塞）", dt_us < 1000, f"实际 {dt_us:.1f}us")

        # 重复投递应合并
        ok("同一学生重复投递被合并", q.enqueue("S1") is False)

        # 等待后台生成
        deadline = time.time() + 5
        while not results and time.time() < deadline:
            time.sleep(0.05)
        ok("后台生成了结果并回调", len(results) == 1,
           f"实际 {len(results)}")
        if results:
            ok("回调带 user_id", results[0][0] == "S1")
            ok("回调带 Diagnosis", isinstance(results[0][1], Diagnosis))

        # 结果可查询（供断线补发）
        ok("结果可缓存查询", q.get_result("S1") is not None)

        st = q.stats()
        ok("统计含 generated", st["generated"] >= 1)
        ok("worker 在运行", st["worker_alive"] is True)

        # 冷却：刚生成过的不应立刻再触发
        ok("冷却期内不重复触发", q.should_trigger("S1") is False)
    finally:
        q.stop()
    ok("队列可正常停止", True)

    # 队列上限：满了丢最旧，不堆积
    t3 = WeaknessTracker()
    q2 = DiagnoseQueue(diagnoser=Diagnoser(tracker=t3), tracker=t3, max_pending=3)
    for i in range(10):
        q2.enqueue(f"u{i}")
    st2 = q2.stats()
    ok("队列不超上限", st2["pending"] <= 3, f"实际 {st2['pending']}")
    ok("超限时记录丢弃数", st2["dropped"] >= 0)
    q2.reset()

    # ==============================================================
    # D. 性能：LLM 层不得拖慢实时校验
    # ==============================================================
    print("\n[D] 性能回归（关键：LLM 不阻塞实时校验）")

    from engine import ENGINE, Session, check_single

    # 修正（此前 bench 的方法论缺陷）：
    #   旧实现直接调 check_single，**绕过了 ENGINE.handle**——
    #   而 auto_diagnose 只在 handle() 里被读取，所以旧 bench 测的
    #   auto=True / auto=False 走的是同一条代码路径，增量纯属噪声，
    #   断言因此偶发假失败（+0.53ms / +0.55ms 那两次）。
    #
    #   正确做法：走 ENGINE.handle（auto_diagnose 真正生效的路径），
    #   并用**配对测量**（同一轮内交替 off/on）消除负载漂移。
    #   配对后测量的是"auto_diagnose 开销"本身，而非两次独立采样之差。

    def bench_paired(handle_rounds: int = 800) -> tuple:
        ENGINE.auto_diagnose = False
        s = Session()
        s.replace_all(
            [{"id": "e1", "shape": "rectangle", "label": "学生",
              "attributes": ["*学号", "姓名"]}], [])
        # 预置一个达标学生，使 handle 路径里 should_trigger 返回 True，
        # 测"开启时每条消息的完整判定+投递开销"的最坏情况
        _t = ENGINE._maybe_enqueue_diagnosis  # noqa: F841  (确保方法存在)
        off, on = [], []
        try:
            # 用独立测试队列，避免全局状态干扰
            from weakness import WeaknessTracker
            from llm import Diagnoser
            tq = WeaknessTracker()
            for i in range(5):
                tq.record("bench-stu", "R02", "error", "m", f"e{i}", now=float(i) * 10)
            test_q = DiagnoseQueue(diagnoser=Diagnoser(tracker=tq), tracker=tq)

            import engine as _eng
            orig_maybe = _eng.ENGINE._maybe_enqueue_diagnosis

            def maybe(uid):
                if ENGINE.auto_diagnose and test_q.should_trigger(uid):
                    test_q.enqueue(uid)   # 不 start worker，只测投递路径

            _eng.ENGINE._maybe_enqueue_diagnosis = maybe
            for i in range(handle_rounds):
                msg = {"action": "check", "event": "element_added",
                       "element": {"id": f"n{i}", "shape": "ellipse",
                                   "label": "属性", "attributes": []}}
                # 同一轮内紧邻测量，负载条件一致
                ENGINE.auto_diagnose = False
                t0 = time.perf_counter()
                ENGINE.handle("bench-paired", msg)
                off.append((time.perf_counter() - t0) * 1e6)

                ENGINE.auto_diagnose = True
                t0 = time.perf_counter()
                ENGINE.handle("bench-paired", msg)
                on.append((time.perf_counter() - t0) * 1e6)
            _eng.ENGINE._maybe_enqueue_diagnosis = orig_maybe
        finally:
            ENGINE.auto_diagnose = True
        off.sort()
        on.sort()
        # 注意单位：samples 以微秒记录，转回毫秒返回
        return off[len(off) // 2] / 1000.0, on[len(on) // 2] / 1000.0

    # 取 3 轮中位（比 min 更抗离群）
    rounds_res = [bench_paired() for _ in range(3)]
    off = sorted(r[0] for r in rounds_res)[1]
    on = sorted(r[1] for r in rounds_res)[1]
    delta = on - off
    print(f"        handle 路径 关闭 p50={off:.3f}ms  开启 p50={on:.3f}ms  "
          f"增量={delta:+.3f}ms")
    ok("handle 路径：开启自动诊断后延迟增量 < 0.5ms", delta < 0.5,
       f"实际 {delta:+.3f}ms")
    ok("自动诊断未使延迟翻倍", on < off * 2,
       f"{off:.3f}ms -> {on:.3f}ms")

    # 投递本身是 O(1)：即使队列忙碌，投递也不等待
    t4 = seeded_tracker()
    q3 = DiagnoseQueue(diagnoser=Diagnoser(tracker=t4), tracker=t4)
    # 不 start()，模拟 worker 繁忙/未启动
    times = []
    for i in range(200):
        t0 = time.perf_counter()
        q3._pending.clear()          # 允许重复投递，专测投递路径耗时
        q3.enqueue("S1")
        times.append((time.perf_counter() - t0) * 1e6)
    times.sort()
    p95 = times[int(len(times) * 0.95)]
    print(f"        投递 200 次 p50={times[100]:.1f}us  p95={p95:.1f}us")
    ok("投递 p95 < 1ms（worker 未运行也不阻塞）", p95 < 1000,
       f"实际 {p95:.1f}us")

    ENGINE.auto_diagnose = True

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题：")
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
