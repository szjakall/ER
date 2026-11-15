# -*- coding: utf-8 -*-
"""
真实学生操作流程走查
====================

此前的测试都是「直接构造单条消息」。本脚本改为模拟**学生的真实操作序列**，
按前端 store.ts 的实际调用顺序发消息，并复现前端的消费逻辑来判断可用性。

关键发现（读 frontend/src/model/store.ts 后）：
    1. applyResult 第 232 行：
           if (!this.findElement(id) && !this.findConnection(id)) return;
       前端会**丢弃本地模型里不存在的 id 的结果**。
       所以回包的 element_id / results 的 key 必须在本地存在，
       多回、错回都会导致提示不显示（且无任何报错）。

    2. ws.ts onOpen → store.onOpen → batchCheck()：
       前端**每次连接（含断线重连）都会自动发一次 batch_check**。
       因此 batch_check 必须能正确处理"带完整图"的请求。

    3. store.normIssues 第 61 行：
           level: (o.level === "warn" ? "warn" : "error")
       前端只认 "warn"，**其余一律当 error（红色）**。
       若后端错发 level，会被静默标红。

    4. markPending 先清空再等结果：若后端不回，该元素永远停在 pending 态。

本脚本用真实 WS 复现完整流程，并按前端的消费规则校验。
前置：先启动 server.py
运行：ER_WS_PORT=8000 python audit_student_flow.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import asyncio
import json
import os
import sys
from typing import Dict

PORT = int(os.environ.get("ER_WS_PORT", "8000"))
URI = f"ws://127.0.0.1:{PORT}/ws"

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


class FakeFrontend:
    """
    复现前端 store.ts 的模型与消费逻辑，用于判断后端回包是否真能被消费。
    """

    def __init__(self) -> None:
        self.elements: Dict[str, dict] = {}
        self.connections: Dict[str, dict] = {}
        self.results: Dict[str, dict] = {}
        self.painted: Dict[str, bool] = {}
        self.discarded: list = []   # 被前端丢弃的结果（id 不在本地）

    # --- 模拟 store 的本地模型 ---
    def add_element(self, eid, shape, label, attrs=None, weak=False):
        el = {"id": eid, "shape": shape, "label": label,
              "attributes": attrs or [], "is_weak": weak}
        self.elements[eid] = el
        return el

    def add_connection(self, cid, frm, to, ctype="line", label="", card=None):
        c = {"id": cid, "from": frm, "to": to, "type": ctype,
             "label": label, "cardinality": card}
        self.connections[cid] = c
        return c

    def find(self, eid: str) -> bool:
        return eid in self.elements or eid in self.connections

    # --- 复现 store.applyResult 的丢弃逻辑 ---
    def apply_result(self, eid: str, payload: dict) -> bool:
        if not self.find(eid):
            self.discarded.append((eid, payload))
            return False
        self.results[eid] = payload
        self.painted[eid] = True
        return True

    def mark_pending(self, eid: str) -> None:
        self.painted[eid] = False
        self.results[eid] = {"violations": [], "suggestions": []}

    def pending_ids(self) -> list:
        return [k for k, v in self.painted.items() if not v]

    # --- 复现 normIssues 的 level 归一 ---
    @staticmethod
    def norm_level(raw) -> str:
        # 前端原逻辑：o.level === "warn" ? "warn" : "error"
        return "warn" if raw == "warn" else "error"

    def rendered_color(self, eid: str) -> str:
        """按 highlight.ts：有 error→红，否则有 warn→橙，否则绿。"""
        r = self.results.get(eid) or {"violations": [], "suggestions": []}
        if r.get("violations"):
            return "red"
        if r.get("suggestions"):
            return "orange"
        return "green"


from typing import Dict  # noqa: E402


def encode_element_added(el): return {"action": "check", "event": "element_added", "element": el}
def encode_element_modified(el, changes=None):
    return {"action": "check", "event": "element_modified", "element": el,
            "changes": changes or {"attributes_changed": False, "label_changed": False}}
def encode_element_deleted(el): return {"action": "check", "event": "element_deleted", "element": el}
def encode_connection_added(c): return {"action": "check", "event": "connection_added", "connection": c}
def encode_connection_modified(c): return {"action": "check", "event": "connection_modified", "connection": c}


async def send(ws, msg):
    await ws.send(json.dumps(msg, ensure_ascii=False))
    return json.loads(await ws.recv())


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("需要 websockets")
        return 1

    print("=" * 70)
    print("  真实学生操作流程走查（按前端 store.ts 的调用顺序）")
    print("=" * 70)

    try:
        ws = await websockets.connect(URI)
    except Exception as ex:
        print(f"  无法连接 {URI}：{ex}")
        return 1

    fe = FakeFrontend()
    try:
        # ==========================================================
        # 流程 1：学生从零开始画一张 ER 图
        # ==========================================================
        print("\n[1] 从零画图：新实体 → 加属性 → 画联系 → 标基数")

        # 1a 新建实体「读者」（前端 addElement 会立刻发 element_added）
        el = fe.add_element("rect_001", "rectangle", "读者", ["读者ID", "姓名"])
        fe.mark_pending("rect_001")
        resp = await send(ws, encode_element_added(el))
        ok("element_added 有回包", resp.get("action") == "result")
        applied = fe.apply_result(resp.get("element_id"), resp)
        ok("回包 id 能匹配前端本地元素（不被丢弃）", applied,
           f"element_id={resp.get('element_id')!r}")
        color = fe.rendered_color("rect_001")
        ok("缺主键 → 前端显示红色", color == "red", f"实际 {color}")
        print(f"        颜色={color} violations={[v['rule_id'] for v in resp['violations']]}")

        # 1b 学生补上主键（拖拽/编辑都会触发 modified）
        el2 = fe.add_element("rect_001", "rectangle", "读者", ["*读者ID", "姓名"])
        fe.mark_pending("rect_001")
        resp = await send(ws, encode_element_modified(
            el2, {"attributes_changed": True, "label_changed": False}))
        fe.apply_result(resp.get("element_id"), resp)
        color = fe.rendered_color("rect_001")
        ok("补主键后不再是红", color in ("orange", "green"), f"实际 {color}")

        # 1c 新建第二个实体 + 联系菱形
        el3 = fe.add_element("rect_002", "rectangle", "图书", ["*图书ID", "书名"])
        fe.mark_pending("rect_002")
        resp = await send(ws, encode_element_added(el3))
        fe.apply_result(resp.get("element_id"), resp)

        dia = fe.add_element("dia_001", "diamond", "借阅")
        fe.mark_pending("dia_001")
        resp = await send(ws, encode_element_added(dia))
        fe.apply_result(resp.get("element_id"), resp)
        ok("联系菱形被接受", resp.get("action") == "result")

        # 1d 画联系分支线（先不标基数）
        c1 = fe.add_connection("conn_001", "rect_001", "dia_001",
                               "diamond_line", "", None)
        fe.mark_pending("conn_001")
        resp = await send(ws, encode_connection_added(c1))
        applied = fe.apply_result(resp.get("element_id"), resp)
        ok("连线回包 id 能匹配", applied,
           f"element_id={resp.get('element_id')!r}")
        vids = {v["rule_id"] for v in resp["violations"]}
        ok("缺基数 → 红色提示", "R14" in vids, f"实际 {vids}")
        print(f"        颜色={fe.rendered_color('conn_001')} "
              f"violations={sorted(vids)}")

        # 1e 学生在线上写基数 N
        c1b = fe.add_connection("conn_001", "rect_001", "dia_001",
                                "diamond_line", "", "N")
        fe.mark_pending("conn_001")
        resp = await send(ws, encode_connection_modified(c1b))
        fe.apply_result(resp.get("element_id"), resp)
        vids = {v["rule_id"] for v in resp["violations"]}
        ok("补基数后 R14 消失", "R14" not in vids, f"实际 {vids}")

        # ==========================================================
        # 流程 2：断线重连 → 前端自动 batch_check
        # ==========================================================
        print("\n[2] 断线重连（前端 onOpen 会自动 batch_check）")
    finally:
        await ws.close()

    # 新连接 = 重连
    ws2 = await websockets.connect(URI)
    try:
        payload = {
            "action": "batch_check",
            "diagram": {
                "elements": list(fe.elements.values()),
                "connections": list(fe.connections.values()),
            },
        }
        resp = await send(ws2, payload)
        ok("重连后 batch_check 有回包", resp.get("action") == "batch_result")
        results = resp.get("results") or {}

        # 前端会遍历 results 逐个 applyResult —— 多出的 id 会被丢弃
        local_ids = set(fe.elements) | set(fe.connections)
        extra = set(results) - local_ids
        ok("batch results 不含前端未知的 id（否则被丢弃）", not extra,
           f"多余 {extra}")
        missing = local_ids - set(results)
        ok("batch results 覆盖全部本地元素（否则停在 pending）",
           not missing, f"缺失 {missing}")

        # 逐个应用，检查是否都能被消费
        discarded = 0
        for eid, body in results.items():
            if not fe.apply_result(eid, body):
                discarded += 1
        ok("所有 batch 结果都能被前端消费", discarded == 0,
           f"{discarded} 条被丢弃")

        # 检查是否还有元素停在 pending
        still_pending = fe.pending_ids()
        ok("无元素卡在 pending 态", not still_pending, f"{still_pending}")

        # ==========================================================
        # 流程 3：level 归一化风险
        # ==========================================================
        print("\n[3] level 字段归一化（前端只认 'warn'，其余当红色）")
        all_levels = set()
        for body in results.values():
            for it in body.get("violations", []) + body.get("suggestions", []):
                all_levels.add(it.get("level"))
        ok("后端只使用 'error'/'warn' 两种 level", all_levels <= {"error", "warn"},
           f"实际出现 {all_levels}")
        # 模拟前端归一：warn 之外都会被标红
        miscolored = []
        for body in results.values():
            for it in body.get("suggestions", []):
                if FakeFrontend.norm_level(it.get("level")) != "warn":
                    miscolored.append(it)
        ok("所有 suggestions 在归一后仍是 warn（不会被误标红）", not miscolored,
           f"{len(miscolored)} 条会被误标红")

        # ==========================================================
        # 流程 4：删除元素（前端会发 element_deleted）
        # ==========================================================
        print("\n[4] 删除元素")
        removed = fe.elements.pop("dia_001")
        fe.connections = {k: v for k, v in fe.connections.items()
                          if v["from"] != "dia_001" and v["to"] != "dia_001"}
        fe.mark_pending("dia_001")
        resp = await send(ws2, encode_element_deleted(removed))
        ok("element_deleted 有回包", resp.get("action") == "result")
        ok("回包 id 正确", resp.get("element_id") == "dia_001")
        # 前端消费删除事件的回包；但该元素已从本地模型移除，
        # applyResult 会因 findElement 失败而丢弃 —— 这是**前端预期行为**
        # （元素都没了，不需要再上色）。此处显式记录，不视为缺陷。
        deleted_discarded = not fe.apply_result(resp.get("element_id"), resp)
        ok("已删除元素的回包被前端丢弃（预期行为，元素已不在画布）",
           deleted_discarded)
        # 清掉它的 pending 标记：元素已不存在，不应再计入"卡住"
        fe.painted.pop("dia_001", None)
        fe.results.pop("dia_001", None)

        # ==========================================================
        # 流程 5：连续快速编辑（学生拖拽属性时的真实节奏）
        # ==========================================================
        print("\n[5] 连续快速编辑（模拟拖拽/快速改名）")
        import time
        t0 = time.perf_counter()
        n = 60
        for i in range(n):
            e = dict(fe.elements["rect_001"])
            e["label"] = f"读者{i}"
            fe.elements["rect_001"] = e
            fe.mark_pending("rect_001")
            resp = await send(ws2, encode_element_modified(
                e, {"attributes_changed": False, "label_changed": True}))
            fe.apply_result(resp.get("element_id"), resp)
        dt = (time.perf_counter() - t0) / n * 1000
        ok(f"{n} 次连续编辑全部有回包且被消费",
           not fe.pending_ids(), f"仍在 pending: {fe.pending_ids()}")
        print(f"        平均每次 {dt:.1f}ms（前端超时 2000ms）")
        ok("远小于前端 2s 超时", dt < 2000, f"实际 {dt:.1f}ms")

    finally:
        await ws2.close()

    # ==========================================================
    # 汇总
    # ==========================================================
    print("\n[汇总] 前端丢弃统计")
    print(f"        整个流程中被丢弃的结果数：{len(fe.discarded)}")
    for eid, _ in fe.discarded[:5]:
        print(f"          - {eid}")
    # 唯一允许的丢弃是"已删除元素"的回包 —— 元素不在画布上，无需上色。
    unexpected = [eid for eid, _ in fe.discarded if eid != "dia_001"]
    ok("除已删除元素外，无结果被前端丢弃", not unexpected,
       f"意外丢弃 {unexpected}")

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
