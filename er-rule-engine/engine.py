# -*- coding: utf-8 -*-
"""
ER 规则引擎
============
加载所有规则，跑一遍，返回结果。

用法：
  命令行：  python engine.py test_data.json
  代码调用：
    from engine import run_all_rules
    result = run_all_rules(er_data_dict)
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import ALL_RULES


def run_all_rules(er_data):
    """
    运行所有规则，返回检查结果。

    输入: er_data (dict) —— ER 图 JSON 数据
    输出: {
        "errors": [ {rule_id, level, target_type, target_id, message}, ... ],
        "summary": { "total": int, "errors": int, "warnings": int }
    }
    """
    all_errors = []
    for rule_fn in ALL_RULES:
        try:
            result = rule_fn(er_data)
            all_errors.extend(result)
        except Exception as ex:
            all_errors.append({
                "rule_id": rule_fn.__name__,
                "level": "error",
                "target_type": "system",
                "target_id": "",
                "message": f"规则执行异常: {ex}",
            })

    error_count = sum(1 for e in all_errors if e["level"] == "error")
    warning_count = sum(1 for e in all_errors if e["level"] == "warning")

    return {
        "errors": all_errors,
        "summary": {
            "total": len(all_errors),
            "errors": error_count,
            "warnings": warning_count,
        },
    }


# ======================================================================
# 命令行入口
# ======================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python engine.py <er_data.json>")
        print("示例: python engine.py test_data.json")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        sys.exit(1)

    with open(filepath, encoding="utf-8") as f:
        er_data = json.load(f)

    result = run_all_rules(er_data)
    s = result["summary"]

    print(f"\n{'='*60}")
    print(f"  检查完成：{s['errors']} 个错误，{s['warnings']} 个警告，共 {s['total']} 条")
    print(f"{'='*60}\n")

    if not result["errors"]:
        print("  ✅ 没有发现问题！\n")
    else:
        for e in result["errors"]:
            icon = "🔴" if e["level"] == "error" else "🟠"
            print(f"  {icon} [{e['rule_id']}] {e['message']}")
        print()
