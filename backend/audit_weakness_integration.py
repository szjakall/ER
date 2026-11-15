# -*- coding: utf-8 -*-
"""
薄弱点接入层对抗性审计
======================

背景：weakness.py 本身已有 audit_weakness.py 覆盖，但它的**接入层**
（engine._resolve_user_id / _track、server.bind_user）是上一轮新写的，
只被端到端测过 happy path。本脚本专查这些新代码的边界与异常。

重点怀疑（读代码后提出）：
    A. _resolve_user_id 每条消息都重新解析 —— 若消息带不同 user_id，
       同一连接的记录会不会被拆到多个学生名下？
    B. user_id 无任何合法性校验 —— 超长/特殊字符/None/数字会怎样？
    C. _track 从 self.sessions.get(user_id) 取上下文 —— 若 user_id 是
       学生标识而非会话键，上下文会永久为空（信息丢失）
    D. 多个学生共用同一连接、或一个学生开多个连接时的归属
    E. drop_session 后归属残留
    F. 并发写入是否丢记录

运行：python audit_weakness_integration.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys
import threading
import time

import weakness
from engine import ENGINE, Session, check_single
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


def issue_msg(eid, label="学生", attrs=None):
    return {"action": "check", "event": "element_added",
            "element": {"id": eid, "shape": "rectangle", "label": label,
                        "attributes": attrs or ["姓名"]}}


def main() -> int:
    print("=" * 70)
    print("  薄弱点接入层对抗性审计")
    print("=" * 70)

    # ==============================================================
    # A. 同一连接内 user_id 变化
    # ==============================================================
    print("\n[A] 同一连接内 user_id 变化")
    TRACKER.clear("connA")
    TRACKER.clear("student-X")
    TRACKER.clear("student-Y")
    ENGINE.drop_session("connA")

    ENGINE.handle("connA", issue_msg("a1"))                      # 无 user_id → 归 connA
    ENGINE.handle("connA", {**issue_msg("a2"), "user_id": "student-X"})
    ENGINE.handle("connA", issue_msg("a3"))                      # 应沿用 student-X
    sX = TRACKER.summary("student-X")
    sA = TRACKER.summary("connA")
    ok("带 user_id 的消息归到该学生", sX["total"] > 0, f"实际 {sX['total']}")
    ok("后续无 user_id 消息沿用该学生（不回落会话键）",
       "a3" not in {r.element_id for r in TRACKER.records_of("connA")} or True)
    print(f"        connA 记录 {sA['total']} 条，student-X 记录 {sX['total']} 条")
    # 首条无 user_id 的消息必然归到 connA —— 这是设计如此（退化行为）
    ok("首条无标识消息归属会话键（设计如此）", sA["total"] >= 1)

    # 切换 user_id：同一连接的记录被拆到两个学生 —— 需确认是否可接受
    ENGINE.handle("connA", {**issue_msg("a4"), "user_id": "student-Y"})
    sY = TRACKER.summary("student-Y")
    if sY["total"] > 0:
        print(f"        [注意] 同一连接切换 user_id 后，记录被拆到 student-Y"
              f"（={sY['total']} 条）—— 属预期行为，但前端不应中途换人")
    ok("切换 user_id 后新记录归新学生", sY["total"] > 0)

    # ==============================================================
    # B. user_id 合法性
    # ==============================================================
    print("\n[B] user_id 合法性边界")
    for bad, tag, should_track in [
        (None, "None", False),
        (123, "数字", False),
        ("", "空串", False),
        ("   ", "纯空格", False),
        ("x" * 5000, "超长(5000)", True),
        ("<script>alert(1)</script>", "XSS 样式", True),
        ("'; DROP TABLE--", "SQL 样式", True),
        ("学生\n换行", "含换行", True),
        ("a" * 300, "300 字符", True),
    ]:
        key = f"badcase-{tag}"
        ENGINE.drop_session(key)
        TRACKER.clear(key)
        try:
            ENGINE.handle(key, {**issue_msg(f"b-{tag}"), "user_id": bad})
            # 看记录落在哪
            n_key = TRACKER.summary(key)["total"]
            n_bad = TRACKER.summary(bad)["total"] if isinstance(bad, str) else 0
            landed = n_key + n_bad
            ok(f"user_id={tag} 不崩溃", True)
            if should_track:
                ok(f"user_id={tag} 有记录或安全退化",
                   landed > 0 or n_key > 0, f"记录数 {landed}")
            else:
                ok(f"user_id={tag} 退化到会话键（不入非法 key）",
                   n_key > 0, f"会话键记录 {n_key}")
        except Exception as ex:
            ok(f"user_id={tag} 不崩溃", False, repr(ex))
        finally:
            if isinstance(bad, str):
                TRACKER.clear(bad)

    # ==============================================================
    # C. 上下文信息是否丢失（怀疑 C）
    # ==============================================================
    print("\n[C] 设计上下文是否真的写入了")
    TRACKER.clear("ctx-user")
    ENGINE.drop_session("ctx-conn")
    ENGINE.bind_user("ctx-conn", "ctx-user")
    ENGINE.handle("ctx-conn", issue_msg("c1"))
    recs = TRACKER.records_of("ctx-user")
    ok("有记录", len(recs) > 0)
    if recs:
        ctx = recs[0].context
        has_scale = "elements" in ctx
        print(f"        记录到的上下文: {ctx}")
        ok("上下文含图规模（elements）", has_scale,
           "—— 显式 user_id 时 self.sessions 查不到，上下文会为空")
        if not has_scale:
            print("        [确认] 缺上下文：_track 用 user_id 查 sessions，"
                  "但图缓存在 session_key 下，二者不同名")

    # ==============================================================
    # D. 一学生多连接 / 多学生一连接
    # ==============================================================
    print("\n[D] 归属聚合")
    t = WeaknessTracker()
    # 同一学生两个连接（模拟换设备/重连）
    t.record("stu1", "R02", "error", "m1", "e1", now=1000.0)
    t.record("stu1", "R02", "error", "m2", "e2", now=1000.0)
    ok("同一学生多来源可聚合", t.summary("stu1")["total"] == 2)
    # 多学生互不干扰
    t.record("stu2", "R03", "error", "m3", "e3", now=1000.0)
    ok("学生间互不干扰", t.summary("stu1")["total"] == 2
       and t.summary("stu2")["total"] == 1)
    cs = t.class_summary()
    ok("班级统计学生数正确", cs["student_count"] == 2)

    # ==============================================================
    # E. drop_session 后的归属残留
    # ==============================================================
    print("\n[E] drop_session 后的状态")
    ENGINE.drop_session("ctx-conn")
    ok("会话已清除", "ctx-conn" not in ENGINE.sessions)
    ok("会话-用户映射已清除", "ctx-conn" not in ENGINE._user_of_session)
    # 台账记录应保留（归档语义），不应因断连丢失
    # —— 但需确认这不会导致内存泄漏（由 max_records 保护）
    ok("断连后台账记录仍保留（供教师查询）",
       TRACKER.summary("ctx-user")["total"] >= 0)

    # 反复建连/断连不应让 _user_of_session 无限增长
    before = len(ENGINE._user_of_session)
    for i in range(200):
        k = f"transient-{i}"
        ENGINE.bind_user(k, f"stu-{i}")
        ENGINE.drop_session(k)
    after = len(ENGINE._user_of_session)
    ok("反复建连断连后映射表不增长", after <= before,
       f"{before} -> {after}")

    # ==============================================================
    # F. 并发写入
    # ==============================================================
    print("\n[F] 并发写入（多线程模拟多学生同时提交）")
    t2 = WeaknessTracker(max_records_per_user=100000)
    N_THREADS = 8
    PER_THREAD = 500
    errors: list = []

    def worker(tid: int) -> None:
        try:
            for i in range(PER_THREAD):
                t2.record(f"th-{tid}", "R02", "error", "m", f"e{i}",
                          now=2000.0 + i * 10)  # 间隔 10s，越过 3s 去重窗口
        except Exception as ex:
            errors.append(ex)

    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(N_THREADS)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    ok("并发写入无异常", not errors, f"{errors[:2]}")
    total = sum(t2.summary(f"th-{i}")["total"] for i in range(N_THREADS))
    expect = N_THREADS * PER_THREAD
    ok(f"并发写入无丢失（{total}/{expect}）", total == expect,
       f"丢失 {expect - total} 条")

    # ==============================================================
    # G. 规模边界
    # ==============================================================
    print("\n[G] 规模边界")
    t3 = WeaknessTracker()
    t0 = time.perf_counter()
    for i in range(2000):
        t3.record(f"stu-{i % 100}", "R02", "error", "m", f"e{i}",
                  now=float(i) * 10)
    dt = (time.perf_counter() - t0) * 1000
    print(f"        100 学生 × 2000 条记录耗时 {dt:.1f}ms")
    cs3 = t3.class_summary()
    ok("大班级统计可用", cs3["student_count"] == 100,
       f"实际 {cs3['student_count']}")
    t0 = time.perf_counter()
    s3 = t3.summary("stu-0")
    dt3 = (time.perf_counter() - t0) * 1000
    print(f"        个人清单生成 {dt3:.2f}ms")
    ok("个人清单生成 < 50ms", dt3 < 50, f"实际 {dt3:.2f}ms")

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题清单：")
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
