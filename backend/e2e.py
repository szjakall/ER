# -*- coding: utf-8 -*-
"""
端到端验证：用前端真实消息格式打真实 WebSocket 服务
====================================================

验证目标（对应 g4/g5/g8）：
    1) 前端 encode.ts 产出的三种消息都能被正确响应
    2) 回包字段与 INTERFACE.md 完全一致
    3) violations(level=error) / suggestions(level=warn) 分流正确
    4) 前端 highlight.ts 能据此上色（error→红 warn→橙）

前置：先启动 server.py
运行：python e2e.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import sys

# 默认 8000（INTERFACE.md 约定）；若被占用可用环境变量覆盖
PORT = int(os.environ.get("ER_WS_PORT", "8000"))
URI = f"ws://127.0.0.1:{PORT}/ws"

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {detail}")


# 前端 encode.ts 的 cloneElement / cloneConnection 产物格式
def fe_element(eid, shape, label, attrs=None, is_weak=False, x=0, y=0):
    return {"id": eid, "shape": shape, "label": label,
            "attributes": attrs or [], "is_weak": is_weak,
            "position": {"x": x, "y": y}}


def fe_connection(cid, frm, to, ctype="line", label="", card=None):
    return {"id": cid, "from": frm, "to": to, "type": ctype,
            "label": label, "cardinality": card}


async def send(ws, obj):
    await ws.send(json.dumps(obj, ensure_ascii=False))
    return json.loads(await ws.recv())


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets 库")
        return 1

    print("=" * 66)
    print("  端到端验证（前端真实消息格式 → 真实 WebSocket 服务）")
    print("=" * 66)

    async with websockets.connect(URI) as ws:
        # ==============================================================
        # 场景 1：element_added，实体缺主键 → 期望红色 violations
        # ==============================================================
        print("\n[场景1] 新建实体「读者」，属性无 * 前缀")
        resp = await send(ws, {
            "action": "check", "event": "element_added",
            "element": fe_element("rect_001", "rectangle", "读者",
                                  ["读者ID", "姓名", "电话"], x=120, y=300),
        })
        check("action=result", resp.get("action") == "result")
        check("element_id 回传正确", resp.get("element_id") == "rect_001")
        check("有 violations 数组", isinstance(resp.get("violations"), list))
        check("有 suggestions 数组", isinstance(resp.get("suggestions"), list))
        vids = {v["rule_id"] for v in resp["violations"]}
        sids = {s["rule_id"] for s in resp["suggestions"]}
        check("命中缺主键规则 R02", "R02" in vids, f"实际 {vids}")
        check("命中多值属性建议 H03", "H03" in sids, f"实际 {sids}")
        check("violations 全 error 级（前端标红）",
              all(v["level"] == "error" for v in resp["violations"]))
        check("suggestions 全 warn 级（前端标橙）",
              all(s["level"] == "warn" for s in resp["suggestions"]))
        check("issue 字段严格为 rule_id/level/message",
              all(set(v) == {"rule_id", "level", "message"}
                  for v in resp["violations"] + resp["suggestions"]))
        for v in resp["violations"]:
            print(f"        红 [{v['rule_id']}] {v['message']}")
        for s in resp["suggestions"]:
            print(f"        橙 [{s['rule_id']}] {s['message']}")

        # ==============================================================
        # 场景 2：修正后 element_modified → 期望清空
        # ==============================================================
        print("\n[场景2] 给属性加 * 前缀（element_modified）")
        resp = await send(ws, {
            "action": "check", "event": "element_modified",
            "element": fe_element("rect_001", "rectangle", "读者",
                                  ["*读者ID", "姓名"], x=120, y=300),
            "changes": {"attributes_changed": True, "label_changed": False},
        })
        vids = {v["rule_id"] for v in resp["violations"]}
        check("补上主键后 R02 消失", "R02" not in vids, f"实际 {vids}")
        print(f"        violations={len(resp['violations'])} "
              f"suggestions={len(resp['suggestions'])}")

        # ==============================================================
        # 场景 3：connection_added，联系分支缺基数 → 期望红色
        # ==============================================================
        print("\n[场景3] 画一条联系分支线（菱形↔实体），无基数")
        await send(ws, {
            "action": "check", "event": "element_added",
            "element": fe_element("d_001", "diamond", "借阅"),
        })
        await send(ws, {
            "action": "check", "event": "element_added",
            "element": fe_element("rect_002", "rectangle", "图书",
                                  ["*图书ID", "书名"]),
        })
        resp = await send(ws, {
            "action": "check", "event": "connection_added",
            "connection": fe_connection("conn_001", "rect_001", "d_001",
                                        "diamond_line", "", None),
        })
        check("conn 回包 element_id 正确", resp.get("element_id") == "conn_001")
        vids = {v["rule_id"] for v in resp["violations"]}
        check("命中缺基数 R14", "R14" in vids, f"实际 {vids}")
        for v in resp["violations"]:
            print(f"        红 [{v['rule_id']}] {v['message']}")

        # ==============================================================
        # 场景 4：补上基数 → 期望 R14 消失
        # ==============================================================
        print("\n[场景4] 在线上写基数 N（connection_modified）")
        resp = await send(ws, {
            "action": "check", "event": "connection_modified",
            "connection": fe_connection("conn_001", "rect_001", "d_001",
                                        "diamond_line", "", "N"),
        })
        vids = {v["rule_id"] for v in resp["violations"]}
        check("补上基数后 R14 消失", "R14" not in vids, f"实际 {vids}")

        # ==============================================================
        # 场景 5：批量检查（导入已有设计）
        # ==============================================================
        print("\n[场景5] batch_check 整图体检")
        resp = await send(ws, {
            "action": "batch_check",
            "diagram": {
                "elements": [
                    fe_element("rect_001", "rectangle", "读者",
                               ["*读者ID", "姓名"]),
                    fe_element("rect_002", "rectangle", "图书",
                               ["*图书ID", "书名"]),
                    fe_element("d_001", "diamond", "借阅"),
                ],
                "connections": [
                    fe_connection("conn_001", "rect_001", "d_001",
                                  "diamond_line", "", "M"),
                    fe_connection("conn_002", "rect_002", "d_001",
                                  "diamond_line", "", "N"),
                ],
            },
        })
        check("action=batch_result", resp.get("action") == "batch_result")
        results = resp.get("results", {})
        check("results 覆盖全部 5 个元素/连线",
              set(results) == {"rect_001", "rect_002", "d_001",
                               "conn_001", "conn_002"},
              f"实际 {set(results)}")
        check("每条结果都含 violations+suggestions",
              all({"violations", "suggestions"} <= set(v)
                  for v in results.values()))
        total_v = sum(len(v["violations"]) for v in results.values())
        print(f"        整图 violations 合计 {total_v} 条")

        # ==============================================================
        # 场景 6：错误响应
        # ==============================================================
        print("\n[场景6] 畸形消息 → error 响应")
        resp = await send(ws, {
            "action": "check", "event": "element_added",
            "element": {"id": "bad_001", "shape": "rectangle",
                        "label": "坏", "attributes": "不是数组"},
        })
        check("attributes 非数组 → action=error", resp.get("action") == "error")
        check("error 带 element_id", resp.get("element_id") == "bad_001")
        check("error 带 message", bool(resp.get("message")))
        print(f"        {resp.get('message')}")

        # ==============================================================
        # 场景 7：字典树索引——element_deleted 也正确响应
        # ==============================================================
        print("\n[场景7] 删除元素（element_deleted）")
        resp = await send(ws, {
            "action": "check", "event": "element_deleted",
            "element": fe_element("rect_002", "rectangle", "图书",
                                  ["*图书ID"]),
        })
        check("删除事件返回 result", resp.get("action") == "result")

    print("\n" + "=" * 66)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    print("=" * 66)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
