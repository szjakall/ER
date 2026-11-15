# -*- coding: utf-8 -*-
"""
ER 规则引擎单元测试
===================

运行： python test_engine.py

覆盖：
    1) 每条规则至少 1 个触发用例
    2) 字典树索引正确性（非全量扫描）
    3) 协议组包形状正确（violations/suggestions 分数组）
    4) 会话缓存与批量检查
"""

from __future__ import annotations

# 测试模式：避免测试数据写入生产学情日志（weakness_log.jsonl）
import os as _os
_os.environ.setdefault("ER_TESTING", "1")

import sys

from engine import (
    ENGINE,
    Session,
    check_batch,
    check_single,
    select_rules,
    TRIE,
    RULE_FN_BY_ID,
)
from rules import HEURISTIC_IDS, RIGID_IDS, RULE_IDS, RULE_SPECS

_passed = 0
_failed = 0
_failures: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        _failures.append(name)
        print(f"  [FAIL] {name} {detail}")


# ----------------------------------------------------------------------
# 构造helper
# ----------------------------------------------------------------------

def el(eid, shape, label, attrs=None, is_weak=False):
    return {"id": eid, "shape": shape, "label": label,
            "attributes": attrs or [], "is_weak": is_weak}


def conn(cid, frm, to, ctype="line", label="", card=None):
    return {"id": cid, "from": frm, "to": to, "type": ctype,
            "label": label, "cardinality": card}


def run(event, msg, session=None):
    """跑一次单事件检查。"""
    s = session or Session()
    return check_single(s, msg), s


def batch(elements, connections, req=""):
    s = Session()
    msg = {"action": "batch_check",
           "diagram": {"elements": elements, "connections": connections}}
    if req:
        msg["requirement_text"] = req
    return check_batch(s, msg)


def rule_ids(resp) -> set:
    """收集回包里所有 rule_id（不分 violations/suggestions）。"""
    ids = set()
    for k in ("violations", "suggestions"):
        for it in resp.get(k, []):
            ids.add(it["rule_id"])
    return ids


def level_of(resp, rule_id: str):
    """
    取某条规则在回包中的等级（error / warn），未出现则 None。

    为什么需要它：早期断言只查 `rule_id in ids`，**不看等级**。
    结果是把规则从 error 降为 warn 时，测试依然是绿的——
    等级回归（红↔橙错位，直接影响前端标色）不会被发现。
    """
    for k, lvl in (("violations", "error"), ("suggestions", "warn")):
        for it in resp.get(k, []):
            if it["rule_id"] == rule_id:
                return it["level"]
    return None


def batch_level_of(resp, rule_id: str):
    """批量回包里取某规则的等级（取任一出现处）。"""
    for v in resp.get("results", {}).values():
        for k, lvl in (("violations", "error"), ("suggestions", "warn")):
            for it in v.get(k, []):
                if it["rule_id"] == rule_id:
                    return it["level"]
    return None


def batch_rule_ids(resp) -> set:
    ids = set()
    for v in resp.get("results", {}).values():
        for k in ("violations", "suggestions"):
            for it in v.get(k, []):
                ids.add(it["rule_id"])
    return ids


# ======================================================================
# 一、字典树 / 索引
# ======================================================================

def test_trie() -> None:
    print("\n[字典树索引]")
    total = len(RULE_IDS)
    ok("规则总数 >= 35", total >= 35, f"实际 {total}")

    st = TRIE.stats()
    ok("统计总规则数与注册表一致", st["total_rules"] == total,
       f"trie={st['total_rules']} spec={total}")

    # 非全量扫描：单事件命中数必须小于总数
    n_added = len(select_rules("element_added", has_full_graph=False))
    ok("element_added 只跑子集（不含通配）", n_added < total,
       f"{n_added}/{total}")
    ok("element_added 命中 16 条", n_added == 16, f"实际 {n_added}")

    n_conn = len(select_rules("connection_added", has_full_graph=False))
    ok("connection_added 命中 13 条", n_conn == 13, f"实际 {n_conn}")

    # 通配（图结构级）只在有全图快照时放行
    with_full = len(select_rules("element_added", has_full_graph=True))
    ok("有全图时追加通配规则", with_full > n_added, f"{n_added} -> {with_full}")

    # 字典树查找 O(len(event))：不存在的事件本身没有挂载规则
    ok("未知事件本身无规则", TRIE.match("no_such_event") == [])
    # 但通配分支（图结构级）仍会在有全图快照时生效——这是设计如此
    ok("未知事件+全图 → 仅含通配规则",
       select_rules("no_such_event", True) == select_rules("*", True))

    # 去重：同一规则挂在多事件上，单次查询不重复
    fns = select_rules("connection_added", has_full_graph=True)
    ok("单次查询规则不重复", len(fns) == len({id(f) for f in fns}))


# ======================================================================
# 二、每条规则至少一个触发用例
# ======================================================================

def test_each_rule() -> None:
    print("\n[逐条规则触发]")

    # 基础：一个"两面"图，含两个实体+一个联系（菱形）+两条分支线
    def base(weak=False, pk=True, rel_label="选修", branch2_card="N"):
        e1 = el("e1", "rectangle", "学生", ["*学号", "姓名"] if pk else ["姓名"])
        e2 = el("e2", "rectangle", "课程", ["*课程号"])
        d = el("d1", "diamond", rel_label)
        return [e1, e2, d], [
            conn("c1", "e1", "d1", "diamond_line", "", "1"),
            conn("c2", "e2", "d1", "diamond_line", "", branch2_card),
        ]

    # --- R01 元素无名 ---
    r = batch([el("e1", "rectangle", "", ["*a"]), el("e2", "rectangle", "B", ["*b"])],
              [])
    ok("R01 元素无名称", "R01" in batch_rule_ids(r))

    # --- R02 实体缺主键 ---
    r = batch([el("e1", "rectangle", "学生", ["姓名"]),
               el("e2", "rectangle", "课程", ["*课程号"])],
              [conn("c1", "e1", "e2", "diamond_line", "", "1")])
    ok("R02 实体缺主键", "R02" in batch_rule_ids(r))

    # --- R03 属性无名 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号"]), el("a1", "ellipse", "")], [])
    ok("R03 属性无名", "R03" in batch_rule_ids(r))

    # --- R04 联系无名 ---
    es, cs = base(rel_label="")
    ok("R04 联系无名", "R04" in batch_rule_ids(batch(es, cs)))

    # --- R05 弱实体缺部分键 ---
    es, cs = base()
    es[0]["is_weak"] = True   # 学生 变弱实体，但没有 # 属性
    ok("R05 弱实体缺部分键", "R05" in batch_rule_ids(batch(es, cs)))

    # --- R06 空白属性名 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "  "]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("R06 空白属性名", "R06" in batch_rule_ids(r))

    # --- R07 多个主键（复选为启发级：复合主键是合法建模）---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "*姓名"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("R07 多主键提示", "R07" in batch_rule_ids(r))
    ok("R07 为启发级(橙色)——复合主键合法，不应判红",
       batch_level_of(r, "R07") == "warn", f"实际 {batch_level_of(r, 'R07')}")

    # --- R08 属性重名 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "姓名", "姓名"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("R08 属性重名", "R08" in batch_rule_ids(r))

    # --- R09 属性名与实体名相同 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "学生"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("R09 属性名同实体名", "R09" in batch_rule_ids(r))

    # --- R10 悬空连线 ---
    es, cs = base()
    cs.append(conn("c9", "e1", "e999", "diamond_line", "", "1"))
    ok("R10 悬空连线", "R10" in batch_rule_ids(batch(es, cs)))

    # --- R11 自环 ---
    es, cs = base()
    cs.append(conn("c8", "e1", "e1"))
    ok("R11 自环连线", "R11" in batch_rule_ids(batch(es, cs)))

    # --- R12 重复连线 ---
    es, cs = base()
    cs.append(conn("c7", "e1", "d1", "diamond_line", "", "1"))  # 与 c1 重复
    ok("R12 重复连线", "R12" in batch_rule_ids(batch(es, cs)))

    # --- R13 实体间直接连线（启发级：ISA 继承也这样画）---
    es, cs = base()
    cs.append(conn("c6", "e1", "e2", "line"))
    r13 = batch(es, cs)
    ok("R13 实体直接连线提示", "R13" in batch_rule_ids(r13))
    ok("R13 为启发级(橙色)——ISA 直连是合法画法",
       batch_level_of(r13, "R13") == "warn",
       f"实际 {batch_level_of(r13, 'R13')}")

    # --- R14 分支线缺基数 ---
    es, cs = base(branch2_card=None)
    ok("R14 分支线缺基数", "R14" in batch_rule_ids(batch(es, cs)))

    # --- R15 非法基数 ---
    es, cs = base()
    cs[0]["cardinality"] = "X"
    ok("R15 非法基数", "R15" in batch_rule_ids(batch(es, cs)))

    # --- R16 普通连线标了基数（启发级：属操作失误，非模型错误）---
    es, cs = base()
    cs.append(conn("c5", "e1", "e2", "line", "", "1"))
    r16 = batch(es, cs)
    ok("R16 普通连线带基数提示", "R16" in batch_rule_ids(r16))
    ok("R16 为启发级(橙色)——基数写错位置不损坏模型",
       batch_level_of(r16, "R16") == "warn",
       f"实际 {batch_level_of(r16, 'R16')}")

    # --- R17 联系缺基数（图级）---
    es, cs = base(branch2_card=None)
    ok("R17 联系缺基数", "R17" in batch_rule_ids(batch(es, cs)))

    # --- R18 联系只连 1 个实体 ---
    es, cs = base()
    cs = [cs[0]]   # 只留一条分支线
    ok("R18 联系连接不足", "R18" in batch_rule_ids(batch(es, cs)))

    # --- R19 孤立菱形 ---
    es, cs = base()
    cs = []
    ok("R19 孤立菱形", "R19" in batch_rule_ids(batch(es, cs)))

    # --- R20 联系重名 ---
    es, cs = base()
    es.append(el("d2", "diamond", "选修"))
    ok("R20 联系重名", "R20" in batch_rule_ids(batch(es, cs)))

    # --- R21 实体重名 ---
    es, cs = base()
    es.append(el("e3", "rectangle", "学生", ["*学号"]))
    ok("R21 实体重名", "R21" in batch_rule_ids(batch(es, cs)))

    # --- R22 无实体 ---
    r = batch([el("d1", "diamond", "联系")], [])
    ok("R22 无实体", "R22" in batch_rule_ids(r))

    # --- H01 复数实体名 ---
    r = batch([el("e1", "rectangle", "学生们", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H01 复数实体名", "H01" in batch_rule_ids(r))

    # --- H02 联系名非动词 ---
    es, cs = base(rel_label="东西")
    ok("H02 联系名非动词", "H02" in batch_rule_ids(batch(es, cs)))

    # --- H03 多值属性 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "电话"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H03 多值属性", "H03" in batch_rule_ids(r))

    # --- H04 派生属性 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "年龄"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H04 派生属性", "H04" in batch_rule_ids(r))

    # --- H05 中英混用 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "name"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H05 命名风格混用", "H05" in batch_rule_ids(r))

    # --- H06 属性过多 ---
    many = ["*id"] + [f"属性{i}" for i in range(13)]
    r = batch([el("e1", "rectangle", "大表", many),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H06 属性过多", "H06" in batch_rule_ids(r))

    # --- H07 名称含空格/特殊字符 ---
    r = batch([el("e1", "rectangle", "学 生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H07 名称含空格", "H07" in batch_rule_ids(r))

    # --- H08 名称过长 ---
    r = batch([el("e1", "rectangle", "这是一个非常非常长的实体名称超过二十个字符限制",
                  ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H08 名称过长", "H08" in batch_rule_ids(r))

    # --- H09 实体间 diamond_line ---
    es, cs = base()
    cs.append(conn("c4", "e1", "e2", "diamond_line", "", "M"))
    ok("H09 实体间diamond_line", "H09" in batch_rule_ids(batch(es, cs)))

    # --- H10 属性归属方向 ---
    es, cs = base()
    es.append(el("a1", "ellipse", "电话"))
    cs.append(conn("c3", "e1", "a1"))   # 实体 -> 属性（建议反过来）
    ok("H10 属性归属方向", "H10" in batch_rule_ids(batch(es, cs)))

    # --- H11 联系只连一条分支 ---
    es, cs = base()
    cs = [cs[0]]
    ok("H11 分支线不齐", "H11" in batch_rule_ids(batch(es, cs)))

    # --- H12 孤立实体 ---
    es, cs = base()
    es.append(el("e9", "rectangle", "孤立", ["*id"]))
    ok("H12 孤立实体", "H12" in batch_rule_ids(batch(es, cs)))

    # --- H13 多实体无联系 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H13 多实体无联系", "H13" in batch_rule_ids(r))

    # --- H14 联系各端基数均 1 ---
    es, cs = base(branch2_card="1")
    ok("H14 各端基数均1", "H14" in batch_rule_ids(batch(es, cs)))

    # --- H15 三元联系基数可疑 ---
    e3 = el("e3", "rectangle", "教师", ["*工号"])
    d = el("d1", "diamond", "讲授")
    cs2 = [
        conn("c1", "e1", "d1", "diamond_line", "", "M"),
        conn("c2", "e2", "d1", "diamond_line", "", "N"),
        conn("c3", "e3", "d1", "diamond_line", "", "N"),
    ]
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"]), e3, d], cs2)
    ok("H15 三元基数可疑", "H15" in batch_rule_ids(r))

    # --- H16 仅一个属性 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])], [])
    ok("H16 属性偏少", "H16" in batch_rule_ids(r))

    # --- H17 图规模过小 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号"])], [])
    ok("H17 图规模过小", "H17" in batch_rule_ids(r))

    # --- H18/H19/H20/H21 需求对齐 ---
    r = batch([el("e1", "rectangle", "学生", ["*学号", "姓名"]),
               el("e2", "rectangle", "课程", ["*课程号"])],
              [conn("c1", "e1", "e2", "diamond_line", "", "1")],
              req="教师可以授课，学生可以选修课程，需要记录成绩")
    ids = batch_rule_ids(r)
    ok("H18 需求实体未覆盖（教师）", "H18" in ids)
    ok("H19 需求联系未覆盖", "H19" in ids)
    ok("H20 需求属性未覆盖（成绩）", "H20" in ids)


# ======================================================================
# 二·补、教学正确性回归（第二轮独立教学审查发现的问题）
# ======================================================================

def test_teaching_fixes() -> None:
    """覆盖 7 项教学正确性修复，防止日后回退。"""
    print("\n[教学正确性回归]")

    # (1) 递归（一元）联系不应被判为重复连线
    #     教材必讲："员工—管理—员工"，两条分支线端点对相同、基数不同
    els = [el("e1", "rectangle", "员工", ["*工号"]),
           el("d1", "diamond", "管理")]
    cons = [conn("c1", "e1", "d1", "diamond_line", "", "1"),
            conn("c2", "e1", "d1", "diamond_line", "", "N")]
    r = batch(els, cons)
    ok("递归联系两条分支线不被判重复（R12）", "R12" not in batch_rule_ids(r),
       f"实际 {sorted(batch_rule_ids(r))}")
    # 真正重复（基数也相同）仍应被抓
    cons_dup = [conn("c1", "e1", "d1", "diamond_line", "", "1"),
                conn("c2", "e1", "d1", "diamond_line", "", "1")]
    ok("完全相同的连线仍判重复（R12）",
       "R12" in batch_rule_ids(batch(els, cons_dup)))

    # (2) 复合主键是合法建模，不应判红
    r = batch([el("e1", "rectangle", "选课", ["*学号", "*课号", "成绩"]),
               el("e2", "rectangle", "学生", ["*学号"])], [])
    ok("复合主键不判红（R07 为启发级）",
       batch_level_of(r, "R07") == "warn",
       f"实际 {batch_level_of(r, 'R07')}")

    # (3) ISA 直接连线是合法画法，不应判红
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "研究生", ["*学号", "导师"])],
              [conn("c1", "e1", "e2", "line")])
    ok("ISA 直连不判红（R13 为启发级）",
       batch_level_of(r, "R13") == "warn",
       f"实际 {batch_level_of(r, 'R13')}")

    # (4) 弱实体同时标 * 与 # —— 概念混淆，必须抓（此前漏报）
    r = batch([el("e1", "rectangle", "亲属", ["#称呼", "*编号", "姓名"],
                  is_weak=True),
               el("e2", "rectangle", "职工", ["*工号"])], [])
    ok("弱实体同时标主键与部分键被抓（R05）",
       "R05" in batch_rule_ids(r), f"实际 {sorted(batch_rule_ids(r))}")

    # (5) 多级弱实体：弱实体依赖弱实体，再依赖强实体
    els = [el("s", "rectangle", "职工", ["*工号"]),
           el("w1", "rectangle", "亲属", ["#称呼"], is_weak=True),
           el("w2", "rectangle", "子女", ["#姓名"], is_weak=True),
           el("d1", "diamond", "具有"), el("d2", "diamond", "拥有")]
    cons = [conn("c1", "s", "d1", "diamond_line", "", "1"),
            conn("c2", "d1", "w1", "diamond_line", "", "N"),
            conn("c3", "w1", "d2", "diamond_line", "", "1"),
            conn("c4", "d2", "w2", "diamond_line", "", "N")]
    ok("多级弱实体不误报（R23）", "R23" not in batch_rule_ids(batch(els, cons)))
    # 反向：真孤立弱实体仍须报
    ok("孤立弱实体仍报（R23）",
       "R23" in batch_rule_ids(batch(
           [el("w", "rectangle", "孤儿", ["#a"], is_weak=True),
            el("s", "rectangle", "强", ["*b"])], [])))

    # (6) 基数缺失不应重复报 3 条（R14 与 R17 去重）
    els = [el("e1", "rectangle", "学生", ["*学号"]),
           el("e2", "rectangle", "课程", ["*课程号"]),
           el("d1", "diamond", "选修")]
    cons = [conn("c1", "e1", "d1", "diamond_line", "", None),
            conn("c2", "e2", "d1", "diamond_line", "", None)]
    r = batch(els, cons)
    n_missing = sum(
        1 for v in r["results"].values()
        for it in v["violations"] if it["rule_id"] in ("R14", "R17"))
    ok("整条联系缺基数只报 1 条（不重复刷屏）", n_missing <= 1,
       f"实际 {n_missing} 条")
    ok("图结构级 R17 负责汇报", "R17" in batch_rule_ids(r))

    # (7) 基数写错位置是操作失误，应为启发级
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])],
              [conn("c1", "e1", "e2", "line", "", "1")])
    ok("普通线标基数为启发级（R16）",
       batch_level_of(r, "R16") == "warn",
       f"实际 {batch_level_of(r, 'R16')}")

    # (8) 焦点过滤不得吞掉"挂在别的元素上的新问题"（真实缺陷回归）
    #     场景：把 e2 改名成与 e1 同名 → R21 报在 e1 上，
    #     但学生编辑的是 e2；早期实现只留 target_id==e2，导致重名警告丢失。
    s = Session()
    check_single(s, {"action": "check", "event": "element_added",
                     "element": el("e1", "rectangle", "学生", ["*学号"])})
    check_single(s, {"action": "check", "event": "element_added",
                     "element": el("e2", "rectangle", "课程", ["*课程号"])})
    r = check_single(s, {
        "action": "check", "event": "element_modified",
        "element": el("e2", "rectangle", "学生", ["*课程号"]),
        "changes": {"label_changed": True, "attributes_changed": False}})
    vids = {v["rule_id"] for v in r["violations"]}
    ok("改名造成重名能被回传（R21 不被焦点过滤吞掉）", "R21" in vids,
       f"实际 {vids}")
    # 同一问题重复发送不应反复刷屏
    r2 = check_single(s, {
        "action": "check", "event": "element_modified",
        "element": el("e2", "rectangle", "学生", ["*课程号"]),
        "changes": {"label_changed": True, "attributes_changed": False}})
    ok("已存在的问题不重复刷屏",
       "R21" not in {v["rule_id"] for v in r2["violations"]},
       f"实际 {[v['rule_id'] for v in r2['violations']]}")


# ======================================================================
# 三、规则计数与分级
# ======================================================================

def test_registry() -> None:
    print("\n[规则注册表]")
    ok("规则数 >= 35", len(RULE_IDS) >= 35, f"实际 {len(RULE_IDS)}")
    ok("编号唯一", len(RULE_IDS) == len(set(RULE_IDS)))
    # v1.3：前缀≠等级（R07/R13/R16 为启发级），断言改为验证
    # "偏离集 == LEVEL_OVERRIDE 声明"，防止无意偏离混入。
    from rules import level_of, LEVEL_OVERRIDE
    devs = {r for r in RULE_IDS
            if (r.startswith("R") and level_of(r) == "warn")
            or (r.startswith("H") and level_of(r) == "error")}
    ok("前缀偏离集与 LEVEL_OVERRIDE 一致",
       devs == set(LEVEL_OVERRIDE),
       f"偏离 {sorted(devs)} vs 声明 {sorted(LEVEL_OVERRIDE)}")
    ok("刚性+启发 == 总数", len(RIGID_IDS) + len(HEURISTIC_IDS) == len(RULE_IDS))
    ok("每条规则至少挂 1 个事件",
       all(evs for _, _, evs in RULE_SPECS))
    print(f"       按实际等级：刚性 {len(RIGID_IDS)} 条；启发 {len(HEURISTIC_IDS)} 条"
          f"（含前缀偏离 {sorted(LEVEL_OVERRIDE)}）")


# ======================================================================
# 四、协议组包
# ======================================================================

def test_protocol() -> None:
    print("\n[协议组包]")

    # 单次检查
    s = Session()
    resp = check_single(s, {
        "action": "check", "event": "element_added",
        "element": el("e1", "rectangle", "学生", ["姓名"]),
    })
    ok("result 有 action", resp.get("action") == "result")
    ok("result 有 element_id", resp.get("element_id") == "e1")
    ok("result 有 violations 数组", isinstance(resp.get("violations"), list))
    ok("result 有 suggestions 数组", isinstance(resp.get("suggestions"), list))
    ok("violations 全为 level=error",
       all(i["level"] == "error" for i in resp["violations"]))
    ok("suggestions 全为 level=warn",
       all(i["level"] == "warn" for i in resp["suggestions"]))
    ok("issue 三字段齐全",
       all({"rule_id", "level", "message"} <= set(i) for i in
           resp["violations"] + resp["suggestions"]))

    # 批量检查
    r = batch([el("e1", "rectangle", "学生", ["*学号"]),
               el("e2", "rectangle", "课程", ["*课程号"])],
              [conn("c1", "e1", "e2", "diamond_line", "", "1")])
    ok("batch_result 有 action", r.get("action") == "batch_result")
    ok("batch_result.results 覆盖全部元素与连线",
       set(r["results"]) == {"e1", "e2", "c1"}, f"实际 {set(r['results'])}")
    ok("每条结果含 violations/suggestions",
       all({"violations", "suggestions"} <= set(v) for v in r["results"].values()))

    # 图级提示只由一个元素承载（v1.5 修复回归）
    # 旧实现把 target_id 为空的图级提示分发给所有元素，
    # 200 元素图实测复制 600 条 → 前端面板刷屏。
    r = batch([el(f"e{i}", "rectangle", f"实体{i}", ["*学号", "姓名"])
               for i in range(50)], [])
    h13 = [eid for eid, v in r["results"].items()
           if any(i["rule_id"] == "H13" for i in v["suggestions"])]
    ok("图级提示（H13）只承载于 1 个元素", len(h13) == 1,
       f"实际 {len(h13)} 个元素承载")
    ok("承载元素确实是图内元素（前端能消费）",
       bool(h13) and h13[0] in r["results"])

    # 错误响应
    resp = ENGINE.handle("t-err", {"action": "check", "event": "element_added",
                                   "element": {"id": "x", "shape": "rectangle",
                                               "attributes": "not-a-list"}})
    ok("attributes 非数组 → error", resp.get("action") == "error")
    resp = ENGINE.handle("t-err2", {"action": "check", "event": "bogus"})
    ok("未知事件 → error", resp.get("action") == "error")
    resp = ENGINE.handle("t-err3", {"action": "bogus"})
    ok("未知 action → error", resp.get("action") == "error")


# ======================================================================
# 五、会话缓存
# ======================================================================

def test_session() -> None:
    print("\n[会话缓存]")
    s = Session()
    # 建两个实体
    check_single(s, {"action": "check", "event": "element_added",
                     "element": el("e1", "rectangle", "学生", ["*学号"])})
    check_single(s, {"action": "check", "event": "element_added",
                     "element": el("e2", "rectangle", "课程", ["*课程号"])})
    ok("缓存了两个实体", len(s.elements) == 2, f"实际 {len(s.elements)}")

    # 加联系菱形
    check_single(s, {"action": "check", "event": "element_added",
                     "element": el("d1", "diamond", "选修")})
    check_single(s, {"action": "check", "event": "connection_added",
                     "connection": conn("c1", "e1", "d1", "diamond_line", "", "1")})
    ok("缓存了连线", len(s.connections) == 1)

    # 删除实体应连带清理其连线
    check_single(s, {"action": "check", "event": "element_deleted",
                     "element": el("e1", "rectangle", "学生", ["*学号"])})
    ok("删除元素后清理其连线", len(s.connections) == 0,
       f"实际 {len(s.connections)}")
    ok("删除元素后元素减少", "e1" not in s.elements)

    # 会话隔离
    a = ENGINE.session("iso-a")
    b = ENGINE.session("iso-b")
    ok("会话彼此隔离", a is not b)
    ENGINE.drop_session("iso-a")
    ENGINE.drop_session("iso-b")


# ======================================================================
# 主入口
# ======================================================================

def main() -> int:
    print("=" * 64)
    print(f"  ER 规则引擎测试（{len(RULE_IDS)} 条规则）")
    print("=" * 64)

    test_trie()
    test_registry()
    test_each_rule()
    test_teaching_fixes()
    test_protocol()
    test_session()

    print("\n" + "=" * 64)
    print(f"  结果：{_passed} 通过，{_failed} 失败")
    if _failures:
        print("  失败项：")
        for f in _failures:
            print(f"    - {f}")
    print("=" * 64)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
