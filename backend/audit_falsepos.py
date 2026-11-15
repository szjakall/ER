# -*- coding: utf-8 -*-
"""
误报检查：用前端自带的教科书标准图验证
======================================

weak.json    —— 弱实体图（职工 === 具有 === 亲属）
ternary.json —— 三元联系图（供应商 M—供应—N 项目 / P 零件）
library.json —— 普通二元图

这些是**正确的标准设计**。若引擎在它们身上报出大量刚性错误 R，
就是误报，会让学生被无故标红。

运行：python audit_falsepos.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import json
import sys
from pathlib import Path

from engine import Session, check_batch

SAMPLES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "samples"

# 允许出现的启发建议（教学上合理，不算误报）
ACCEPTABLE_HINTS = {
    "H03",  # 多值属性（电话/地址）—— 教科书图里确实存在，提示拆分是合理的
    "H04",  # 派生属性（年龄）
    "H07",  # 名称含空格/特殊字符
    "H13",  # 多实体无联系
    "H14",  # 各端基数均 1
    "H15",  # 三元基数组合
    "H16",  # 属性偏少
    "H17",  # 图规模过小
    "H18", "H19", "H20", "H21",  # 需求对齐（无需求文本时不触发）
    "H05",  # 命名风格
    "H12",  # 孤立实体
}


def run_sample(path: Path) -> tuple[int, int, list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    s = Session()
    resp = check_batch(s, {"action": "batch_check",
                           "diagram": {"elements": data["elements"],
                                       "connections": data["connections"]}})
    # 汇总（同一元素可能重复收到图级提示，按 rule_id 去重统计）
    rigid, hints = {}, {}
    for v in resp["results"].values():
        for it in v["violations"]:
            rigid.setdefault(it["rule_id"], it["message"])
        for it in v["suggestions"]:
            hints.setdefault(it["rule_id"], it["message"])
    return rigid, hints, data


def main() -> int:
    print("=" * 68)
    print("  误报检查：教科书标准图")
    print("=" * 68)

    problems = 0
    for name in ["weak.json", "ternary.json", "library.json"]:
        p = SAMPLES / name
        if not p.exists():
            print(f"\n[跳过] {name} 不存在")
            continue
        rigid, hints, data = run_sample(p)
        labels = [e.get("label", "") for e in data["elements"]]
        print(f"\n[{name}] 元素: {'、'.join(labels)}")
        print(f"  刚性错误 R: {len(rigid)} 种")
        for rid, msg in sorted(rigid.items()):
            print(f"     红 [{rid}] {msg}")
        print(f"  启发建议 H: {len(hints)} 种")
        for rid, msg in sorted(hints.items()):
            mark = "" if rid in ACCEPTABLE_HINTS else "  ← 未预期的提示类型"
            print(f"     橙 [{rid}] {msg}{mark}")

        # 判定：标准图不应出现刚性错误
        unexpected = {k: v for k, v in rigid.items() if True}
        if unexpected:
            problems += len(unexpected)
            print(f"  ** 该标准图出现 {len(unexpected)} 种刚性错误（疑似误报）**")
        else:
            print("  ✓ 无刚性错误")

    print("\n" + "=" * 68)
    if problems == 0:
        print("  结论：标准图零刚性误报 ✓")
    else:
        print(f"  结论：累计 {problems} 处刚性误报，需复核")
    print("=" * 68)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
