# -*- coding: utf-8 -*-
"""
延迟基准测试
============

目的：用**实测数据**回答"反馈是否 <100ms"，而不是靠断言。

测量两条路径：
    A. 引擎纯计算（engine.handle）—— 规则判定本身的开销
    B. 端到端 WebSocket（真实 ws 连接 + 序列化 + 网络回环）
       —— 这才是前端实际感知的延迟

结论口径：
    - 单笔绘图操作（element_added / connection_added）的 p95 必须 < 100ms
    - batch_check（整图体检）单独统计，不混入单笔延迟指标

运行： python bench.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import statistics
import time
from typing import Callable, Dict, List

from engine import ENGINE, Session, check_batch, check_single, select_rules
from rules import RULE_IDS


def pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
    return sorted_vals[k]


def report(name: str, samples_us: List[float], budget_ms: float = 100.0) -> Dict:
    s = sorted(samples_us)
    ms = [v / 1000.0 for v in s]
    stats = {
        "name": name,
        "count": len(ms),
        "min_ms": min(ms),
        "p50_ms": pct(ms, 0.50),
        "p95_ms": pct(ms, 0.95),
        "p99_ms": pct(ms, 0.99),
        "max_ms": max(ms),
        "mean_ms": statistics.fmean(ms),
        "budget_ms": budget_ms,
        "pass": pct(ms, 0.95) < budget_ms,
    }
    flag = "PASS" if stats["pass"] else "FAIL"
    print(f"  [{flag}] {name}")
    print(f"         n={stats['count']}  "
          f"p50={stats['p50_ms']:.2f}ms  p95={stats['p95_ms']:.2f}ms  "
          f"p99={stats['p99_ms']:.2f}ms  max={stats['max_ms']:.2f}ms  "
          f"(预算 {budget_ms:.0f}ms)")
    return stats


# ----------------------------------------------------------------------
# 构造一个中等规模的图（贴近真实课堂作业：6 实体 + 5 联系）
# ----------------------------------------------------------------------

def build_diagram():
    elements = [
        {"id": "e1", "shape": "rectangle", "label": "学生",
         "attributes": ["*学号", "姓名", "性别", "出生日期"]},
        {"id": "e2", "shape": "rectangle", "label": "课程",
         "attributes": ["*课程号", "课程名", "学分"]},
        {"id": "e3", "shape": "rectangle", "label": "教师",
         "attributes": ["*工号", "姓名", "职称"]},
        {"id": "e4", "shape": "rectangle", "label": "班级",
         "attributes": ["*班级号", "班级名"]},
        {"id": "e5", "shape": "rectangle", "label": "院系",
         "attributes": ["*院系号", "院系名"]},
        {"id": "e6", "shape": "rectangle", "label": "借阅记录",
         "attributes": ["#流水号", "借出日期", "归还日期"]},
        {"id": "d1", "shape": "diamond", "label": "选修"},
        {"id": "d2", "shape": "diamond", "label": "授课"},
        {"id": "d3", "shape": "diamond", "label": "属于"},
        {"id": "d4", "shape": "diamond", "label": "归入"},
    ]
    connections = [
        {"id": "c1", "from": "e1", "to": "d1", "type": "diamond_line",
         "label": "", "cardinality": "M"},
        {"id": "c2", "from": "e2", "to": "d1", "type": "diamond_line",
         "label": "", "cardinality": "N"},
        {"id": "c3", "from": "e3", "to": "d2", "type": "diamond_line",
         "label": "", "cardinality": "1"},
        {"id": "c4", "from": "e2", "to": "d2", "type": "diamond_line",
         "label": "", "cardinality": "N"},
        {"id": "c5", "from": "e1", "to": "d3", "type": "diamond_line",
         "label": "", "cardinality": "N"},
        {"id": "c6", "from": "e4", "to": "d3", "type": "diamond_line",
         "label": "", "cardinality": "1"},
        {"id": "c7", "from": "e4", "to": "d4", "type": "diamond_line",
         "label": "", "cardinality": "N"},
        {"id": "c8", "from": "e5", "to": "d4", "type": "diamond_line",
         "label": "", "cardinality": "1"},
    ]
    return elements, connections


# ----------------------------------------------------------------------
# A. 引擎纯计算
# ----------------------------------------------------------------------

def bench_inprocess(rounds: int = 2000) -> List[Dict]:
    print("\n[A] 引擎纯计算（无网络）")
    results = []
    elements, connections = build_diagram()

    # --- element_added ---
    samples = []
    for i in range(rounds):
        s = Session()
        # 预置全图，使通配规则也参与（最坏情况）
        s.replace_all(elements, connections)
        msg = {"action": "check", "event": "element_added",
               "element": {"id": f"new{i}", "shape": "ellipse", "label": "属性",
                           "attributes": []}}
        t0 = time.perf_counter()
        check_single(s, msg)
        samples.append((time.perf_counter() - t0) * 1e6)
    results.append(report("element_added（含全图 15 条通配规则）", samples))

    # --- connection_added ---
    samples = []
    for i in range(rounds):
        s = Session()
        s.replace_all(elements, connections)
        msg = {"action": "check", "event": "connection_added",
               "connection": {"id": f"nc{i}", "from": "e1", "to": "d1",
                              "type": "diamond_line", "label": "",
                              "cardinality": "1"}}
        t0 = time.perf_counter()
        check_single(s, msg)
        samples.append((time.perf_counter() - t0) * 1e6)
    results.append(report("connection_added（含全图通配规则）", samples))

    # --- element_deleted ---
    samples = []
    for i in range(rounds):
        s = Session()
        s.replace_all(elements, connections)
        msg = {"action": "check", "event": "element_deleted",
               "element": {"id": "e1", "shape": "rectangle", "label": "学生",
                           "attributes": ["*学号"]}}
        t0 = time.perf_counter()
        check_single(s, msg)
        samples.append((time.perf_counter() - t0) * 1e6)
    results.append(report("element_deleted", samples))

    # --- batch_check（整图体检，单独口径）---
    samples = []
    for i in range(max(200, rounds // 10)):
        s = Session()
        msg = {"action": "batch_check",
               "diagram": {"elements": elements, "connections": connections}}
        t0 = time.perf_counter()
        check_batch(s, msg)
        samples.append((time.perf_counter() - t0) * 1e6)
    results.append(report("batch_check（整图 14 元素，口径独立）", samples,
                          budget_ms=100.0))

    return results


# ----------------------------------------------------------------------
# B. 全量 vs 子集（证明"非全量扫描"的价值）
# ----------------------------------------------------------------------

def bench_subset_vs_full(rounds: int = 2000) -> None:
    print("\n[B] 全量扫描 vs 字典树子集（证明索引有效）")
    elements, connections = build_diagram()

    total = len(RULE_IDS)
    n_added = len(select_rules("element_added", has_full_graph=True, graph_dirty=True))
    n_conn = len(select_rules("connection_added", has_full_graph=True, graph_dirty=True))
    n_clean = len(select_rules("element_added", has_full_graph=True, graph_dirty=False))
    n_local = len(select_rules("element_added", has_full_graph=False))
    print(f"        规则总数 {total}")
    print(f"        element_added  图有变化 → {n_added} 条（{n_added/total*100:.0f}%）")
    print(f"        element_added  图未变化 → {n_clean} 条（{n_clean/total*100:.0f}%）")
    print(f"        element_added  无全图   → {n_local} 条（{n_local/total*100:.0f}%）")
    print(f"        connection_added 有变化 → {n_conn} 条（{n_conn/total*100:.0f}%）")

    # 全量：模拟"不做索引，每次都跑全部 44 条"
    from engine import run_rules
    from model import Diagram
    from rules import RuleContext

    s = Session()
    s.replace_all(elements, connections)
    diagram = s.to_diagram()

    def run_all_forced():
        ctx = RuleContext(diagram=diagram)
        import rules as R
        for rid, fn, _ in R.RULE_SPECS:
            try:
                fn(ctx)
            except Exception:
                pass

    samples_full, samples_sub, samples_clean = [], [], []
    for _ in range(rounds):
        t0 = time.perf_counter()
        run_all_forced()
        samples_full.append((time.perf_counter() - t0) * 1e6)

        t0 = time.perf_counter()
        run_rules(diagram, event="element_added", has_full_graph=True,
                  graph_dirty=True)
        samples_sub.append((time.perf_counter() - t0) * 1e6)

        t0 = time.perf_counter()
        run_rules(diagram, event="element_added", has_full_graph=True,
                  graph_dirty=False)
        samples_clean.append((time.perf_counter() - t0) * 1e6)

    report("强制全量跑 44 条", samples_full)
    report("字典树子集（图有变化）", samples_sub)
    report("字典树子集（图未变化，纯文本编辑）", samples_clean)

    f = statistics.fmean(samples_full) / 1000
    b = statistics.fmean(samples_sub) / 1000
    c = statistics.fmean(samples_clean) / 1000
    print(f"        图有变化时加速比：{f/b:.2f}x（{f:.3f}ms → {b:.3f}ms）")
    print(f"        图未变化时加速比：{f/c:.2f}x（{f:.3f}ms → {c:.3f}ms）")


# ----------------------------------------------------------------------
# C. 端到端 WebSocket（真实网络往返）
# ----------------------------------------------------------------------

async def bench_ws(rounds: int = 500) -> List[Dict]:
    print("\n[C] 端到端 WebSocket（真实 ws 回环，前端实际感知延迟）")
    try:
        import websockets
    except ImportError:
        print("        [SKIP] 未安装 websockets")
        return []

    import json as _json
    import os as _os

    # 若已有服务在目标端口上运行（如 ws://localhost:8000/ws），直接压测它；
    # 否则自起一个临时服务。这样基准测的就是真实部署的那条链路。
    external = _os.environ.get("ER_BENCH_EXTERNAL") == "1"
    port = int(_os.environ.get("ER_WS_PORT", "8123"))
    uri = f"ws://127.0.0.1:{port}/ws"

    srv = task = None
    if external:
        print(f"        压测已运行的服务：{uri}")
    else:
        import server
        import uvicorn

        config = uvicorn.Config(server.app, host="127.0.0.1", port=port,
                                log_level="error")
        srv = uvicorn.Server(config)
        task = asyncio.create_task(srv.serve())
        await asyncio.sleep(1.2)

    results = []
    try:
        uri = f"ws://127.0.0.1:{port}/ws"
        async with websockets.connect(uri) as ws:
            # 预热
            for _ in range(20):
                await ws.send(json.dumps({
                    "action": "check", "event": "element_added",
                    "element": {"id": "warm", "shape": "rectangle",
                                "label": "预热", "attributes": ["*id"]}},
                    ensure_ascii=False))
                await ws.recv()

            # 单元素事件
            samples = []
            for i in range(rounds):
                payload = json.dumps({
                    "action": "check", "event": "element_added",
                    "element": {"id": f"e{i}", "shape": "rectangle",
                                "label": f"实体{i}",
                                "attributes": ["*id", "名称"]}},
                    ensure_ascii=False)
                t0 = time.perf_counter()
                await ws.send(payload)
                await ws.recv()
                samples.append((time.perf_counter() - t0) * 1e6)
            results.append(report("WS element_added 往返", samples))

            # 连线事件
            samples = []
            for i in range(rounds):
                payload = json.dumps({
                    "action": "check", "event": "connection_added",
                    "connection": {"id": f"c{i}", "from": "e0", "to": "e1",
                                   "type": "diamond_line", "label": "",
                                   "cardinality": "1"}},
                    ensure_ascii=False)
                t0 = time.perf_counter()
                await ws.send(payload)
                await ws.recv()
                samples.append((time.perf_counter() - t0) * 1e6)
            results.append(report("WS connection_added 往返", samples))

            # 批量
            elements, connections = build_diagram()
            samples = []
            for _ in range(max(100, rounds // 5)):
                payload = json.dumps({
                    "action": "batch_check",
                    "diagram": {"elements": elements,
                                "connections": connections}},
                    ensure_ascii=False)
                t0 = time.perf_counter()
                await ws.send(payload)
                await ws.recv()
                samples.append((time.perf_counter() - t0) * 1e6)
            results.append(report("WS batch_check 往返（整图体检）", samples))
    finally:
        if srv is not None and task is not None:
            srv.should_exit = True
            await task

    return results


# ----------------------------------------------------------------------

def main() -> int:
    print("=" * 68)
    print(f"  ER 规则引擎延迟基准（{len(RULE_IDS)} 条规则，预算 <100ms）")
    print("=" * 68)

    a = bench_inprocess()
    bench_subset_vs_full()
    c = asyncio.run(bench_ws())

    allr = a + c
    print("\n" + "=" * 68)
    single = [r for r in allr if "batch_check" not in r["name"]]
    if all(r["pass"] for r in single):
        print("  结论：单笔绘图操作全部满足 <100ms 预算")
    else:
        bad = [r["name"] for r in single if not r["pass"]]
        print(f"  结论：存在超标项：{bad}")
    print("=" * 68)
    return 0 if all(r["pass"] for r in single) else 1


if __name__ == "__main__":
    raise SystemExit(main())
