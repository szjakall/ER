# -*- coding: utf-8 -*-
"""
ER 规则校验 WebSocket 服务
==========================

地址：ws://localhost:8000/ws   （与 INTERFACE.md 一致）

启动：
    python server.py
或：
    uvicorn server:app --host 0.0.0.0 --port 8000

实现的消息（INTERFACE.md 消息总览）：
    前端→后端： action=check (element_added/modified/deleted, connection_added/modified)
                action=batch_check
    后端→前端： action=result / batch_result / error
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from engine import ENGINE, trie_summary
from weakness import TRACKER
import diagnose_queue
from llm import DIAGNOSER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("er-ws")

app = FastAPI(title="ER 规则校验服务")

# 统计（供 /stats 查看）
STATS = {"connections": 0, "messages": 0, "errors": 0, "timings_us": []}

# 在线连接：user_id -> WebSocket，用于把异步诊断结果推给对应学生
LIVE_SOCKETS: dict = {}


def _push_diagnosis(user_id: str, diagnosis) -> None:
    """
    诊断生成完成后的回调：通过 WebSocket 非侵入式推送给学生。

    需求书要求"结果以非侵入式提示呈现"——故用独立的
    action="diagnosis" 消息类型，不混入 violations/suggestions，
    前端可选择只在侧栏展示，不打断绘图。
    """
    ws = LIVE_SOCKETS.get(user_id)
    if ws is None:
        return
    payload = {
        "action": "diagnosis",
        "user_id": user_id,
        "data": diagnosis.to_dict(),
    }
    try:
        import asyncio
        asyncio.run_coroutine_threadsafe(
            ws.send_text(json.dumps(payload, ensure_ascii=False)),
            LOOP_HOLDER["loop"])
    except Exception:
        pass


# 事件循环句柄（推送需要从 worker 线程投递回事件循环）
LOOP_HOLDER: dict = {"loop": None}


@app.on_event("startup")
async def startup_runtime() -> None:
    """
    兼容两种部署方式：
      1) python server.py（main 会调用 init_queue）
      2) uvicorn server:app（不会经过 main，必须在 startup 启动 worker）
    """
    import asyncio
    LOOP_HOLDER["loop"] = asyncio.get_running_loop()
    if diagnose_queue.QUEUE is None:
        diagnose_queue.init_queue(on_result=_push_diagnosis)


@app.on_event("shutdown")
async def shutdown_runtime() -> None:
    """停止异步诊断 worker，并把学情缓冲落盘。"""
    if diagnose_queue.QUEUE is not None:
        diagnose_queue.QUEUE.stop()
        diagnose_queue.QUEUE = None
    LIVE_SOCKETS.clear()
    LOOP_HOLDER["loop"] = None
    TRACKER.flush_all()


@app.get("/")
def index() -> dict:
    return {
        "service": "ER 规则校验服务",
        "websocket": "ws://localhost:8000/ws",
        "rules": len(ENGINE.trie.all_rules()),
        "trie": ENGINE.trie.stats(),
    }


# ----------------------------------------------------------------------
# 薄弱点 / 学情接口（研究内容三）
# 供学情看板取数；LLM 深度归因作为后续异步层，读同一份数据即可。
# ----------------------------------------------------------------------

@app.get("/weakness/{user_id}")
def weakness_of_user(user_id: str, top_n: int = 5) -> dict:
    """
    个人错误清单：按规则分类汇总 + 高频薄弱点。

    示例：GET /weakness/student-A
    """
    return TRACKER.summary(user_id, top_n=top_n)


@app.get("/weakness")
def weakness_class(top_n: int = 5) -> dict:
    """
    班级学情：共性问题识别（如"80% 学生遗漏联系基数标注"）。

    示例：GET /weakness
    """
    return TRACKER.class_summary(top_n=top_n)


@app.delete("/weakness/{user_id}")
def weakness_clear(user_id: str) -> dict:
    """清除某用户的记录（会话结束归档后调用）。"""
    TRACKER.clear(user_id)
    return {"ok": True, "user_id": user_id}


# ----------------------------------------------------------------------
# LLM 深度归因接口（研究内容三：统计 + LLM 归因）
# 与实时校验完全解耦：这些接口同步生成，但**不参与**绘图的毫秒级反馈。
# ----------------------------------------------------------------------

@app.get("/diagnosis/{user_id}")
def diagnosis_of_user(user_id: str, top_n: int = 3,
                      source: str = "") -> dict:
    """
    生成某学生的学情诊断报告。

    source 可选 "heuristic"（本地确定性归因）或 "llm"（大模型）。
    不传则用默认 Provider（配了 LLM 用 LLM，否则自动用启发式）。

    示例：GET /diagnosis/student-A
    """
    d = DIAGNOSER.diagnose_user(user_id, top_n=top_n,
                                force_source=source or None)
    return d.to_dict()


@app.get("/diagnosis")
def diagnosis_class(top_n: int = 5) -> dict:
    """
    班级学情摘要 + 教学调整建议（对应需求书"自动为教师生成整体学情分析报告"）。

    示例：GET /diagnosis
    """
    return DIAGNOSER.diagnose_class(top_n=top_n)


@app.get("/diagnosis/queue/stats")
def diagnosis_queue_stats() -> dict:
    """异步诊断队列状态（用于确认"LLM 不阻塞实时校验"）。"""
    if diagnose_queue.QUEUE is None:
        return {"running": False}
    return {"running": True, **diagnose_queue.QUEUE.stats()}


@app.get("/stats")
def stats() -> dict:
    t = STATS["timings_us"]
    if not t:
        return {**{k: v for k, v in STATS.items() if k != "timings_us"},
                "latency": None}
    s = sorted(t)
    return {
        "connections": STATS["connections"],
        "messages": STATS["messages"],
        "errors": STATS["errors"],
        "latency_us": {
            "count": len(s),
            "p50": s[len(s) // 2],
            "p95": s[int(len(s) * 0.95)] if len(s) > 1 else s[0],
            "max": s[-1],
        },
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    STATS["connections"] += 1
    # 每个连接一个会话（图缓存隔离）
    session_key = f"{id(ws)}"
    # 学生标识：连接时用 ?user_id=xxx 指定（推荐），
    # 也可在消息体里带 user_id；都不传则退化为会话键。
    # 这样"薄弱点记录"才能归属到具体学生，教师才查得到人。
    uid = ws.query_params.get("user_id") or ws.query_params.get("student_id")
    if uid:
        ENGINE.bind_user(session_key, uid)
    # 日志注入防护：uid 来自客户端（查询参数/消息体），含换行可伪造日志行。
    # 记账侧不受影响（JSONL 是 JSON 转义存储），仅清洗日志输出。
    uid_log = (uid or "-").replace("\r", "\\r").replace("\n", "\\n")
    log.info("客户端已连接 session=%s user=%s", session_key, uid_log)
    # 记录在线连接，供异步诊断结果推送
    if uid:
        LIVE_SOCKETS[uid] = ws
    # 记录事件循环，使 worker 线程能把结果投递回本循环
    if LOOP_HOLDER["loop"] is None:
        import asyncio as _a
        LOOP_HOLDER["loop"] = _a.get_running_loop()

    try:
        while True:
            # 用 receive() 而非 receive_text()（v1.5 修正）：
            # receive_text 遇到二进制帧会直接抛异常，落入兜底断连——
            # 客户端误发/恶意发一帧二进制就断连，虽然前端会自动重连，
            # 但回 error 不断连更健壮。
            raw_msg = await ws.receive()
            if raw_msg.get("type") == "websocket.disconnect":
                break
            if raw_msg.get("bytes") is not None:
                STATS["errors"] += 1
                await ws.send_text(json.dumps({
                    "action": "error",
                    "element_id": None,
                    "message": "消息格式错误: 收到二进制帧，请发送 UTF-8 JSON 文本",
                }, ensure_ascii=False))
                continue
            raw = raw_msg.get("text") or ""
            t0 = time.perf_counter()
            STATS["messages"] += 1

            # --- 解析 -------------------------------------------------
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                STATS["errors"] += 1
                await ws.send_text(json.dumps({
                    "action": "error",
                    "element_id": None,
                    "message": "消息格式错误: JSON 解析失败",
                }, ensure_ascii=False))
                continue

            if not isinstance(msg, dict):
                STATS["errors"] += 1
                await ws.send_text(json.dumps({
                    "action": "error",
                    "element_id": None,
                    "message": "消息格式错误: 顶层应为 JSON 对象",
                }, ensure_ascii=False))
                continue

            # --- 交给引擎 ---------------------------------------------
            reply = ENGINE.handle(session_key, msg)

            # --- 回包 -------------------------------------------------
            await ws.send_text(json.dumps(reply, ensure_ascii=False))
            dt_us = (time.perf_counter() - t0) * 1_000_000
            STATS["timings_us"].append(dt_us)
            # 只保留最近 5000 条，避免内存增长
            if len(STATS["timings_us"]) > 5000:
                STATS["timings_us"] = STATS["timings_us"][-5000:]

    except WebSocketDisconnect:
        log.info("客户端断开 session=%s", session_key)
    except Exception as ex:  # pragma: no cover
        log.warning("连接异常 session=%s: %s", session_key, ex)
    finally:
        ENGINE.drop_session(session_key)
        # 断连即落盘：把该连接缓冲的学情记录写盘，
        # 避免进程异常退出时丢掉最后一个学生的数据。
        TRACKER.flush()
        if uid and LIVE_SOCKETS.get(uid) is ws:
            LIVE_SOCKETS.pop(uid, None)
        STATS["connections"] = max(0, STATS["connections"] - 1)


def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="ER 规则校验服务")
    parser.add_argument("--host", default="0.0.0.0")
    # 默认 8000（INTERFACE.md 约定）；被占用时可用 --port 指定其他端口
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("ER_WS_PORT", "8000")))
    args = parser.parse_args()

    print("=" * 64)
    print("  ER 规则校验服务")
    print("=" * 64)
    print(trie_summary())
    print("-" * 64)
    st = TRACKER.stats()
    print(f"  学情台账: {st['students']} 名学生 / {st['total_records']} 条记录")
    print(f"  持久化  : {st['persist_path'] or '已关闭（仅内存）'}")
    prov = DIAGNOSER.provider
    if prov.name == "heuristic":
        prov_desc = "本地启发式（未配置 LLM，功能仍完整可用）"
    else:
        prov_desc = getattr(prov, "model", prov.name) or prov.name
    print(f"  归因层  : {prov.name}（{prov_desc}）")
    print("-" * 64)
    print(f"  WebSocket: ws://localhost:{args.port}/ws")
    print(f"  健康检查:  http://localhost:{args.port}/")
    print(f"  学情接口:  http://localhost:{args.port}/weakness")
    print(f"  诊断接口:  http://localhost:{args.port}/diagnosis")
    print("=" * 64)
    # worker 统一由应用 startup/shutdown 管理，兼容脚本与 uvicorn 入口。
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        if diagnose_queue.QUEUE is not None:
            diagnose_queue.QUEUE.stop()
        # 正常退出前落盘，防止丢尾部缓冲
        n = TRACKER.flush_all()
        if n:
            print(f"退出前已落盘 {n} 条学情记录")


if __name__ == "__main__":
    main()
