# -*- coding: utf-8 -*-
"""
LLM 归因层端到端验证
====================

验证真实场景：
    1) 学生经 WebSocket 画图 → 触发规则校验 → 统计信号达标
    2) 后台异步生成诊断
    3) 诊断结果经 WebSocket 以 action="diagnosis" 非侵入式推送
    4) 全程不阻塞实时校验

前置：先启动 server.py
运行：ER_WS_PORT=8000 python audit_llm_e2e.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import sys
import time
import urllib.request

PORT = int(os.environ.get("ER_WS_PORT", "8000"))
WS_BASE = f"ws://127.0.0.1:{PORT}/ws"
HTTP = f"http://127.0.0.1:{PORT}"

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


def get(path: str) -> dict:
    with urllib.request.urlopen(HTTP + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    print("=" * 70)
    print("  LLM 归因层端到端验证")
    print("=" * 70)

    uid = "e2e-llm-student"
    # 清历史
    try:
        urllib.request.urlopen(
            urllib.request.Request(HTTP + f"/weakness/{uid}", method="DELETE"),
            timeout=5).read()
    except Exception:
        pass

    try:
        ws = await websockets.connect(f"{WS_BASE}?user_id={uid}")
    except Exception as ex:
        print(f"  无法连接：{ex}")
        return 1

    received_diagnosis = []
    other_actions = []

    def classify(raw: str) -> None:
        """把收到的消息分流：诊断推送 vs 其他。"""
        try:
            m = json.loads(raw)
        except Exception:
            return
        if m.get("action") == "diagnosis":
            received_diagnosis.append(m)
        else:
            other_actions.append(m.get("action"))

    try:
        # ==========================================================
        # 1. 模拟学生反复犯同一类错误（触发概念性归因）
        #
        # 注意（测试脚本自身的坑）：不能简单地"发一条 + recv 一条"。
        # 异步诊断推送会**穿插**在 result 之间到达；
        # 若每轮只 recv 一次并假定它是 result，诊断帧会被当成 result
        # 丢弃，导致"收不到诊断"的假失败。
        # 正确做法：边发边用"按 action 分流"的方式收。
        # ==========================================================
        print("\n[1] 学生连续画错（同一类错误重复出现）")
        received: list = []

        async def collector() -> None:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    return
                received.append(raw)
                classify(raw)

        ct = asyncio.create_task(collector())
        t_send0 = time.perf_counter()
        slowest = 0.0
        for i in range(6):
            t0 = time.perf_counter()
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": f"e{i}", "shape": "rectangle",
                            "label": f"实体{i}", "attributes": ["姓名"]}},
                ensure_ascii=False))
            await asyncio.sleep(0.35)
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)

        # 等待诊断（最多 10 秒）
        deadline = time.time() + 10
        while time.time() < deadline and not received_diagnosis:
            await asyncio.sleep(0.2)
        ct.cancel()
        print(f"        6 次校验完成，从发送到全部完成 "
              f"{(time.perf_counter()-t_send0):.1f}s")
        print(f"        共收到 {len(received)} 条消息，"
              f"其中 result {other_actions.count('result')} 条")

        # ==========================================================
        # 2. 异步诊断推送
        # ==========================================================
        print("\n[2] 异步诊断推送（非侵入式）")
        if received_diagnosis:
            d = received_diagnosis[0]
            ok("收到 action=diagnosis 推送", True)
            ok("推送带 user_id", d.get("user_id") == uid)
            data = d.get("data") or {}
            ok("诊断含 summary", bool(data.get("summary")))
            ok("诊断含 weak_points", isinstance(data.get("weak_points"), list))
            ok("诊断含 suggestions", isinstance(data.get("suggestions"), list))
            ok("诊断标注 source", data.get("source") in ("heuristic", "llm"))
            print(f"        来源: {data.get('source')}")
            print(f"        正文首行: {(data.get('summary') or '').splitlines()[0][:70]}")
            ok("诊断推送不混入 violations（非侵入式）",
               "violations" not in d and "suggestions" not in d,
               f"实际键 {sorted(d)}")
            print(f"        生成耗时: {data.get('meta', {}).get('elapsed_ms')}ms")
        else:
            ok("收到异步诊断推送", False, "10 秒内未收到")
        # 实时校验本身仍正常
        ok("期间实时校验正常返回 result",
           other_actions.count("result") >= 6,
           f"实际 {other_actions.count('result')} 条")
    finally:
        await ws.close()

    # ==========================================================
    # 3. HTTP 接口
    # ==========================================================
    print("\n[3] HTTP 诊断接口")
    try:
        rep = get(f"/diagnosis/{uid}")
        ok("GET /diagnosis/{user} 返回报告", bool(rep.get("summary")))
        ok("含 user_id", rep.get("user_id") == uid)
        ok("含薄弱点", isinstance(rep.get("weak_points"), list))
        print(f"        来源: {rep.get('source')}")

        cls = get("/diagnosis")
        ok("GET /diagnosis 返回班级摘要", "summary" in cls)
        ok("含教学建议字段", "teaching_advice" in cls)

        qs = get("/diagnosis/queue/stats")
        ok("队列状态接口可用", "running" in qs)
        if qs.get("running"):
            print(f"        队列: 已生成 {qs.get('generated')} 份, "
                  f"待处理 {qs.get('pending')}")
    except Exception as ex:
        ok("HTTP 接口调用", False, repr(ex))

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
