# -*- coding: utf-8 -*-
"""
并发与多会话隔离实测
====================

教学场景：一个班几十个学生同时画图。必须保证：
    1) 多连接并发不互相阻塞、不报错
    2) 会话隔离：A 的图不会污染 B 的校验结果
    3) 并发下延迟仍可接受

前置：先启动 server.py
运行：ER_WS_PORT=8000 python audit_concurrent.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import statistics
import sys

PORT = int(os.environ.get("ER_WS_PORT", "8000"))
URI = f"ws://127.0.0.1:{PORT}/ws"

_passed = 0
_failed = 0
_problems = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        _problems.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


async def student(ws, sid: str, n: int) -> list:
    """模拟一个学生连续画图，返回每次往返耗时（ms）。"""
    times = []
    # 每个学生用自己独有的元素名，便于验证隔离
    for i in range(n):
        payload = json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": f"{sid}_e{i}", "shape": "rectangle",
                        "label": f"{sid}的实体{i}", "attributes": ["学号"]}},
            ensure_ascii=False)
        import time
        t0 = time.perf_counter()
        await ws.send(payload)
        await ws.recv()
        times.append((time.perf_counter() - t0) * 1000)
    return times


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    print("=" * 68)
    print("  并发与多会话隔离实测")
    print("=" * 68)

    # ---------------- 1. 并发 20 个学生 ----------------
    print("\n[1] 20 个并发连接，每人画 15 笔")
    N_STUDENTS = 20
    N_OPS = 15
    try:
        conns = await asyncio.gather(*[websockets.connect(URI)
                                       for _ in range(N_STUDENTS)])
    except Exception as ex:
        print(f"  连接失败：{ex}")
        return 1

    try:
        results = await asyncio.gather(
            *[student(ws, f"s{i}", N_OPS) for i, ws in enumerate(conns)],
            return_exceptions=True)

        errs = [r for r in results if isinstance(r, Exception)]
        ok("20 并发连接全部正常完成", not errs,
           f"{len(errs)} 个异常: {errs[:2]}")

        alltimes = [t for r in results if not isinstance(r, Exception) for t in r]
        if alltimes:
            s = sorted(alltimes)
            p50 = s[len(s) // 2]
            p95 = s[int(len(s) * 0.95)]
            print(f"        总请求 {len(alltimes)} 次")
            print(f"        往返延迟 p50={p50:.1f}ms  p95={p95:.1f}ms  "
                  f"max={max(s):.1f}ms")
            ok("并发下 p95 < 100ms", p95 < 100, f"实际 {p95:.1f}ms")
    finally:
        for ws in conns:
            await ws.close()

    # ---------------- 2. 会话隔离 ----------------
    print("\n[2] 会话隔离：两个连接各自建图")
    async with websockets.connect(URI) as wa, websockets.connect(URI) as wb:
        # A 建一个缺主键的实体 → 应有 R02
        await wa.send(json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": "A_e1", "shape": "rectangle",
                        "label": "甲实体", "attributes": ["姓名"]}},
            ensure_ascii=False))
        ra = json.loads(await wa.recv())

        # B 建一个合规实体 → 不应受 A 影响
        await wb.send(json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": "B_e1", "shape": "rectangle",
                        "label": "乙实体", "attributes": ["*编号"]}},
            ensure_ascii=False))
        rb = json.loads(await wb.recv())

        ok("A 得到自己的结果", ra.get("element_id") == "A_e1")
        ok("B 得到自己的结果", rb.get("element_id") == "B_e1")
        ok("A 报了缺主键 R02",
           any(v["rule_id"] == "R02" for v in ra["violations"]),
           f"实际 {[v['rule_id'] for v in ra['violations']]}")
        ok("B 未受 A 污染（无 R02）",
           not any(v["rule_id"] == "R02" for v in rb["violations"]),
           f"实际 {[v['rule_id'] for v in rb['violations']]}")

        # B 做批量检查，只应看到自己的图
        await wb.send(json.dumps({
            "action": "batch_check",
            "diagram": {"elements": [
                {"id": "B_e1", "shape": "rectangle", "label": "乙实体",
                 "attributes": ["*编号"]}],
                "connections": []}}, ensure_ascii=False))
        rbb = json.loads(await wb.recv())
        ok("B 的批量结果只含自己的元素",
           set(rbb["results"]) == {"B_e1"}, f"实际 {set(rbb['results'])}")

    # ---------------- 3. 单连接高频（模拟快速拖拽） ----------------
    print("\n[3] 单连接高频连续消息（模拟快速拖拽）")
    async with websockets.connect(URI) as ws:
        times = []
        import time
        for i in range(300):
            t0 = time.perf_counter()
            await ws.send(json.dumps({
                "action": "check", "event": "element_modified",
                "element": {"id": "hot1", "shape": "rectangle",
                            "label": f"改名{i}", "attributes": ["*学号", "姓名"]},
                "changes": {"label_changed": True, "attributes_changed": False}},
                ensure_ascii=False))
            await ws.recv()
            times.append((time.perf_counter() - t0) * 1000)
        s = sorted(times)
        p95 = s[int(len(s) * 0.95)]
        print(f"        300 次连续修改 p50={s[len(s)//2]:.1f}ms  "
              f"p95={p95:.1f}ms  max={max(s):.1f}ms")
        ok("高频修改 p95 < 100ms", p95 < 100, f"实际 {p95:.1f}ms")

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
