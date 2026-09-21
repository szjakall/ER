# -*- coding: utf-8 -*-
"""
ER 概念设计规则库（32 条规则）
================================
分类：
  A. 实体规则      R01-R08  (8 条)
  B. 属性规则      R09-R15  (7 条)
  C. 联系规则      R16-R23  (8 条)
  D. 结构/全局规则  R24-R28  (5 条)
  E. 需求对齐规则   R29-R32  (4 条)

每条规则 = 一个函数：输入 er_data (dict)，输出 [error_dict, ...]
新增规则三步：
  1) 写一个 rule_RXX(er_data) 函数
  2) 加到 ALL_RULES 列表
  3) 在规则清单.md 里登记
"""

import json
import os

# ======================================================================
# 同义词表（需求对齐用）
# 可用 synonyms.json 覆盖，文件不存在时使用内置表
# ======================================================================

_SYNONYMS = {
    "学生": ["学员", "学生", "student"],
    "教师": ["老师", "教职工", "教师", "teacher"],
    "课程": ["课程", "课", "course"],
    "学院": ["学院", "院系", "department"],
    "班级": ["班级", "班", "class"],
}

_REL_SYNONYMS = {
    "选课": ["选课", "选修", "选课登记"],
    "授课": ["授课", "讲授", "教学"],
    "考试": ["考试", "测验", "考核"],
    "归属": ["归属", "属于", "隶属"],
}

_ATTR_SYNONYMS = {
    "学号": ["学号", "学生编号", "student_id"],
    "姓名": ["姓名", "名字", "name"],
    "成绩": ["成绩", "分数", "score"],
    "课程号": ["课程号", "课程编号", "course_id"],
    "课程名": ["课程名", "课程名称", "course_name"],
}


def _load_synonyms():
    """从 synonyms.json 加载同义词表，文件不存在则用内置表"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synonyms.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _SYNONYMS


# ======================================================================
# 错误对象工厂
# ======================================================================

def _err(rule_id, level, target_type, target_id, message):
    """统一的错误返回结构，前端按此渲染标红/标橙"""
    return {
        "rule_id": rule_id,
        "level": level,              # "error" 或 "warning"
        "target_type": target_type,  # "entity" / "attribute" / "relationship" / "graph"
        "target_id": target_id,
        "message": message,
    }


# ======================================================================
# A. 实体规则 (R01-R08)
# ======================================================================

def rule_R01(er_data):
    """R01: 实体必须有名称 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        if not (e.get("name") or "").strip():
            errors.append(_err("R01", "error", "entity", e.get("id", ""),
                               "存在未命名的实体"))
    return errors


def rule_R02(er_data):
    """R02: 实体名必须唯一 (error)"""
    errors = []
    seen = {}
    for e in er_data.get("entities", []):
        name = (e.get("name") or "").strip()
        if name:
            seen.setdefault(name, []).append(e.get("id", ""))
    for name, ids in seen.items():
        if len(ids) > 1:
            errors.append(_err("R02", "error", "entity", ids[0],
                               f"实体名「{name}」重复出现 {len(ids)} 次，实体名必须唯一"))
    return errors


def rule_R03(er_data):
    """R03: 非弱实体必须有主键 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        if e.get("is_weak"):
            continue
        attrs = e.get("attributes", [])
        has_pk = any(a.get("is_primary_key") for a in attrs)
        if not has_pk:
            errors.append(_err("R03", "error", "entity", e.get("id", ""),
                               f"实体「{e.get('name', '未命名')}」缺少主键属性"))
    return errors


def rule_R04(er_data):
    """R04: 非弱实体至少有一个属性 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        if e.get("is_weak"):
            continue
        if not e.get("attributes"):
            errors.append(_err("R04", "error", "entity", e.get("id", ""),
                               f"实体「{e.get('name', '未命名')}」没有任何属性"))
    return errors


def rule_R05(er_data):
    """R05: 弱实体必须有部分键/鉴别器 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        if not e.get("is_weak"):
            continue
        attrs = e.get("attributes", [])
        has_partial = any(a.get("is_partial_key") for a in attrs)
        if not has_partial:
            errors.append(_err("R05", "error", "entity", e.get("id", ""),
                               f"弱实体「{e.get('name', '未命名')}」缺少部分键（鉴别器属性）"))
    return errors


def rule_R06(er_data):
    """R06: 主键不能是多值属性 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            if a.get("is_primary_key") and a.get("is_multi_valued"):
                errors.append(_err("R06", "error", "entity", e.get("id", ""),
                                   f"实体「{e.get('name', '未命名')}」的主键「{a.get('name', '')}」不能是多值属性"))
    return errors


def rule_R07(er_data):
    """R07: 主键不能是派生属性 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            if a.get("is_primary_key") and a.get("is_derived"):
                errors.append(_err("R07", "error", "entity", e.get("id", ""),
                                   f"实体「{e.get('name', '未命名')}」的主键「{a.get('name', '')}」不能是派生属性"))
    return errors


def rule_R08(er_data):
    """R08: 孤立实体检测 (warning)"""
    linked = set()
    for r in er_data.get("relationships", []):
        linked.add(r.get("from_entity"))
        linked.add(r.get("to_entity"))
    errors = []
    for e in er_data.get("entities", []):
        if e.get("id") not in linked:
            errors.append(_err("R08", "warning", "entity", e.get("id", ""),
                               f"实体「{e.get('name', '未命名')}」未参与任何联系，可能是孤立实体"))
    return errors


# ======================================================================
# B. 属性规则 (R09-R15)
# ======================================================================

def rule_R09(er_data):
    """R09: 属性必须有名称 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            if not (a.get("name") or "").strip():
                errors.append(_err("R09", "error", "attribute", e.get("id", ""),
                                   f"实体「{e.get('name', '未命名')}」下有属性缺少名称"))
    for r in er_data.get("relationships", []):
        for a in r.get("attributes", []):
            if not (a.get("name") or "").strip():
                errors.append(_err("R09", "error", "attribute", r.get("id", ""),
                                   f"联系「{r.get('name', '未命名')}」下有属性缺少名称"))
    return errors


def rule_R10(er_data):
    """R10: 同一实体内属性名不能重复 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        seen = {}
        for a in e.get("attributes", []):
            name = (a.get("name") or "").strip()
            if name:
                seen.setdefault(name, []).append(a)
        for name, attrs in seen.items():
            if len(attrs) > 1:
                errors.append(_err("R10", "error", "attribute", e.get("id", ""),
                                   f"实体「{e.get('name', '未命名')}」中属性「{name}」重复"))
    return errors


def rule_R11(er_data):
    """R11: 主键属性不允许为空 (error)"""
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            if a.get("is_primary_key") and a.get("is_nullable", True):
                errors.append(_err("R11", "error", "attribute", e.get("id", ""),
                                   f"实体「{e.get('name', '未命名')}」的主键「{a.get('name', '')}」不允许为空（nullable）"))
    return errors


def rule_R12(er_data):
    """R12: 复合属性必须有子属性 (warning)"""
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            if a.get("is_composite") and not a.get("sub_attributes"):
                errors.append(_err("R12", "warning", "attribute", e.get("id", ""),
                                   f"复合属性「{a.get('name', '')}」未定义子属性"))
    return errors


def rule_R13(er_data):
    """R13: 属性名不应与所属实体名相同 (warning)"""
    errors = []
    for e in er_data.get("entities", []):
        ent_name = (e.get("name") or "").strip()
        for a in e.get("attributes", []):
            if (a.get("name") or "").strip() == ent_name and ent_name:
                errors.append(_err("R13", "warning", "attribute", e.get("id", ""),
                                   f"实体「{ent_name}」的属性名与实体名相同，建议区分"))
    return errors


def rule_R14(er_data):
    """R14: 疑似派生属性未标记 (warning)"""
    keywords = ["总计", "平均", "汇总", "合计", "总数", "余额", "排名"]
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            name = a.get("name", "")
            if any(kw in name for kw in keywords) and not a.get("is_derived"):
                errors.append(_err("R14", "warning", "attribute", e.get("id", ""),
                                   f"属性「{name}」可能是派生属性，建议标记 is_derived=true"))
    return errors


def rule_R15(er_data):
    """R15: 疑似多值属性未标记 (warning)"""
    keywords = ["列表", "集合", "多个", "系列", "一组"]
    errors = []
    for e in er_data.get("entities", []):
        for a in e.get("attributes", []):
            name = a.get("name", "")
            if any(kw in name for kw in keywords) and not a.get("is_multi_valued"):
                errors.append(_err("R15", "warning", "attribute", e.get("id", ""),
                                   f"属性「{name}」可能是多值属性，建议标记 is_multi_valued=true"))
    return errors


# ======================================================================
# C. 联系规则 (R16-R23)
# ======================================================================

def rule_R16(er_data):
    """R16: 联系必须有名称 (error)"""
    errors = []
    for r in er_data.get("relationships", []):
        if not (r.get("name") or "").strip():
            errors.append(_err("R16", "error", "relationship", r.get("id", ""),
                               "存在未命名的联系"))
    return errors


def rule_R17(er_data):
    """R17: 联系必须标注基数 (error)"""
    errors = []
    for r in er_data.get("relationships", []):
        if not (r.get("cardinality") or "").strip():
            errors.append(_err("R17", "error", "relationship", r.get("id", ""),
                               f"联系「{r.get('name', '未命名')}」缺少基数标注"))
    return errors


def rule_R18(er_data):
    """R18: 联系基数必须是合法值 (error)"""
    valid = {"1:1", "1:N", "M:N"}
    errors = []
    for r in er_data.get("relationships", []):
        card = (r.get("cardinality") or "").strip().upper()
        if card and card not in valid:
            errors.append(_err("R18", "error", "relationship", r.get("id", ""),
                               f"联系「{r.get('name', '未命名')}」的基数「{r.get('cardinality')}」不合法，应为 1:1 / 1:N / M:N"))
    return errors


def rule_R19(er_data):
    """R19: 联系两端必须连接存在的实体 (error)"""
    entity_ids = {e.get("id") for e in er_data.get("entities", [])}
    errors = []
    for r in er_data.get("relationships", []):
        for endpoint in ["from_entity", "to_entity"]:
            target = r.get(endpoint)
            if not target or target not in entity_ids:
                errors.append(_err("R19", "error", "relationship", r.get("id", ""),
                                   f"联系「{r.get('name', '未命名')}」的 {endpoint} 指向了不存在的实体"))
    return errors


def rule_R20(er_data):
    """R20: 联系名称唯一 (error)"""
    errors = []
    seen = {}
    for r in er_data.get("relationships", []):
        name = (r.get("name") or "").strip()
        if name:
            seen.setdefault(name, []).append(r.get("id", ""))
    for name, ids in seen.items():
        if len(ids) > 1:
            errors.append(_err("R20", "error", "relationship", ids[0],
                               f"联系名「{name}」重复出现 {len(ids)} 次"))
    return errors


def rule_R21(er_data):
    """R21: 1:1 联系较少见，建议确认 (warning)"""
    errors = []
    for r in er_data.get("relationships", []):
        if (r.get("cardinality") or "").strip().upper() == "1:1":
            errors.append(_err("R21", "warning", "relationship", r.get("id", ""),
                               f"联系「{r.get('name', '未命名')}」为 1:1 类型，较为少见，建议确认是否应为 1:N 或 M:N"))
    return errors


def rule_R22(er_data):
    """R22: 自环联系需确认 (warning)"""
    errors = []
    for r in er_data.get("relationships", []):
        if r.get("from_entity") and r.get("from_entity") == r.get("to_entity"):
            errors.append(_err("R22", "warning", "relationship", r.get("id", ""),
                               f"联系「{r.get('name', '未命名')}」连接了同一实体，请确认是否为递归联系"))
    return errors


def rule_R23(er_data):
    """R23: M:N 联系建议有联系属性 (warning)"""
    errors = []
    for r in er_data.get("relationships", []):
        if (r.get("cardinality") or "").strip().upper() == "M:N":
            if not r.get("attributes"):
                errors.append(_err("R23", "warning", "relationship", r.get("id", ""),
                                   f"M:N 联系「{r.get('name', '未命名')}」通常需要联系属性（如选课日期），建议补充"))
    return errors


# ======================================================================
# D. 结构/全局规则 (R24-R28)
# ======================================================================

def rule_R24(er_data):
    """R24: ER 图至少有一个实体 (error)"""
    if not er_data.get("entities"):
        return [_err("R24", "error", "graph", "", "ER 图中没有任何实体")]
    return []


def rule_R25(er_data):
    """R25: 多个实体但无联系 (warning)"""
    ents = er_data.get("entities", [])
    rels = er_data.get("relationships", [])
    if len(ents) > 1 and not rels:
        return [_err("R25", "warning", "graph", "",
                     f"图中存在 {len(ents)} 个实体但没有任何联系")]
    return []


def rule_R26(er_data):
    """R26: 实体属性过多 (warning)"""
    errors = []
    for e in er_data.get("entities", []):
        n = len(e.get("attributes", []))
        if n > 15:
            errors.append(_err("R26", "warning", "entity", e.get("id", ""),
                               f"实体「{e.get('name', '未命名')}」有 {n} 个属性，建议拆分或检查是否符合范式"))
    return errors


def rule_R27(er_data):
    """R27: 主键属性过多 (warning)"""
    errors = []
    for e in er_data.get("entities", []):
        pk_count = sum(1 for a in e.get("attributes", []) if a.get("is_primary_key"))
        if pk_count > 3:
            errors.append(_err("R27", "warning", "entity", e.get("id", ""),
                               f"实体「{e.get('name', '未命名')}」的主键包含 {pk_count} 个属性，建议检查是否可缩减"))
    return errors


def rule_R28(er_data):
    """R28: 弱实体应通过联系依赖强实体 (error)"""
    entities = er_data.get("entities", [])
    relationships = er_data.get("relationships", [])
    weak_ids = {e["id"] for e in entities if e.get("is_weak")}
    strong_ids = {e["id"] for e in entities if not e.get("is_weak")}

    errors = []
    for wid in weak_ids:
        connected = False
        for r in relationships:
            f, t = r.get("from_entity"), r.get("to_entity")
            if (f == wid and t in strong_ids) or (t == wid and f in strong_ids):
                connected = True
                break
        if not connected:
            ent = next((e for e in entities if e.get("id") == wid), {})
            errors.append(_err("R28", "error", "entity", wid,
                               f"弱实体「{ent.get('name', '未命名')}」未通过联系依赖任何强实体"))
    return errors


# ======================================================================
# E. 需求对齐规则 (R29-R32)
# 仅当 er_data 中包含 requirement_text 字段时触发
# ======================================================================

def rule_R29(er_data):
    """R29: 需求实体覆盖率 (warning)"""
    req = er_data.get("requirement_text", "")
    if not req:
        return []

    synonyms = _load_synonyms()
    entities = er_data.get("entities", [])

    # 收集图中已有的实体名（含同义词展开）
    designed = set()
    for e in entities:
        name = e.get("name", "")
        designed.add(name)
        for key, syns in synonyms.items():
            if name in syns or name == key:
                designed.add(key)
                designed.update(syns)

    # 找需求中提到、但图中缺失的实体
    missing = []
    for key, syns in synonyms.items():
        in_req = any(syn in req for syn in syns)
        in_design = any(syn in designed for syn in [key] + syns)
        if in_req and not in_design:
            missing.append(key)

    if missing:
        return [_err("R29", "warning", "graph", "",
                     f"需求中提到的实体未出现在 ER 图中：{', '.join(missing)}")]
    return []


def rule_R30(er_data):
    """R30: 需求联系覆盖率 (warning)"""
    req = er_data.get("requirement_text", "")
    if not req:
        return []

    rels = er_data.get("relationships", [])

    # 收集图中已有的联系名（含同义词展开）
    designed = set()
    for r in rels:
        name = r.get("name", "")
        designed.add(name)
        for key, syns in _REL_SYNONYMS.items():
            if name in syns or name == key:
                designed.add(key)
                designed.update(syns)

    missing = []
    for key, syns in _REL_SYNONYMS.items():
        in_req = any(syn in req for syn in syns)
        in_design = any(syn in designed for syn in [key] + syns)
        if in_req and not in_design:
            missing.append(key)

    if missing:
        return [_err("R30", "warning", "graph", "",
                     f"需求中提到的联系未出现在 ER 图中：{', '.join(missing)}")]
    return []


def rule_R31(er_data):
    """R31: 需求属性覆盖率 (warning)"""
    req = er_data.get("requirement_text", "")
    if not req:
        return []

    entities = er_data.get("entities", [])
    designed = set()
    for e in entities:
        for a in e.get("attributes", []):
            name = a.get("name", "")
            designed.add(name)
            for key, syns in _ATTR_SYNONYMS.items():
                if name in syns or name == key:
                    designed.add(key)
                    designed.update(syns)

    missing = []
    for key, syns in _ATTR_SYNONYMS.items():
        in_req = any(syn in req for syn in syns)
        in_design = any(syn in designed for syn in [key] + syns)
        if in_req and not in_design:
            missing.append(key)

    if missing:
        return [_err("R31", "warning", "graph", "",
                     f"需求中提到的属性未出现在 ER 图中：{', '.join(missing)}")]
    return []


def rule_R32(er_data):
    """R32: 需求与设计命名一致性检查 (warning)"""
    req = er_data.get("requirement_text", "")
    if not req:
        return []

    synonyms = _load_synonyms()
    entities = er_data.get("entities", [])
    errors = []

    for e in entities:
        name = e.get("name", "")
        for key, syns in synonyms.items():
            if name in syns and name != key:
                # 图中用了同义词，看需求用的是哪个
                req_words = [s for s in syns if s in req]
                if key in req_words and name not in req_words:
                    errors.append(_err("R32", "warning", "entity", e.get("id", ""),
                                       f"需求中使用「{key}」，ER 图中命名为「{name}」，建议统一命名"))
    return errors


# ======================================================================
# 规则注册表 —— 加新规则在这里加一行
# ======================================================================

ALL_RULES = [
    # A. 实体规则
    rule_R01, rule_R02, rule_R03, rule_R04, rule_R05,
    rule_R06, rule_R07, rule_R08,
    # B. 属性规则
    rule_R09, rule_R10, rule_R11, rule_R12, rule_R13,
    rule_R14, rule_R15,
    # C. 联系规则
    rule_R16, rule_R17, rule_R18, rule_R19, rule_R20,
    rule_R21, rule_R22, rule_R23,
    # D. 结构/全局规则
    rule_R24, rule_R25, rule_R26, rule_R27, rule_R28,
    # E. 需求对齐规则
    rule_R29, rule_R30, rule_R31, rule_R32,
]
