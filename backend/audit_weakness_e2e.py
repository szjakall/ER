# -*- coding: utf-8 -*-
"""
薄弱点接口端到端验证
====================

流程：真实 WebSocket 发绘图消息 → 触发违规 → HTTP 查学情接口。

前置：先启动 server.py
运行：ER_WS_PORT=8000 python audit_weakness_e2e.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import sys
import urllib.request

PORT = int(os.environ.get("ER_WS_PORT", "8000"))
WS_URI = f"ws://127.0.0.1:{PORT}/ws"
HTTP = f"http://127.0.0.1:{PORT}"

_passed = 0
_failed = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {detail}")


def get(path: str) -> dict:
    with urllib.request.urlopen(HTTP + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    print("=" * 68)
    print("  薄弱点接口端到端验证")
    print("=" * 68)

    # 用一个独立会话键，避免污染其他测试
    sess = "e2e-weakness-student"
    try:
        urllib.request.urlopen(
            urllib.request.Request(HTTP + f"/weakness/{sess}", method="DELETE"),
            timeout=5).read()
    except Exception:
        pass

    # 真实场景：前端连接时用 ?user_id= 指定学生标识
    try:
        ws = await websockets.connect(f"{WS_URI}?user_id={sess}")
    except Exception as ex:
        print(f"  无法连接 {WS_URI}：{ex}")
        return 1

    try:
        # 制造若干违规：
        # 1) 实体缺主键（R02）
        for i in range(3):
            await ws.send(json.dumps({
                "action": "check", "event": "element_added",
                "element": {"id": f"w_e{i}", "shape": "rectangle",
                            "label": f"实体{i}", "attributes": ["姓名"]}},
                ensure_ascii=False))
            await ws.recv()
            await asyncio.sleep(3.1)  # 越过去重窗口，确保被计数

        # 2) 联系分支缺基数（R14）
        await ws.send(json.dumps({
            "action": "check", "event": "element_added",
            "element": {"id": "w_d1", "shape": "diamond", "label": "选修"}},
            ensure_ascii=False))
        await ws.recv()
        await asyncio.sleep(3.1)
        await ws.send(json.dumps({
            "action": "check", "event": "connection_added",
            "connection": {"id": "w_c1", "from": "w_e0", "to": "w_d1",
                           "type": "diamond_line", "label": "",
                           "cardinality": None}}, ensure_ascii=False))
        await ws.recv()
    finally:
        await ws.close()

    # ---- 查询个人清单 ----
    print("\n[1] GET /weakness/{user_id}")
    data = get(f"/weakness/{sess}")
    ok("返回 total", "total" in data)
    ok("有违规记录", data["total"] > 0, f"实际 {data['total']}")
    ok("含 error_count/warning_count",
       "error_count" in data and "warning_count" in data)
    ok("by_rule 非空", len(data.get("by_rule", [])) > 0)
    rules_hit = {x["rule_id"] for x in data.get("by_rule", [])}
    print(f"        命中规则: {sorted(rules_hit)}")
    ok("记录了 R02（实体缺主键）", "R02" in rules_hit, f"实际 {rules_hit}")
    ok("记录了 R14（联系缺基数）", "R14" in rules_hit, f"实际 {rules_hit}")
    ok("by_rule 项含 count/message/first_at/last_at",
       all({"count", "message", "first_at", "last_at"} <= set(x)
           for x in data["by_rule"]))
    ok("weak_points 已生成", isinstance(data.get("weak_points"), list))
    print(f"        薄弱点: "
          f"{[(w['rule_id'], w['count']) for w in data.get('weak_points', [])]}")

    # ---- 查询班级学情 ----
    print("\n[2] GET /weakness（班级学情）")
    cls = get("/weakness")
    ok("返回 student_count", "student_count" in cls)
    ok("student_count >= 1", cls["student_count"] >= 1)
    ok("含 common_issues", isinstance(cls.get("common_issues"), list))
    ok("common_issues 非空", len(cls["common_issues"]) > 0)
    top = cls["common_issues"][0]
    ok("共性问题含 rule_id/student_count/student_share",
       {"rule_id", "student_count", "student_share"} <= set(top))
    print(f"        共性问题首位: {top['rule_id']} "
          f"命中 {top['student_count']}/{cls['student_count']} 人 "
          f"({top['student_share']*100:.0f}%)")

    # ---- 清除 ----
    print("\n[3] DELETE /weakness/{user_id}")
    req = urllib.request.Request(HTTP + f"/weakness/{sess}", method="DELETE")
    with urllib.request.urlopen(req, timeout=5) as r:
        res = json.loads(r.read().decode("utf-8"))
    ok("清除返回 ok", res.get("ok") is True)
    after = get(f"/weakness/{sess}")
    ok("清除后 total 归零", after["total"] == 0, f"实际 {after['total']}")

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
