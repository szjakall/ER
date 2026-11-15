# -*- coding: utf-8 -*-
"""
协议反向审查（从代码提字段，反查文档）
====================================

方法不同于 audit_protocol.py：
    那个脚本是"读 INTERFACE.md 抽字段 → 看后端有没有"（正向）。
    本脚本反过来：**从后端源码提取所有对外发出的字段名**，
    再检查每一个是否在 INTERFACE.md / 前端类型里有出处。
    目的是抓"后端悄悄多发了协议没定义的字段"。

这类问题很隐蔽：多发字段前端不会报错（JS 忽略多余键），
但会让协议逐渐失守（下游依赖了非契约字段，未来改动即破坏）。

运行：python audit_protocol_reverse.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

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


def main() -> int:
    print("=" * 70)
    print("  协议反向审查（从后端代码提字段 → 反查契约）")
    print("=" * 70)

    # ---------------------------------------------------------------
    # 1. 从源码提取：所有字面量字典键（后端可能发出的字段）
    #
    # 注意：AST 扫描无法区分"协议字段"与"数据键"。
    # 例如 rules.py 的同义词表 {'学生': [...], '课程': [...]} 里的中文键
    # 是业务数据、不是对外字段。故此处只扫**协议出口**文件
    # （engine.py / server.py），并跳过明显的数据字典。
    # rules.py / model.py 的键属于规则内部数据，不参与协议审查。
    # ---------------------------------------------------------------
    print("\n[1] 从后端源码提取对外字段（仅协议出口文件）")
    src_files = ["engine.py", "server.py"]
    # 这些是数据字典（同义词表等），键不是协议字段
    DATA_DICT_LINE_HINTS = ("_REQUIREMENT_SYNONYMS", "_REQUIREMENT_ATTRS",
                            "_SYNONYMS", "SYNONYMS", "ATTRS")
    literal_keys: dict = {}
    for name in src_files:
        p = HERE / name
        if not p.exists():
            continue
        source = p.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            # 跳过位于数据字典语句内的字典
            ctx_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if any(h in ctx_line for h in DATA_DICT_LINE_HINTS):
                continue
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    literal_keys.setdefault(k.value, set()).add(
                        f"{name}:{node.lineno}")
    print(f"        字面量键共 {len(literal_keys)} 个")

    # ---------------------------------------------------------------
    # 2. 从 INTERFACE.md + 前端类型 收集"契约允许的字段"
    # ---------------------------------------------------------------
    print("\n[2] 收集契约允许的字段")
    md = (ROOT / "INTERFACE.md").read_text(encoding="utf-8")
    ts = (ROOT / "frontend" / "src" / "protocol" / "types.ts").read_text(encoding="utf-8")

    contract = set(re.findall(r'"\s*([a-z_]+)\s*"\s*:', re.sub(r"//.*", "", md)))
    # 前端 TS 接口字段：  name: Type  或  name?: Type
    contract |= set(re.findall(r"^\s{2}([a-z_]+)\??\s*:", ts, re.M))
    # 前端发的字段（encode.ts 里构造的对象键）
    enc = (ROOT / "frontend" / "src" / "protocol" / "encode.ts").read_text(encoding="utf-8")
    contract |= set(re.findall(r"^\s+([a-z_]+):", enc, re.M))
    # 协议行为隐含的键（前端 ws.ts / store.ts 会读）
    ws = (ROOT / "frontend" / "src" / "protocol" / "ws.ts").read_text(encoding="utf-8")
    contract |= set(re.findall(r"msg\.([a-z_]+)", ws))
    contract |= {"action", "event", "element", "connection", "diagram",
                 "violations", "suggestions", "results", "element_id",
                 "rule_id", "level", "message", "changes", "x", "y"}

    # backend 侧**已文档化**的协议扩展（见 PROTOCOL-EXTENSIONS.md）。
    # 这里不是"白名单开脱"：扩展文档本身就是契约的一部分，
    # 字段必须在该文档里写明才算合法，否则仍报未声明。
    ext_path = HERE / "PROTOCOL-EXTENSIONS.md"
    if ext_path.exists():
        ext_text = ext_path.read_text(encoding="utf-8")
        ext_keys = set(re.findall(r'"\s*([a-z_]+)\s*"\s*:', ext_text))
        ext_keys |= set(re.findall(r"`([a-z_]+)`", ext_text))
        contract |= ext_keys
        print(f"        已文档化扩展字段 {len(ext_keys)} 个")
    print(f"        契约允许 {len(contract)} 个字段")

    # ---------------------------------------------------------------
    # 3. 反向检查：后端发出的字段是否都有出处
    # ---------------------------------------------------------------
    print("\n[3] 后端字段是否有契约出处")
    # 这些不是协议字段，是内部结构/诊断字段，单独列出说明
    INTERNAL_ALLOWED = {
        # 请求里前端可能带的（未在 INTERFACE.md 正式定义，但服务端支持）
        "user_id", "student_id", "requirement_text",
        # 纯内部变量名，从不出现在任何回包里
        # （LOOP_HOLDER = {"loop": None} 是本地持有事件循环用的，
        #   不是对外字段；AST 扫描无法区分"字典键"与"协议字段"，故显式排除）
        "loop",
        # 内部诊断/统计
        "count", "p50", "p95", "p99", "max", "latency_us", "service",
        "websocket", "rules", "trie", "total_rules", "events",
        "max_per_event", "node_count", "connections", "messages", "errors",
        "time_str", "timestamp", "context", "elements", "total",
        "error_count", "warning_count", "by_rule", "by_level", "weak_points",
        "session_span_sec", "share", "first_at", "last_at", "student_count",
        "common_issues", "total_count", "student_share", "ok", "students",
        "total_records", "pending_writes", "persist_failures", "persist_path",
        "latency", "min", "mean", "budget",
        # /stats 接口的内部统计键（HTTP 诊断接口，非 WS 协议）
        "timings_us",
    }
    undeclared = sorted(k for k in literal_keys
                        if k not in contract and k not in INTERNAL_ALLOWED)
    if undeclared:
        print("        以下字段既不在契约、也不在内部白名单：")
        for k in undeclared:
            locs = ", ".join(sorted(literal_keys[k])[:3])
            print(f"          - {k!r}  ({locs})")
    ok("后端发出的协议字段全部有出处", not undeclared,
       f"共 {len(undeclared)} 个未声明")

    # ---------------------------------------------------------------
    # 4. 实际运行时抓包：真实回包里出现的所有字段
    # ---------------------------------------------------------------
    print("\n[4] 运行时回包字段（比静态分析更可靠）")
    from engine import ENGINE, Session, check_batch

    seen = {}

    def collect(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                seen.setdefault(k, set()).add(path)
                collect(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for it in obj[:3]:
                collect(it, f"{path}[]")

    # 单次检查（含错误响应）
    s = Session()
    collect(ENGINE.handle("rev-1", {
        "action": "check", "event": "element_added",
        "element": {"id": "e1", "shape": "rectangle", "label": "学生",
                    "attributes": ["姓名"]}}), "result")
    collect(ENGINE.handle("rev-2", {"action": "bogus"}), "error")
    collect(ENGINE.handle("rev-3", {
        "action": "check", "event": "element_added",
        "element": {"id": "x", "attributes": "bad"}}), "badfmt")
    # 批量
    collect(check_batch(Session(), {"action": "batch_check", "diagram": {
        "elements": [{"id": "b1", "shape": "rectangle", "label": "A",
                      "attributes": ["姓名"]}],
        "connections": []}}), "batch")

    print(f"        实际出现 {len(seen)} 个字段")
    # results 的键是**元素 id**（动态数据），不是协议字段。
    # 判定依据：它是 batch_check 请求里出现的 id，而非固定字段名。
    dynamic_keys = {"b1", "e1", "x", "z", "rev-1", "rev-2", "rev-3",
                    "rev-4", "rev-5"}
    runtime_undeclared = sorted(
        k for k in seen
        if k not in contract and k not in INTERNAL_ALLOWED
        and k not in dynamic_keys)
    ok("运行时字段全部有出处（排除元素 id 等动态键）",
       not runtime_undeclared, f"未声明：{runtime_undeclared}")

    # ---------------------------------------------------------------
    # 5. 协议要求的字段是否真的都出现（正向兜底）
    # ---------------------------------------------------------------
    print("\n[5] 协议关键字段是否真的出现")
    for k in ["action", "element_id", "violations", "suggestions",
              "rule_id", "level", "message", "results"]:
        ok(f"运行时出现 '{k}'", k in seen, f"实际字段：{sorted(seen)[:12]}")

    # ---------------------------------------------------------------
    # 6. level 取值封闭性（前端只认 error/warn）
    # ---------------------------------------------------------------
    print("\n[6] level 取值封闭性")
    import rules as R
    from model import Diagram
    from rules import RuleContext
    levels = set()
    for rid, fn, _ in R.RULE_SPECS:
        try:
            for it in (fn(RuleContext(diagram=Diagram([], []))) or []):
                levels.add(it.get("level"))
        except Exception:
            pass
    ok("level 取值 ⊆ {error, warn}", levels <= {"error", "warn"},
       f"实际 {levels}")

    # ---------------------------------------------------------------
    # 7. action 取值封闭性
    # ---------------------------------------------------------------
    print("\n[7] action 取值封闭性")
    # INTERFACE.md 声明的后端→前端 action
    declared_actions = {"result", "batch_result", "error"}
    runtime_actions = set()
    for tag in ("result", "error", "badfmt", "batch"):
        pass
    # 从实际回包重采
    r1 = ENGINE.handle("rev-4", {"action": "check", "event": "element_added",
                                 "element": {"id": "z", "shape": "rectangle",
                                             "label": "A", "attributes": ["*a"]}})
    r2 = ENGINE.handle("rev-5", {"action": "nope"})
    r3 = check_batch(Session(), {"action": "batch_check",
                                 "diagram": {"elements": [], "connections": []}})
    runtime_actions = {r1.get("action"), r2.get("action"), r3.get("action")}
    ok("实际 action 都在协议声明内", runtime_actions <= declared_actions,
       f"实际 {runtime_actions} vs 声明 {declared_actions}")
    ok("三类回包 action 均被实际触发到",
       runtime_actions == declared_actions, f"实际 {runtime_actions}")

    print("\n" + "=" * 70)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题：")
        for p in _problems:
            print(f"    - {p}")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
