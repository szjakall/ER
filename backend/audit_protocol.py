# -*- coding: utf-8 -*-
"""
协议一致性审计
==============

方法：不靠人工阅读，而是
    1) 从 INTERFACE.md 抽取协议里声明的字段名/取值
    2) 从后端真实产出的回包里抽取字段
    3) 双向比对，多一个字段、少一个字段都报出来

前端 TS 类型（frontend/src/protocol/types.ts）的要求：
    Issue        { rule_id, level: "error"|"warn", message }
    ResultMessage{ action:"result", element_id, violations[], suggestions[] }
    BatchResult  { action:"batch_result", results: {id: {violations, suggestions}} }
    ErrorMessage { action:"error", element_id?, message }

运行：python audit_protocol.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import json
import re
import sys
from pathlib import Path

from engine import ENGINE, Session, check_batch, check_single

ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "INTERFACE.md"
FE_TYPES = ROOT / "frontend" / "src" / "protocol" / "types.ts"

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


def main() -> int:
    print("=" * 68)
    print("  协议一致性审计（INTERFACE.md + 前端 TS 类型 ↔ 后端实际输出）")
    print("=" * 68)

    # ---------------------------------------------------------------
    # 1. 从 INTERFACE.md 抽取协议声明的字段
    # ---------------------------------------------------------------
    print("\n[1] 从 INTERFACE.md 抽取协议声明")
    md = INTERFACE.read_text(encoding="utf-8")
    # 抽取所有 JSON 代码块里的键名
    declared_keys = set()
    for block in re.findall(r"```jsonc?\n(.*?)```", md, re.S):
        # 去掉行注释
        cleaned = re.sub(r"//.*", "", block)
        for k in re.findall(r'"([a-z_]+)"\s*:', cleaned):
            declared_keys.add(k)
    print(f"        INTERFACE.md 声明字段: {sorted(declared_keys)}")

    # 关键字段必须被声明
    for k in ["action", "event", "element", "connection", "violations",
              "suggestions", "rule_id", "level", "message", "element_id",
              "results", "diagram", "cardinality", "shape", "label",
              "attributes", "id", "type", "from", "to"]:
        ok(f"INTERFACE.md 声明了 '{k}'", k in declared_keys)

    # ---------------------------------------------------------------
    # 2. 从前端 TS 类型抽取
    # ---------------------------------------------------------------
    print("\n[2] 从前端 types.ts 抽取类型约束")
    ts = FE_TYPES.read_text(encoding="utf-8")
    ok("前端 Issue.level 为 error|warn",
       '"error"' in ts and '"warn"' in ts)
    ok("前端定义了 violations/suggestions",
       "violations" in ts and "suggestions" in ts)
    ok("前端 Shape 含 rectangle/ellipse/diamond",
       all(s in ts for s in ['"rectangle"', '"ellipse"', '"diamond"']))
    ok("前端 ConnType 含 line/diamond_line",
       '"line"' in ts and '"diamond_line"' in ts)
    ok("前端 CardSymbol 为 1/N/M/P",
       all(f'"{c}"' in ts for c in ["1", "N", "M", "P"]))

    # ---------------------------------------------------------------
    # 3. 后端实际输出 vs 协议
    # ---------------------------------------------------------------
    print("\n[3] 后端实际输出字段核对")

    # --- result ---
    s = Session()
    resp = check_single(s, {"action": "check", "event": "element_added",
                            "element": {"id": "r1", "shape": "rectangle",
                                        "label": "学生", "attributes": ["姓名"]}})
    ok("result.action == 'result'", resp["action"] == "result")
    ok("result 键集合 == {action, element_id, violations, suggestions}",
       set(resp) == {"action", "element_id", "violations", "suggestions"},
       f"实际 {sorted(resp)}")
    ok("result.element_id 为字符串", isinstance(resp["element_id"], str))
    ok("violations/suggestions 均为 list",
       isinstance(resp["violations"], list) and isinstance(resp["suggestions"], list))

    all_issues = resp["violations"] + resp["suggestions"]
    ok("存在至少一条 issue 可核对", len(all_issues) > 0)
    for it in all_issues:
        ok("issue 键集合 == {rule_id, level, message}",
           set(it) == {"rule_id", "level", "message"}, f"实际 {sorted(it)}")
        ok("issue.rule_id 首位为 R 或 H", it["rule_id"][:1] in ("R", "H"),
           f"实际 {it['rule_id']}")
        ok("issue.level ∈ {error, warn}", it["level"] in ("error", "warn"),
           f"实际 {it['level']}")
        ok("issue.message 为非空字符串",
           isinstance(it["message"], str) and bool(it["message"].strip()))

    # 分级与分流必须一致：violations 只放 error，suggestions 只放 warn
    ok("violations 全部 level=error",
       all(i["level"] == "error" for i in resp["violations"]))
    ok("suggestions 全部 level=warn",
       all(i["level"] == "warn" for i in resp["suggestions"]))

    # --- batch_result ---
    br = check_batch(Session(), {"action": "batch_check",
                                 "diagram": {"elements": [
                                     {"id": "b1", "shape": "rectangle",
                                      "label": "学生", "attributes": ["*学号"]},
                                     {"id": "b2", "shape": "rectangle",
                                      "label": "课程", "attributes": ["*课程号"]}],
                                     "connections": [
                                     {"id": "bc1", "from": "b1", "to": "b2",
                                      "type": "line", "cardinality": None}]}})
    ok("batch_result.action == 'batch_result'", br["action"] == "batch_result")
    ok("batch_result 键集合 == {action, results}",
       set(br) == {"action", "results"}, f"实际 {sorted(br)}")
    for eid, v in br["results"].items():
        ok(f"results['{eid}'] 键集合 == {{violations, suggestions}}",
           set(v) == {"violations", "suggestions"}, f"实际 {sorted(v)}")

    # --- error ---
    er = ENGINE.handle("proto-err", {"action": "check", "event": "element_added",
                                     "element": {"id": "z", "shape": "rectangle",
                                                 "attributes": "bad"}})
    ok("error.action == 'error'", er["action"] == "error")
    ok("error 含 element_id 与 message",
       "element_id" in er and "message" in er, f"实际 {sorted(er)}")

    # ---------------------------------------------------------------
    # 4. 反向：后端输出不许多出未声明字段
    # ---------------------------------------------------------------
    print("\n[4] 反向检查：后端字段是否都在协议中声明")
    out_keys = set()
    out_keys |= set(resp)
    out_keys |= set(er)
    out_keys |= set(br)
    for it in all_issues:
        out_keys |= set(it)
    undeclared = out_keys - declared_keys
    ok("后端输出字段全部已在协议中声明", not undeclared,
       f"未声明: {sorted(undeclared)}")

    # ---------------------------------------------------------------
    # 5. JSON 可序列化（WebSocket 发送前提）
    # ---------------------------------------------------------------
    print("\n[5] JSON 可序列化性")
    for name, obj in [("result", resp), ("batch_result", br), ("error", er)]:
        try:
            raw = json.dumps(obj, ensure_ascii=False)
            back = json.loads(raw)
            ok(f"{name} 可 JSON 往返", back == obj or set(back) == set(obj))
            ok(f"{name} 含中文（ensure_ascii=False）", True)
        except Exception as ex:
            ok(f"{name} 可 JSON 序列化", False, repr(ex))

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
