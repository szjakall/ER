# -*- coding: utf-8 -*-
"""
前端 ws.ts 契约适配验证
=======================

关键发现（读 frontend/src/protocol/ws.ts）：
    前端按 `element_id` 从 pending 槽位取回包：
        const slot = this.pending.get(msg.element_id);
        if (slot) { ...回调... }   // 取不到就**静默丢弃**
    且 pending 槽位是用**请求里的 id** 注册的。

    这意味着：后端回包的 element_id 必须与请求中的 id **逐字相同**，
    否则前端不报错、不提示，学生看到的就是"毫无反应"。
    这是最隐蔽的对接失败模式，必须实测。

另需验证：
    - 前端 2 秒超时（TIMEOUT_MS=2000），后端必须远快于它
    - 前端 batch 用固定键 "*batch*"，只认 action=batch_result
    - 前端对 error 只回调 onError，不阻塞画布

运行：ER_WS_PORT=8000 python audit_frontend_contract.py（需先启动服务）
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import sys

PORT = int(os.environ.get("ER_WS_PORT", "8000"))

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


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    uri = f"ws://127.0.0.1:{PORT}/ws"
    print("=" * 68)
    print("  前端 ws.ts 契约适配验证")
    print("=" * 68)

    try:
        ws = await websockets.connect(uri)
    except Exception as ex:
        print(f"  无法连接 {uri}：{ex}")
        return 1

    try:
        # ==========================================================
        # 1. element_id 必须原样回传（前端靠它匹配 pending 槽位）
        # ==========================================================
        print("\n[1] element_id 原样回传")
        ids = ["rect_001", "rect-002", "rect_003", "R_4", "元素_5",
               "a" * 64, "conn_001"]
        for eid in ids:
            ev = "connection_added" if eid.startswith("conn") else "element_added"
            msg = ({"action": "check", "event": ev,
                    "connection": {"id": eid, "from": "x", "to": "y",
                                   "type": "line", "label": "", "cardinality": None}}
                   if ev == "connection_added" else
                   {"action": "check", "event": ev,
                    "element": {"id": eid, "shape": "rectangle",
                                "label": "测试", "attributes": ["*a"]}})
            await ws.send(json.dumps(msg, ensure_ascii=False))
            resp = json.loads(await ws.recv())
            ok(f"element_id 原样回传 [{eid[:16]}]",
               resp.get("element_id") == eid,
               f"请求 {eid!r} → 回 {resp.get('element_id')!r}")

        # ==========================================================
        # 2. 事件类型必须原样支持（前端只会发这 5 种）
        # ==========================================================
        print("\n[2] 5 种前端事件全部被接受")
        events = [
            ("element_added", {"element": {"id": "ev1", "shape": "rectangle",
                                           "label": "A", "attributes": ["*a"]}}),
            ("element_modified", {"element": {"id": "ev2", "shape": "rectangle",
                                              "label": "B", "attributes": ["*b"]},
                                  "changes": {"label_changed": True,
                                              "attributes_changed": False}}),
            ("element_deleted", {"element": {"id": "ev3", "shape": "rectangle",
                                             "label": "C", "attributes": ["*c"]}}),
            ("connection_added", {"connection": {"id": "ev4", "from": "ev1",
                                                 "to": "ev2", "type": "line",
                                                 "label": "", "cardinality": None}}),
            ("connection_modified", {"connection": {"id": "ev5", "from": "ev1",
                                                    "to": "ev2", "type": "line",
                                                    "label": "", "cardinality": None}}),
        ]
        for ev, extra in events:
            msg = {"action": "check", "event": ev, **extra}
            await ws.send(json.dumps(msg, ensure_ascii=False))
            resp = json.loads(await ws.recv())
            ok(f"事件 {ev} → result（非 error）",
               resp.get("action") == "result",
               f"实际 {resp.get('action')}: {resp.get('message', '')}")

        # ==========================================================
        # 3. 回包字段必须满足前端 onResult 的读取方式
        # ==========================================================
        print("\n[3] 回包结构匹配前端读取方式")
        await ws.send(json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": "fr1", "shape": "rectangle", "label": "读者",
                        "attributes": ["读者ID", "电话"]}}, ensure_ascii=False))
        resp = json.loads(await ws.recv())
        ok("result.element_id 存在（前端 pending.get 需要）",
           "element_id" in resp)
        ok("result.violations 是数组（前端直接传给 onResult）",
           isinstance(resp.get("violations"), list))
        ok("result.suggestions 是数组", isinstance(resp.get("suggestions"), list))
        # 前端 highlight.ts 用 level 决定颜色：error→红 warn→橙
        levels = {i["level"] for i in resp["violations"]}
        ok("violations 的 level 均为前端认识的 'error'",
           levels <= {"error"}, f"实际 {levels}")
        levels2 = {i["level"] for i in resp["suggestions"]}
        ok("suggestions 的 level 均为前端认识的 'warn'",
           levels2 <= {"warn"}, f"实际 {levels2}")

        # ==========================================================
        # 4. batch_result 结构（前端用固定键 *batch*，只认 results）
        # ==========================================================
        print("\n[4] batch_result 结构")
        await ws.send(json.dumps({
            "action": "batch_check",
            "diagram": {"elements": [
                {"id": "b1", "shape": "rectangle", "label": "学生",
                 "attributes": ["*学号"]}],
                "connections": []}}, ensure_ascii=False))
        resp = json.loads(await ws.recv())
        ok("action == 'batch_result'", resp.get("action") == "batch_result")
        ok("含 results 字段（前端读 msg.results ?? {}）",
           isinstance(resp.get("results"), dict))
        for eid, v in resp["results"].items():
            ok(f"results[{eid}] 含 violations/suggestions",
               isinstance(v.get("violations"), list)
               and isinstance(v.get("suggestions"), list))

        # 批量里每个元素回包也必须带 element_id 语义上的正确归属
        # （前端按 results 的 key 贴到画布元素上）

        # ==========================================================
        # 5. 错误消息（前端 onError 只读 message/element_id）
        # ==========================================================
        print("\n[5] error 消息结构")
        await ws.send(json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": "bad1", "shape": "rectangle",
                        "attributes": "不是数组"}}, ensure_ascii=False))
        resp = json.loads(await ws.recv())
        ok("action == 'error'", resp.get("action") == "error")
        ok("含 message（前端 onError 读它）", bool(resp.get("message")))
        ok("含 element_id（前端 onError 第二参）", "element_id" in resp)

        # ==========================================================
        # 6. 延迟必须远小于前端 2 秒超时
        # ==========================================================
        print("\n[6] 延迟 vs 前端 2 秒超时")
        import time
        times = []
        for i in range(50):
            t0 = time.perf_counter()
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": f"t{i}", "shape": "rectangle",
                            "label": "计时", "attributes": ["*a"]}},
                ensure_ascii=False))
            await ws.recv()
            times.append((time.perf_counter() - t0) * 1000)
        s = sorted(times)
        mx = max(s)
        print(f"        50 次往返 max={mx:.1f}ms（前端超时 2000ms）")
        ok("最慢往返 < 2000ms 的前端超时", mx < 2000, f"实际 {mx:.1f}ms")
        ok("留出 10 倍余量（<200ms）", mx < 200, f"实际 {mx:.1f}ms")

        # ==========================================================
        # 7. 并发连续发送（前端不等待，可能积压多条）
        # ==========================================================
        print("\n[7] 连续快速发送（模拟拖拽中的高频事件）")
        payloads = [json.dumps({
            "action": "check", "event": "element_modified",
            "element": {"id": "rapid1", "shape": "rectangle",
                        "label": f"改{i}", "attributes": ["*a", "b"]},
            "changes": {"label_changed": True, "attributes_changed": False}},
            ensure_ascii=False) for i in range(100)]
        for p in payloads:
            await ws.send(p)
        got = 0
        for _ in range(100):
            r = json.loads(await ws.recv())
            if r.get("action") == "result":
                got += 1
        ok("100 条连续消息全部有回包", got == 100, f"实际 {got}")
    finally:
        await ws.close()

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
