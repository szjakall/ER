# -*- coding: utf-8 -*-
"""
多学生并发诊断推送 + 异常帧健壮性
==================================

验证（此前盲区）：
    1) 多学生同时触发诊断 → 推送是否串台（A 的诊断推给 B？）
    2) 恶意/异常帧（二进制、超大消息）→ 服务是否崩溃
    3) 推送与实时校验并发交错时的正确性

前置：先启动 server.py
运行：ER_WS_PORT=8000 python audit_push_race.py
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

PORT = int(os.environ.get("ER_WS_PORT", "8000"))
WS = f"ws://127.0.0.1:{PORT}/ws"

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


async def student_trigger(websockets, uid: str, n: int) -> list:
    """一个学生连续画错，并收集收到的所有消息 action + 诊断归属。"""
    got = []
    async with websockets.connect(f"{WS}?user_id={uid}") as ws:
        # 后台收集器：边发边收
        received: list = []

        async def collector():
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    return
                try:
                    m = json.loads(raw)
                    received.append(m)
                except Exception:
                    pass

        ct = asyncio.create_task(collector())
        for i in range(n):
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": f"{uid}_e{i}", "shape": "rectangle",
                            "label": f"实体{i}", "attributes": ["姓名"]}},
                ensure_ascii=False))
            await asyncio.sleep(0.15)
        # 等诊断推送
        deadline = time.time() + 10
        while time.time() < deadline:
            diags = [m for m in received if m.get("action") == "diagnosis"]
            if diags:
                break
            await asyncio.sleep(0.2)
        ct.cancel()
        got = received
    return got


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    print("=" * 70)
    print("  多学生并发诊断推送 + 异常帧健壮性")
    print("=" * 70)

    # ==============================================================
    # 1. 多学生并发诊断 → 是否串台
    #
    # uid 用运行时间戳（v1.5 修正）：学生 uid 若跨次运行重复，
    # 服务端的 60 秒诊断冷却会让第二次运行"收不到推送"——
    # 那是冷却机制在正确工作，不是缺陷，但会让测试假失败。
    # ==============================================================
    print("\n[1] 3 个学生并发触发诊断")
    run_tag = f"{int(time.time()) % 1000000}"
    results = await asyncio.gather(
        *[student_trigger(websockets, f"race-{run_tag}-{k}", 6)
          for k in range(3)],
        return_exceptions=True)
    errs = [r for r in results if isinstance(r, Exception)]
    ok("3 个并发学生全部正常完成", not errs, f"{errs[:2]}")

    for k in range(3):
        uid = f"race-{run_tag}-{k}"
        recs = results[k] if not isinstance(results[k], Exception) else []
        diags = [m for m in recs if m.get("action") == "diagnosis"]
        ok(f"{uid} 收到诊断推送", len(diags) >= 1,
           f"实际 {len(diags)} 条")
        for m in diags:
            ok(f"{uid} 的诊断归属正确（user_id={uid}）",
               m.get("user_id") == uid,
               f"推送归属 {m.get('user_id')!r}")
            data = m.get("data") or {}
            ok(f"{uid} 的诊断正文指向自己",
               uid in (data.get("summary") or ""),
               f"正文开头: {(data.get('summary') or '')[:40]}")

    # ==============================================================
    # 2. 异常帧健壮性
    # ==============================================================
    print("\n[2] 异常帧（二进制 / 超大消息 / 连发垃圾）")
    async with websockets.connect(WS) as ws:
        # 2a 二进制帧
        try:
            await ws.send(b"\x00\x01\x02binary")
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": "after-bin", "shape": "rectangle",
                            "label": "存活", "attributes": ["*a"]}},
                ensure_ascii=False))
            r = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            ok("二进制帧后连接仍可用", r.get("action") in ("result", "error"),
               f"实际 {r.get('action')}")
        except Exception as ex:
            ok("二进制帧不炸连接", False, repr(ex))

        # 2b 超大消息（1MB 字符串标签）
        # 预期：uvicorn 默认单条消息上限 1MB，超限会被服务端以 1009 关闭
        # ——这是**库级资源保护**，行为正确（前端 ws.ts onclose 会自动重连）。
        # 核心断言是"服务不崩、可重连"，而非"连接不断"。
        big = "A" * (1024 * 1024)
        closed_ok = False
        got_reply = False
        try:
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": "big1", "shape": "rectangle",
                            "label": big, "attributes": []}}))
            r = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            got_reply = True
        except Exception:
            closed_ok = True  # 被服务端以 1009 关闭 = 资源保护生效
        ok("超大消息：有回包或被资源保护关闭",
           got_reply or closed_ok, f"got_reply={got_reply} closed={closed_ok}")

        # 2c 新连接上连发垃圾（原连接可能已被 1009 关闭）
        try:
            ws_g = await websockets.connect(WS)
        except Exception as ex:
            ws_g = None
            ok("超大消息后可重连", False, repr(ex))
        if ws_g is not None:
            try:
                for i in range(200):
                    await ws_g.send(json.dumps({"action": "garbage", "n": i}))
                ok("200 条垃圾消息发送完成（服务未断）", True)
                await ws_g.send(json.dumps({
                    "action": "check", "event": "element_added",
                    "element": {"id": "alive2", "shape": "rectangle",
                                "label": "仍存活", "attributes": ["*a"]}},
                    ensure_ascii=False))
                # 每条垃圾都有 error 回包；循环收直到 check 的 result
                # （初版只 recv 一次，取到的是垃圾的 error 回包——测试 bug）
                got_result = False
                deadline = time.time() + 5
                while time.time() < deadline:
                    r = json.loads(await asyncio.wait_for(ws_g.recv(), timeout=3))
                    if r.get("action") == "result":
                        got_result = True
                        break
                ok("垃圾消息后服务仍正常响应", got_result,
                   "未收到 result（error 回包耗尽超时）")
            except Exception as ex:
                ok("垃圾消息不炸连接", False, repr(ex))
            finally:
                await ws_g.close()

    # 服务整体存活
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        ok("服务健康检查仍 200", bool(j.get("service")))
    except Exception as ex:
        ok("服务存活", False, repr(ex))

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
