# -*- coding: utf-8 -*-
"""
交付物一致性审计
================

查"文档说的是不是真的"：
    1) RULES.md 声明的规则数与代码实际是否一致
    2) RULES.md 里列出的每个 rule_id 是否都在代码里实现了
    3) 代码里的每条规则是否都在 RULES.md 里有记录
    4) README.md 里的命令是否都指向真实存在的文件
    5) 无死代码（定义了但没被注册的规则）
    6) 无重复实现（同一 rule_id 出现多次）

运行：python audit_consistency.py
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

import rules as R
from engine import RULE_FN_BY_ID, TRIE

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
    print("  交付物一致性审计（文档 ↔ 代码）")
    print("=" * 68)

    code_ids = list(R.RULE_IDS)

    # ---------------- 1. 规则数一致性 ----------------
    print("\n[1] 规则数一致性")
    ok(f"代码规则数 = {len(code_ids)}", len(code_ids) == 44,
       f"实际 {len(code_ids)}")
    ok("规则数 ≥ 35（需求下限）", len(code_ids) >= 35)
    ok("无重复 rule_id", len(code_ids) == len(set(code_ids)))
    ok("engine 注册表与 rules 一致",
       set(RULE_FN_BY_ID) == set(code_ids),
       f"差集 {set(RULE_FN_BY_ID) ^ set(code_ids)}")

    # ---------------- 2. RULES.md 覆盖 ----------------
    print("\n[2] RULES.md ↔ 代码 双向覆盖")
    md_path = HERE / "RULES.md"
    md = md_path.read_text(encoding="utf-8")

    # 从 markdown 表格行抽 rule_id（形如 | R01 |）
    md_ids = set(re.findall(r"\|\s*([RH]\d{2})\s*\|", md))
    code_set = set(code_ids)

    missing_in_md = code_set - md_ids
    missing_in_code = md_ids - code_set
    ok("代码中每条规则都在 RULES.md 有记录", not missing_in_md,
       f"文档缺失: {sorted(missing_in_md)}")
    ok("RULES.md 中每个编号都有实现", not missing_in_code,
       f"代码缺失: {sorted(missing_in_code)}")

    # 文档标题声明的条数
    m = re.search(r"共\s*(\d+)\s*条", md)
    if m:
        ok("RULES.md 标题条数与代码一致",
           int(m.group(1)) == len(code_ids),
           f"文档声明 {m.group(1)}，代码 {len(code_ids)}")
    else:
        ok("RULES.md 标题含条数声明", False, "未找到「共 N 条」")

    # 分级数字断言：文档声明的 19/25 必须与 level_of 派生值一致。
    # （RULES.md 明确写"刚性 19 / 启发 25"，此前审计只查了"共 44 条"，
    #   分级数字改错不会被发现——文档数字与代码数字是两个独立事实。）
    m2 = re.search(r"刚性\s*(\d+)\s*/\s*启发\s*(\d+)", md)
    if m2:
        doc_r, doc_h = int(m2.group(1)), int(m2.group(2))
        ok("RULES.md 分级数字（刚性）与代码一致",
           doc_r == len(R.RIGID_IDS),
           f"文档 {doc_r}，代码 {len(R.RIGID_IDS)}")
        ok("RULES.md 分级数字（启发）与代码一致",
           doc_h == len(R.HEURISTIC_IDS),
           f"文档 {doc_h}，代码 {len(R.HEURISTIC_IDS)}")
    else:
        ok("RULES.md 含分级数字声明", False, "未找到「刚性 N / 启发 M」")

    # ------------------------------------------------------------------
    # 文档明细表 ↔ 代码等级（关键断言）
    #
    # 注意口径差异：文档 §1–§4 按**教学语义**分组（教师按概念找规则），
    # 代码 RULE_SPECS 按**触发事件**挂载（工程调度）。两种口径本就不同
    # （如 R17–R19 语义上是图结构级，但挂连线事件实时响应），
    # 因此**不能**直接用事件推导对比文档分组数字——曾据此误报 3 处。
    #
    # 真正该验证的是：
    #   1) 文档每行明细表的「级」列 == level_of(id)（防"文档写刚性、
    #      代码是启发"这类脱节——上一轮 RULES.md 大面积脱节的直接防线）
    #   2) 文档每节小计之和 == 明细表总行数（文档内部自洽）
    # ------------------------------------------------------------------
    # 提取明细表行：| R01 | 刚性 | ... 或 | H01 | 启发 | ...
    # 第二列允许 **粗体**（override 规则在文档里用 **启发** 强调）
    LEVEL_CN = {"刚性": "error", "启发": "warn"}
    doc_rows = {}          # rid -> 文档声明的级别
    doc_section_rows = []  # (section, rid)
    section = ""
    for line in md.splitlines():
        sec = re.match(r"^##\s*(\d+)\.\s*(.+?规则|需求-设计对齐规则)", line)
        if sec:
            section = sec.group(1)
        row = re.match(r"^\|\s*([RH]\d{2})\s*\|\s*\**\s*(刚性|启发)\s*\**\s*\|", line)
        if row:
            doc_rows[row.group(1)] = LEVEL_CN[row.group(2)]
            doc_section_rows.append((section, row.group(1)))

    bad_doc_level = []
    for rid, want in doc_rows.items():
        if rid not in set(code_ids):
            continue  # 双向覆盖已有专门断言
        actual = R.level_of(rid)
        if actual != want:
            bad_doc_level.append((rid, want, actual))
    ok(f"文档明细表等级列与代码一致（{len(doc_rows)} 行）",
       not bad_doc_level, f"{bad_doc_level[:6]}")

    # 每节小计之和 == 明细表总行数（文档内部自洽）
    subtotal_decls = re.findall(r"\*\*小计\s*(\d+)\s*条\*\*", md)
    ok("各节小计之和 == 明细表总行数",
       sum(int(x) for x in subtotal_decls) == len(doc_rows),
       f"小计和 {sum(int(x) for x in subtotal_decls)} vs 表格行 {len(doc_rows)}")

    # ---------------- 3. 分级一致性 ----------------
    print("\n[3] 分级一致性（v1.3 起前缀≠等级，以 level_of 声明为准）")
    # v1.3 修正：前缀与等级是两个独立概念（R07/R13/R16 有意偏离），
    # "R 开头数 == 刚性数 / H 开头数 == 启发数"这两条旧断言与新设计矛盾，
    # 已删除。取而代之的语义：
    #   1) 按等级统计的刚性+启发 == 总数（下一条）
    #   2) 前缀偏离必须与 LEVEL_OVERRIDE 声明一致（本节末尾）
    ok("刚性+启发 == 总数",
       len(R.RIGID_IDS) + len(R.HEURISTIC_IDS) == len(code_ids))

    # v1.3 修正：分级不再由前缀推断（R07/R13/R16 教学审查后为启发级）。
    # 期望值来自 rules.level_of 显式声明；检查"声明"与"实际触发"一致。
    # 此前用空图跑规则，R07（需实体）/R13/R16（需连线）不产生 issue，
    # 三条"R 前缀 + warn"全部逃过检查——这是该检查的盲区。
    from model import Diagram
    from rules import RuleContext, level_of
    bad_level = []
    for rid, fn, _ in R.RULE_SPECS:
        want = level_of(rid)
        try:
            issues = fn(RuleContext(diagram=Diagram([], [])))
        except Exception:
            continue
        for it in issues or []:
            if it["level"] != want:
                bad_level.append((rid, it["level"], f"声明 {want}"))
    ok("空图可触发的规则 level 与声明一致", not bad_level, f"{bad_level[:5]}")

    # 需要实体/连线才触发的规则（空图跑不出），用最小触发用例验证。
    # 重点覆盖三条 override（R07/R13/R16）——它们正是前缀与等级偏离的规则。
    trigger_cases = {
        "R07": [ {"id": "e1", "shape": "rectangle", "label": "选课",
                  "attributes": ["*学号", "*课号"]}],
        "R13": [ {"id": "e1", "shape": "rectangle", "label": "学生",
                  "attributes": ["*学号"]},
                 {"id": "e2", "shape": "rectangle", "label": "研究生",
                  "attributes": ["*学号"]}],
        "R16": [ {"id": "e1", "shape": "rectangle", "label": "学生",
                  "attributes": ["*学号"]},
                 {"id": "e2", "shape": "rectangle", "label": "课程",
                  "attributes": ["*课程号"]}],
    }
    trigger_conns = {
        "R13": [ {"id": "c1", "from": "e1", "to": "e2", "type": "line",
                  "label": "", "cardinality": None}],
        "R16": [ {"id": "c1", "from": "e1", "to": "e2", "type": "line",
                  "label": "", "cardinality": "1"}],
    }
    for rid, els in trigger_cases.items():
        fn = R.RULE_SPECS[[r for r, _, _ in R.RULE_SPECS].index(rid)][1]
        try:
            issues = fn(RuleContext(diagram=Diagram(els, trigger_conns.get(rid, []))))
        except Exception as ex:
            ok(f"{rid} 触发用例可运行", False, repr(ex))
            continue
        hits = [it for it in issues or [] if it["rule_id"] == rid]
        if not hits:
            ok(f"{rid} 触发用例确实触发", False, "未触发，无法验证等级")
            continue
        want = level_of(rid)
        actual = {it["level"] for it in hits}
        ok(f"{rid} 实际 level 与声明一致（{want}）", actual == {want},
           f"声明 {want}，实际 {actual}")

    # 前缀偏离必须是**有意的**：偏离清单 == LEVEL_OVERRIDE 的键集
    deviations = {r for r in code_ids
                  if (r.startswith("R") and level_of(r) == "warn")
                  or (r.startswith("H") and level_of(r) == "error")}
    ok("前缀偏离清单与 LEVEL_OVERRIDE 一致",
       deviations == set(R.LEVEL_OVERRIDE),
       f"偏离 {sorted(deviations)} vs 声明 {sorted(R.LEVEL_OVERRIDE)}")
    print(f"       前缀偏离（有意）：{sorted(deviations)}")
    print(f"       刚性 {len(R.RIGID_IDS)} 条 / 启发 {len(R.HEURISTIC_IDS)} 条"
          f"（按实际等级统计）")

    # ---------------- 4. 无死代码 ----------------
    print("\n[4] 死代码检查")
    src = (HERE / "rules.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.startswith("rule_")}
    registered = {fn.__name__ for _, fn, _ in R.RULE_SPECS}
    ok("不存在未注册的 rule_ 函数", defined == registered,
       f"未注册: {sorted(defined - registered)}")

    # 规则必须至少挂在一个事件上
    no_event = [rid for rid, _, evs in R.RULE_SPECS if not evs]
    ok("每条规则至少挂 1 个事件", not no_event, f"{no_event}")

    # 挂的事件必须是合法事件名
    valid_events = {"element_added", "element_modified", "element_deleted",
                    "connection_added", "connection_modified", "*"}
    bad_ev = [(rid, e) for rid, _, evs in R.RULE_SPECS for e in evs
              if e not in valid_events]
    ok("无非法事件名", not bad_ev, f"{bad_ev[:5]}")

    # ---------------- 5. 字典树自检 ----------------
    print("\n[5] 字典树自检")
    st = TRIE.stats()
    ok("trie 规则数 == 注册规则数", st["total_rules"] == len(code_ids),
       f"trie={st['total_rules']} 注册={len(code_ids)}")
    ok("trie 单事件最多命中 < 总数（非全量扫描）",
       st["max_per_event"] < st["total_rules"],
       f"max={st['max_per_event']} total={st['total_rules']}")

    # ---------------- 6. README 命令指向真实文件 ----------------
    print("\n[6] README 中的脚本引用")
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    # 两种引用方式都要认：`python xxx.py` 命令 与 `xxx.py` 反引号提及
    # 文件名可含数字（如 e2e.py），故用 \w 而非 [a-z_]
    refs = set(re.findall(r"python\s+(\w+\.py)", readme))
    refs |= set(re.findall(r"`(\w+\.py)`", readme))
    for f in sorted(refs):
        ok(f"README 引用的 {f} 存在", (HERE / f).exists())
    # 反向：目录里的 py 是否都被 README 提及
    on_disk = {p.name for p in HERE.glob("*.py")}
    unmentioned = on_disk - refs
    ok("目录中所有脚本都在 README 有说明", not unmentioned,
       f"未提及: {sorted(unmentioned)}")

    # ---------------- 7. 文档中引用的审计脚本名正确 ----------------
    print("\n[7] 审计脚本清单")
    for name in ["audit_rules.py", "audit_falsepos.py", "audit_robust.py",
                 "audit_protocol.py", "audit_concurrent.py"]:
        ok(f"{name} 存在", (HERE / name).exists())

    print("\n" + "=" * 68)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _problems:
        print("  问题清单：")
        for p in _problems:
            print(f"    - {p}")
    print("=" * 68)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
