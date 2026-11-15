# -*- coding: utf-8 -*-
"""
ER 校验规则集（44 条）
======================

分级（对应 INTERFACE.md 规则编号规范）：
    R 前缀 = 刚性规则，level="error"，前端标红（#E11D48），必须修
    H 前缀 = 启发规则，level="warn"， 前端标橙（#F97316），建议改

每条规则是一个函数：
    输入  ctx (RuleContext)
    输出  list[Issue]（可为空）

Issue 结构（与协议对齐）：
    {"rule_id": "R01", "level": "error"|"warn", "message": "..."}
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from model import (
    PARTIAL_PREFIX,
    PK_PREFIX,
    SHAPE_DIAMOND,
    SHAPE_ELLIPSE,
    SHAPE_RECT,
    Diagram,
    Element,
    has_partial_prefix,
    has_pk_prefix,
    strip_prefix,
)

# ----------------------------------------------------------------------
# 上下文与结果
# ----------------------------------------------------------------------


class Issue(dict):
    """一条校验结果。dict 子类，便于直接 JSON 序列化。"""

    def __init__(self, rule_id: str, level: str, message: str,
                 target_id: str = "") -> None:
        super().__init__(rule_id=rule_id, level=level, message=message)
        self.target_id = target_id  # 不计入协议字段，仅供 engine 归位


class RuleContext:
    """
    规则执行上下文。

    一次检查可能来自单元素事件、单连线事件或批量事件；
    图模型始终是"当前完整图"（单元素事件时由服务端缓存补全），
    但 target_* 指出本次关注的焦点，供局部规则使用。
    """

    def __init__(
        self,
        diagram: Diagram,
        event: str = "",
        target_element: Optional[Element] = None,
        target_connection=None,
        changes: Optional[dict] = None,
        has_full_graph: bool = True,
    ) -> None:
        self.diagram = diagram
        self.event = event
        self.target_element = target_element
        self.target_connection = target_connection
        self.changes = changes or {}
        self.has_full_graph = has_full_graph

    # 便捷属性
    @property
    def entities(self) -> List[Element]:
        return self.diagram.entities

    @property
    def relationships(self) -> List[Element]:
        return self.diagram.relationships


def _err(rule_id: str, target_id: str, message: str) -> Issue:
    return Issue(rule_id, "error", message, target_id)


def _warn(rule_id: str, target_id: str, message: str) -> Issue:
    return Issue(rule_id, "warn", message, target_id)


# ======================================================================
# 一、图形/元素级规则
# ======================================================================

def rule_R01(ctx: RuleContext) -> List[Issue]:
    """R01 元素必须有名称（刚性）"""
    out = []
    for e in ctx.diagram.elements.values():
        if not e.name:
            kind = {"rectangle": "实体", "ellipse": "属性", "diamond": "联系"}.get(
                e.shape, "元素")
            out.append(_err("R01", e.id, f"{kind}名称不能为空 —— 请为图形命名"))
    return out


def rule_R02(ctx: RuleContext) -> List[Issue]:
    """R02 实体必须有主键（刚性）—— 局部图：无属性时不判，有属性才要求

    弱实体例外（重要）：
        弱实体的标识 = 所属强实体的主键 + 自身的部分键（鉴别器，用 # 标注）。
        因此弱实体**不要求**自己带 * 主键；只要标注了 # 部分键即视为合规。
        若对弱实体也要求 *，会把教科书里标准的弱实体图（如"职工—具有—亲属"，
        亲属用 #称呼 作鉴别器）误判为错误。

    判定口径：
        - 非弱实体：有属性但无 * → 报错
        - 弱实体：有属性但既无 * 也无 # → 报错（提示补部分键，由 R05 负责措辞，
          此处只在两者皆缺时提示，避免与 R05 重复刷屏）
    """
    out = []
    for e in ctx.diagram.entities:
        if not e.name:
            continue
        attrs = [a for a in e.attributes if str(a).strip()]
        if not attrs:
            continue  # 尚未添加属性，不判缺主键

        has_pk = any(has_pk_prefix(a) for a in attrs)
        if has_pk:
            continue

        if e.is_weak:
            # 弱实体：有 # 部分键即可；两者都缺时只报缺部分键（R05 的口径）
            has_partial = any(has_partial_prefix(a) for a in attrs)
            if has_partial:
                continue
            # 交给 R05 报"缺少部分键"，此处不重复报主键
            continue

        out.append(_err(
            "R02", e.id,
            f"实体'{e.name}'缺少主键标注 —— 请在属性名前加 * 号"))
    return out


def rule_R03(ctx: RuleContext) -> List[Issue]:
    """R03 属性必须填写名称（刚性）"""
    return [
        _err("R03", e.id, "属性必须填写名称")
        for e in ctx.diagram.attributes_nodes if not e.name
    ]


def rule_R04(ctx: RuleContext) -> List[Issue]:
    """R04 联系必须标注名称（刚性）"""
    return [
        _err("R04", e.id, "联系必须标注名称（如 借阅、属于）")
        for e in ctx.diagram.relationships if not e.name
    ]


def rule_R05(ctx: RuleContext) -> List[Issue]:
    """R05 弱实体的键标注必须正确（刚性）

    两种情况都报：
      1) 弱实体没有任何 `#` 部分键 —— 缺鉴别器（原有检查）
      2) 弱实体**同时**标了 `#` 和 `*` —— 概念混淆（新增）

    为什么第 2 种是错误：
        弱实体的标识 = **所属强实体的主键 + 自身部分键（鉴别器）**。
        弱实体不应自立独立主键 `*`；同时标 `*` 与 `#` 说明学生
        没理解弱实体与强实体的标识关系，是教学必须纠正的点。
        （此前该情形无任何规则报出，属漏报——R05 见 `#` 即放行、
          R02 见 `*` 即放行、R07 只有一个 `*` 也不报。）
    """
    out = []
    for e in ctx.diagram.entities:
        if not e.is_weak:
            continue
        has_partial = any(has_partial_prefix(a) for a in e.attributes)
        has_pk = any(has_pk_prefix(a) for a in e.attributes)
        name = e.name or "未命名"
        if not has_partial:
            out.append(_err(
                "R05", e.id,
                f"弱实体'{name}'缺少部分键 —— 请在属性名前加 {PARTIAL_PREFIX} 号"))
        elif has_pk:
            out.append(_err(
                "R05", e.id,
                f"弱实体'{name}'同时标注了主键（{PK_PREFIX}）与部分键"
                f"（{PARTIAL_PREFIX}）—— 弱实体的标识由「强实体主键 + 自身部分键」"
                f"构成，不应另标独立主键"))
    return out


def rule_R06(ctx: RuleContext) -> List[Issue]:
    """R06 属性列表不得含空白项（刚性）"""
    out = []
    for e in ctx.diagram.elements.values():
        for a in e.attributes:
            if not str(a).strip():
                out.append(_err(
                    "R06", e.id,
                    f"'{e.name or '未命名'}'存在空白属性名，请补全或删除"))
                break
    return out


def rule_R07(ctx: RuleContext) -> List[Issue]:
    """R07 多个主键属性需确认为复合主键（启发级）

    **为什么要从刚性降为启发**（教学正确性）：
        关系模型里主键可以是**属性的组合**（复合主键），
        `选课(*学号, *课号, 成绩)` 是完全合法的建模，
        在"联系转实体"（如选课、借阅）场景里尤其常见。
        原实现把"多个属性带 * "一律判为刚性错误"主键应当唯一"，
        会逼学生把正确的复合主键改坏——属于把正确设计误判为错误。

        现在改为**启发级确认提示**：提醒学生核对
        "这确实是复合主键，还是误标了多个主键"。
        真正的问题（同一属性重复标 *）由 R08 去重规则兜住。
    """
    out = []
    for e in ctx.diagram.entities:
        pks = e.primary_keys()
        if len(pks) > 1:
            names = "、".join(strip_prefix(p) for p in pks)
            out.append(_warn(
                "R07", e.id,
                f"实体'{e.name or '未命名'}'有 {len(pks)} 个属性标注为主键（{names}）"
                f"—— 若为复合主键请确认无误，否则请只保留一个主键"))
    return out


def rule_R08(ctx: RuleContext) -> List[Issue]:
    """R08 属性名不得重复（刚性）"""
    out = []
    for e in ctx.diagram.elements.values():
        if not e.attributes:
            continue
        seen: Dict[str, int] = {}
        for a in e.attributes:
            bare = strip_prefix(a)
            if bare:
                seen[bare] = seen.get(bare, 0) + 1
        for name, cnt in seen.items():
            if cnt > 1:
                out.append(_err(
                    "R08", e.id,
                    f"属性'{name}'在'{e.name or '未命名'}'中重复出现 {cnt} 次"))
    return out


def rule_R09(ctx: RuleContext) -> List[Issue]:
    """R09 属性名建议不要与所属元素名相同（启发级）

    v1.4 起从刚性降为启发（第二轮教学审查遗漏项，本轮补上）：
        提示语本身写着"建议区分命名"却是 error 级——命令与措辞自相矛盾。
        且"属性名与实体名相同"属命名质量问题（可读性/歧义），
        不影响 ER 模型的语义正确性，与 R07/R13/R16 同理应为启发级。
    """
    out = []
    for e in ctx.diagram.elements.values():
        if not e.name:
            continue
        for a in e.attributes:
            if strip_prefix(a) == e.name:
                out.append(_warn(
                    "R09", e.id,
                    f"'{e.name}'下的属性名与实体名相同，建议区分命名"
                    f"（如属性'学生'可改为'学生姓名'）"))
                break
    return out


def rule_R10(ctx: RuleContext) -> List[Issue]:
    """R10 连线两端必须存在（刚性）"""
    return [
        _err("R10", c.id, "连线端点指向了不存在的元素")
        for c in ctx.diagram.dangling_connections()
    ]


def rule_R11(ctx: RuleContext) -> List[Issue]:
    """R11 禁止自环连线（刚性）"""
    return [
        _err("R11", c.id, "连线不能连接元素自身")
        for c in ctx.diagram.connections.values()
        if c.from_id and c.from_id == c.to_id
    ]


def rule_R12(ctx: RuleContext) -> List[Issue]:
    """R12 禁止重复连线（刚性）

    **递归（一元）联系例外**（重要）：
        教材必讲的"员工—管理—员工"，在 Chen 记法里是
            员工 ──1──◇管理◇──N── 员工
        两条分支线的**端点对天然相同**（同一个实体 ↔ 同一个菱形），
        仅基数不同（1 / N）。若只按 (from, to, type) 判重，
        会把标准递归联系误判为红色刚性错误，
        逼学生改成错误画法才能通过校验。

        故判重键必须包含 cardinality：
            (from, to, type, cardinality)
        这样"端点相同但基数不同"的两条分支线不再算重复，
        而真正重复（端点、类型、基数全同）仍会被拦下。
    """
    seen: Dict[tuple, str] = {}
    out = []
    for c in ctx.diagram.connections.values():
        key = (c.from_id, c.to_id, c.type, c.cardinality or "")
        if key in seen:
            out.append(_err(
                "R12", c.id,
                "元素间已存在完全相同的连线（端点、类型、基数均相同），请勿重复绘制"))
        else:
            seen[key] = c.id
    return out


def rule_R13(ctx: RuleContext) -> List[Issue]:
    """R13 实体间建议不要直接连线（启发级）

    **为什么从刚性降为启发**（教学正确性）：
        不少教材用**无菱形的直接连线**表示 ISA 继承
        （学生 ———— 研究生），这是合法的画法。
        原实现把所有"实体—实体 line 直连"判为红色刚性错误，
        会把正确的继承画法拦下。

        但"两实体直连"确实多数情况下是漏画了菱形，
        仍有提示价值，故保留为启发级建议。

    与 H09 的分工（两者不重叠）：
        - R13/H13 处理 type=line（无菱形的直连）
        - H09  处理 type=diamond_line（用联系分支线把两个实体直连）
        这是两种不同的误用形态，各自提示。
    """
    out = []
    for c in ctx.diagram.connections.values():
        a, b = ctx.diagram.get(c.from_id), ctx.diagram.get(c.to_id)
        if a is None or b is None:
            continue
        if a.is_entity and b.is_entity and c.type == "line":
            out.append(_warn(
                "R13", c.id,
                f"实体'{a.name or a.id}'与'{b.name or b.id}'直接连线 —— "
                f"若是关联关系请用联系（菱形）表达；若是 ISA 继承则可忽略"))
    return out


def rule_R14(ctx: RuleContext) -> List[Issue]:
    """R14 联系分支线必须标注基数（刚性）

    与 R17 的分工（避免同一问题重复报多条红字）：
        本规则是**连线级**视角——针对"这条分支线自己缺基数"。
        R17 是**图结构级**视角——按菱形聚合，说明"这个联系缺基数"。

        两者对同一问题会各报一次，一条菱形两条分支就产生 3 条红字，
        学生会误以为是 3 个独立错误。

        处理：当存在全图快照（能交给 R17 统一报）时，
        **本规则只在"该分支所属菱形还有其他分支已标基数"时发言**，
        即"漏标了一条"这种局部情况；整体都缺的由 R17 汇总。
        这样既保留"具体哪条线漏了"的定位价值，又不重复刷屏。
    """
    out = []
    for c in ctx.diagram.connections.values():
        if not c.is_relation_branch:
            continue
        if c.cardinality:
            continue
        # 找到该分支所属的菱形，看它的其他分支是否已标基数
        diamond_id = None
        for end in (c.from_id, c.to_id):
            el = ctx.diagram.get(end)
            if el is not None and el.is_relationship:
                diamond_id = end
                break
        peers_have_card = False
        if diamond_id and ctx.has_full_graph:
            peers = [b for b in ctx.diagram.branches_of(diamond_id) if b.id != c.id]
            peers_have_card = any(b.cardinality for b in peers)
            if peers and not peers_have_card:
                # 整个菱形都没标 → 交给 R17 汇总报，本规则不重复
                continue
        out.append(_err(
            "R14", c.id,
            "联系连线缺少基数符号（请在线上写 1 / N / M / P）"))
    return out


def rule_R15(ctx: RuleContext) -> List[Issue]:
    """R15 基数必须是合法符号（刚性）"""
    from model import VALID_CARDINALITIES
    out = []
    for c in ctx.diagram.connections.values():
        card = c.cardinality
        if card and card.upper() not in VALID_CARDINALITIES:
            out.append(_err(
                "R15", c.id,
                f"基数'{card}'不合法 —— Chen 记法只允许 1 / N / M / P"))
    return out


def rule_R16(ctx: RuleContext) -> List[Issue]:
    """R16 普通连线不应标注基数（启发级）

    **为什么从刚性降为启发**：
        在属性线或普通关联线上误写基数，属于**操作失误**，
        不是 ER 模型语义错误——不修也不影响模型的正确性与可读性
        （基数只有出现在联系分支线上才有语义）。
        作为刚性红色错误会让学生以为模型错了。

        但"基数写错地方"确实值得提醒（可能学生混淆了线的用途），
        故保留为启发级。
    """
    out = []
    for c in ctx.diagram.connections.values():
        if c.type == "line" and c.cardinality:
            out.append(_warn(
                "R16", c.id,
                "该连线不是联系分支线，基数只有写在联系分支线上才有意义，"
                "建议移除"))
    return out


def rule_R17(ctx: RuleContext) -> List[Issue]:
    """R17 联系必须标注基数（图结构级，按菱形聚合）"""
    out = []
    for d in ctx.diagram.relationships:
        branches = ctx.diagram.branches_of(d.id)
        if not branches:
            continue  # 交给 R19/R18 报"未连接"
        if any(not b.cardinality for b in branches):
            out.append(_err(
                "R17", d.id,
                f"联系'{d.name or '未命名'}'的分支线缺少基数标注"))
    return out


def rule_R18(ctx: RuleContext) -> List[Issue]:
    """R18 联系必须连接两个及以上实体（刚性）"""
    out = []
    for d in ctx.diagram.relationships:
        if len(ctx.diagram.branches_of(d.id)) < 2:
            out.append(_err(
                "R18", d.id,
                f"联系'{d.name or '未命名'}'至少应连接两个实体"))
    return out


def rule_R19(ctx: RuleContext) -> List[Issue]:
    """R19 孤立菱形（刚性）"""
    out = []
    for d in ctx.diagram.relationships:
        if not ctx.diagram.branches_of(d.id):
            out.append(_err(
                "R19", d.id,
                f"联系'{d.name or '未命名'}'未连接到任何实体"))
    return out


def rule_R20(ctx: RuleContext) -> List[Issue]:
    """R20 联系名必须唯一（刚性）"""
    return [
        _err("R20", ids[0], f"联系名'{name}'重复出现 {len(ids)} 次")
        for name, ids in ctx.diagram.duplicate_element_names(SHAPE_DIAMOND).items()
    ]


def rule_R21(ctx: RuleContext) -> List[Issue]:
    """R21 实体名必须唯一（刚性）"""
    return [
        _err("R21", ids[0], f"实体名'{name}'重复出现 {len(ids)} 次")
        for name, ids in ctx.diagram.duplicate_element_names(SHAPE_RECT).items()
    ]


def rule_R22(ctx: RuleContext) -> List[Issue]:
    """R22 ER 图至少有一个实体（刚性）"""
    if not ctx.diagram.entities:
        return [_err("R22", "", "ER 图中没有任何实体")]
    return []


def rule_R23(ctx: RuleContext) -> List[Issue]:
    """R23 弱实体必须依赖强实体（刚性）

    判定口径（跨菱形）：
        弱实体在 Chen 记法里通常经"联系"连到强实体：
            弱实体 ──◇具有◇── 强实体
        所以必须**跨过菱形**去找对端实体，只做"直接相邻实体"判定会误报。

        依赖成立的条件：存在一条路径，使弱实体能到达某个非弱实体。
        既支持"弱实体—强实体"直连，也支持"弱实体—菱形—强实体"。
    """
    out = []
    for e in ctx.diagram.entities:
        if not e.is_weak:
            continue
        reachable = ctx.diagram.entities_via_relationships(e.id)
        strong = [n for n in reachable if not n.is_weak]
        if not strong:
            out.append(_err(
                "R23", e.id,
                f"弱实体'{e.name or '未命名'}'未通过联系依赖任何强实体"))
    return out


# ======================================================================
# 二、启发式规则（H，level="warn"）
# ======================================================================

_VERB_HINTS = ("选", "修", "属", "借", "购", "管", "拥", "包", "含", "参", "授",
               "开", "录", "登", "审", "维", "发", "使", "用", "隶", "组", "供",
               "销", "储", "预", "归", "还", "指", "导", "评", "统", "计",
               # 教科书中常见的联系动词（补全以免误报）
               "具", "有", "持", "领", "带", "配", "对", "应", "关", "联",
               "生", "产", "制", "造", "运", "送", "服", "务",
               # 业务惯例型联系名（独立教学审查指出这些是教材正常用例，
               # 如"婚姻"是 1:1 的经典例子、"父子"是递归联系的经典例子）
               "婚", "姻", "父", "子", "母", "女", "兄", "弟", "考", "试",
               "需", "求", "报", "警", "翻", "译", "监", "护", "合", "作",
               "贷", "款", "租", "赁", "维", "修", "管", "辖", "兼", "任",
               "继", "承", "派", "驻", "兼", "并", "拆", "分", "调", "拨",
               # "成绩"等作为联系名（如"选修—成绩"）在教材习题中很常见
               "成", "绩", "借", "阅", "还", "罚", "款", "折", "扣")
_MULTIVALUE_HINTS = ("电话", "邮箱", "地址", "多个", "列表", "手机", "联系人",
                     "曾用名", "别名", "兴趣", "爱好")
_DERIVED_HINTS = ("年龄", "总计", "总数", "平均", "总分", "排名", "余额",
                  "数量合计", "小计", "占比", "百分比")

# ISA（子类/超类）继承关系的名称特征。
# 画布无专用图元，只能靠菱形名识别；宁可漏报也不误报（见 rule_H14 说明）。
_ISA_HINTS = ("isa", "is_a", "is-a", "继承", "子类", "超类", "父类",
              "是一种", "是一类", "属于一种", "泛化", "特化")


def _looks_like_isa(name: str) -> bool:
    """菱形名是否像 ISA 继承联系。"""
    if not name:
        return False
    low = name.strip().lower()
    return any(h in low for h in _ISA_HINTS)


def rule_H01(ctx: RuleContext) -> List[Issue]:
    """H01 实体名建议使用单数名词（启发）"""
    out = []
    for e in ctx.diagram.entities:
        n = e.name
        if not n:
            continue
        if n.endswith("们") or re.search(r"[a-zA-Z]s$", n):
            out.append(_warn(
                "H01", e.id,
                f"实体名'{n}'建议使用单数名词（如'学生'而非'学生们'）"))
    return out


def rule_H02(ctx: RuleContext) -> List[Issue]:
    """H02 联系名建议使用动词或动宾短语（启发）

    ISA 继承例外：继承联系的规范命名本就是 "ISA" / "是" / "继承" 等，
    它们不是动宾短语，提示"建议使用动词"属噪音（会诱导学生改掉标准写法）。

    提示语为**中性确认式**（独立教学审查建议）：
        词表不可能穷举，"婚姻""父子""考试""监护"等都是教材里
        完全正常的联系名（"婚姻"还是 1:1 的经典例子）。
        若用"建议改为动词"的命令式，会把正确命名说成待改项。
        故改为"若为业务惯例命名可忽略"，把判断权交回学生/教师。
    """
    out = []
    for d in ctx.diagram.relationships:
        n = d.name
        if not n:
            continue
        if _looks_like_isa(n):
            continue
        if not any(h in n for h in _VERB_HINTS):
            out.append(_warn(
                "H02", d.id,
                f"联系名'{n}'不是常见的动词/动宾短语 —— "
                f"建议用动词命名（如'选修'、'属于'）；"
                f"若为业务惯例命名（如'婚姻'）可忽略"))
    return out


def rule_H03(ctx: RuleContext) -> List[Issue]:
    """H03 疑似多值属性（启发）"""
    out = []
    for e in ctx.diagram.elements.values():
        for a in e.attributes:
            name = strip_prefix(a)
            if any(h in name for h in _MULTIVALUE_HINTS):
                out.append(_warn(
                    "H03", e.id,
                    f"属性'{name}'可能为多值属性，建议拆分为独立实体或关联表"))
    return out


def rule_H04(ctx: RuleContext) -> List[Issue]:
    """H04 疑似派生属性（启发）"""
    out = []
    for e in ctx.diagram.elements.values():
        for a in e.attributes:
            name = strip_prefix(a)
            if any(h in name for h in _DERIVED_HINTS):
                out.append(_warn(
                    "H04", e.id,
                    f"属性'{name}'可能是派生属性，建议标注为派生而非存储"))
    return out


def rule_H05(ctx: RuleContext) -> List[Issue]:
    """H05 同类元素的命名风格应统一（启发）

    **收窄判定范围**（独立教学审查指出噪音过大）：
        原实现统计全图所有名称（含属性），只要中英文并存就提示。
        但"实体用中文、属性用英文"在教学中非常常见（教材本身也混排），
        导致该提示几乎恒亮——学生对橙色提示脱敏后，
        会连带忽略真正有价值的那几条。

        现在只在**同类元素内部**混用时才提示：
          - 实体名之间混用（部分中文实体名 + 部分英文实体名），或
          - 属性名之间混用（同一实体或不同实体的属性名中英并存）
        跨类混用（实体中文 + 属性英文）不再报。
    """
    def classify(tokens):
        zh = sum(1 for t in tokens if re.search(r"[\u4e00-\u9fff]", t))
        en = sum(1 for t in tokens if re.search(r"[a-zA-Z]", t))
        return zh, en

    ent_names = [e.name for e in ctx.diagram.entities if e.name]
    attr_names = []
    for e in ctx.diagram.elements.values():
        attr_names.extend(strip_prefix(a) for a in e.attributes if strip_prefix(a))

    zh_e, en_e = classify(ent_names)
    zh_a, en_a = classify(attr_names)

    if zh_e and en_e:
        return [_warn("H05", "",
                      f"实体名中英文混用（中文 {zh_e} 个、英文 {en_e} 个），"
                      f"建议统一命名风格")]
    if zh_a and en_a:
        return [_warn("H05", "",
                      f"属性名中英文混用（中文 {zh_a} 个、英文 {en_a} 个），"
                      f"建议统一命名风格")]
    return []


def rule_H06(ctx: RuleContext) -> List[Issue]:
    """H06 实体属性过多（启发）"""
    out = []
    for e in ctx.diagram.entities:
        n = len([a for a in e.attributes if str(a).strip()])
        if n > 12:
            out.append(_warn(
                "H06", e.id,
                f"实体'{e.name or '未命名'}'有 {n} 个属性，"
                f"建议检查是否符合范式、是否需要拆分"))
    return out


def rule_H07(ctx: RuleContext) -> List[Issue]:
    """H07 名称含多余空格或特殊字符（启发）

    判定口径（独立教学审查后修正）：
      - 首尾空白 —— 总是异常
      - **中文名内部出现空格** —— 异常（如"学 生"）
      - 含标点/分隔符

    **英文名的内部空格属正常**（如 "Student ID"、"First Name"），
    通行写法，不应提示。修正前会把这类英文名判为"含多余空格"，
    而真正该提醒的中缀分隔符（如 `电话(手机)`、`学号/编号`）反而漏掉——
    判定标准与教学现实相反。

    故按语境区分：内部空格只在"名称含中文"时才提示；
    分隔符则不分语境一律提示。
    """
    out = []
    for e in ctx.diagram.elements.values():
        tokens = [e.label] + [strip_prefix(a) for a in e.attributes]
        for t in tokens:
            s = str(t)
            if not s:
                continue
            has_cjk = re.search(r"[\u4e00-\u9fff]", s) is not None
            inner_space = re.search(r"\S\s+\S", s) is not None
            # 分隔符（含中缀括号、斜杠等，这些才是真正该清理的）
            separator = re.search(r"[,，。;；、！？!?()（）/\\|]", s) is not None
            bad = s != s.strip() or separator or (inner_space and has_cjk)
            if bad:
                out.append(_warn(
                    "H07", e.id,
                    f"名称'{s}'含多余空格或特殊字符，建议清理"))
                break
    return out
def rule_H08(ctx: RuleContext) -> List[Issue]:
    """H08 名称过长（启发）"""
    out = []
    for e in ctx.diagram.elements.values():
        if len(e.name) > 20:
            out.append(_warn(
                "H08", e.id,
                f"名称'{e.name[:20]}…'过长，建议精简"))
    return out
def rule_H09(ctx: RuleContext) -> List[Issue]:
    """H09 实体间直接连线缺少联系菱形（启发）"""
    out = []
    for c in ctx.diagram.connections.values():
        a, b = ctx.diagram.get(c.from_id), ctx.diagram.get(c.to_id)
        if a and b and a.is_entity and b.is_entity and c.type == "diamond_line":
            out.append(_warn(
                "H09", c.id,
                f"实体'{a.name or a.id}'与'{b.name or b.id}'之间建议使用联系（菱形）连接"))
    return out
def rule_H10(ctx: RuleContext) -> List[Issue]:
    """H10 属性归属建议由属性指向实体（启发）"""
    out = []
    for c in ctx.diagram.connections.values():
        a, b = ctx.diagram.get(c.from_id), ctx.diagram.get(c.to_id)
        if a is None or b is None:
            continue
        if a.is_entity and b.is_attribute:
            out.append(_warn(
                "H10", c.id,
                f"属性'{b.name or b.id}'的归属连线建议由属性指向实体"))
    return out
def rule_H11(ctx: RuleContext) -> List[Issue]:
    """H11 联系分支线建议两端齐全（启发）"""
    out = []
    for d in ctx.diagram.relationships:
        n = len(ctx.diagram.branches_of(d.id))
        if n == 1:
            out.append(_warn(
                "H11", d.id,
                f"联系'{d.name or '未命名'}'只连接了 1 个实体，建议补齐参与实体"))
    return out
def rule_H12(ctx: RuleContext) -> List[Issue]:
    """H12 孤立实体（启发）"""
    out = []
    for e in ctx.diagram.entities:
        if len(ctx.diagram.entities) < 2:
            continue
        if ctx.diagram.is_isolated(e.id):
            out.append(_warn(
                "H12", e.id,
                f"实体'{e.name or '未命名'}'未参与任何联系，可能是孤立实体"))
    return out
def rule_H13(ctx: RuleContext) -> List[Issue]:
    """H13 多实体但无联系（启发）"""
    ents = ctx.diagram.entities
    if len(ents) > 1:
        has_rel = any(c.is_relation_branch for c in ctx.diagram.connections.values())
        has_diamond = bool(ctx.diagram.relationships)
        if not has_rel and not has_diamond:
            return [_warn(
                "H13", "",
                f"图中存在 {len(ents)} 个实体但没有任何联系")]
    return []


def rule_H14(ctx: RuleContext) -> List[Issue]:
    """H14 联系各端基数均为 1（启发）

    ISA 继承例外（重要）：
        教材里"子类 ISA 超类"常用菱形表示，且**标准写法就是两端均为 1**
        （一个研究生实例对应一个学生实例）。此时提示"是否应为 1:N 或 M:N"
        属噪音，会让学生把正确的继承画法改错。

        画布上没有 ISA 专用图元，唯一可用信号是菱形名称，故按名称识别：
        含 ISA / 是 / 属 / 继承 / 子类 等语义词时跳过。

        代价说明：名为"担任"的 1:1 联系若也含这些字，会被一并跳过——
        分类器宁可漏报（少提示）也不误报（乱提示），因为启发级提示
        的价值在于"值得一看"，噪音会让人忽略全部提示。
    """
    out = []
    for d in ctx.diagram.relationships:
        if _looks_like_isa(d.name):
            continue
        cards = [b.cardinality for b in ctx.diagram.branches_of(d.id) if b.cardinality]
        if len(cards) >= 2 and all(c == "1" for c in cards):
            out.append(_warn(
                "H14", d.id,
                f"联系'{d.name or '未命名'}'各端基数均为 1（1:1 联系）—— "
                f"请确认确实是一对一；若是 ISA 继承可直接忽略"))
    return out
def rule_H15(ctx: RuleContext) -> List[Issue]:
    """H15 联系基数组合可疑（启发）—— 三元及以上且出现重复 M/N"""
    out = []
    for d in ctx.diagram.relationships:
        cards = [b.cardinality for b in ctx.diagram.branches_of(d.id) if b.cardinality]
        if len(cards) >= 3:
            high = [c for c in cards if c in ("M", "N")]
            if len(high) >= 3:
                out.append(_warn(
                    "H15", d.id,
                    f"联系'{d.name or '未命名'}'的基数组合 {'/'.join(cards)} "
                    f"较为少见，建议复核是否确为三元多对多"))
    return out
def rule_H16(ctx: RuleContext) -> List[Issue]:
    """H16 实体仅有主键属性（启发）

    豁免两类实体（独立教学审查指出属结构性噪音）：
      - **弱实体**：其标识由「强实体主键 + 自身部分键」构成，
        只画一个 `#` 鉴别器是标准写法，不该催补描述性属性。
      - **ISA 子类**：子类只继承主键、不重复列超类属性是常见画法。

    判定 ISA 子类：该实体经菱形连接到另一个实体，
    且菱形名像 ISA（复用 _looks_like_isa）。
    """
    out = []
    for e in ctx.diagram.entities:
        if e.is_weak:
            continue
        attrs = [a for a in e.attributes if str(a).strip()]
        if not attrs or len(attrs) != 1:
            continue
        # ISA 子类豁免
        is_subclass = False
        for c in ctx.diagram.connections_of(e.id):
            other = ctx.diagram.get(c.other_end(e.id))
            if other is not None and other.is_relationship \
                    and _looks_like_isa(other.name):
                is_subclass = True
                break
        if is_subclass:
            continue
        out.append(_warn(
            "H16", e.id,
            f"实体'{e.name or '未命名'}'仅有 1 个属性，建议补充描述性属性"))
    return out
def rule_H17(ctx: RuleContext) -> List[Issue]:
    """H17 图规模过小（启发）"""
    if 0 < len(ctx.diagram.entities) < 2:
        return [_warn("H17", "", "图中实体较少，建议补充业务相关实体")]
    return []


# ----------------------------------------------------------------------
# 需求-设计对齐（轻量通道：编辑距离 + 同义词表）
# ----------------------------------------------------------------------

_REQUIREMENT_SYNONYMS: Dict[str, List[str]] = {
    "学生": ["学生", "同学", "学员", "student"],
    "教师": ["教师", "老师", "教员", "teacher"],
    "课程": ["课程", "课", "course"],
    "班级": ["班级", "班", "class"],
    "院系": ["院系", "学院", "系", "department"],
    "图书": ["图书", "书", "书籍", "book"],
    "读者": ["读者", "借阅人", "用户", "reader"],
    "借阅": ["借阅", "借书", "外借", "borrow"],
    "选修": ["选修", "选课", "选", "elect"],
    "授课": ["授课", "讲授", "开课", "教"],
    "成绩": ["成绩", "分数", "得分", "score"],
    "库存": ["库存", "存量", "stock"],
}

_REQUIREMENT_ATTRS: Dict[str, List[str]] = {
    "学号": ["学号", "学生编号", "student_id"],
    "姓名": ["姓名", "名字", "name"],
    "成绩": ["成绩", "分数", "score"],
    "书名": ["书名", "图书名", "title"],
    "库存量": ["库存", "库存量", "数量", "stock"],
}


def _levenshtein(a: str, b: str) -> int:
    """编辑距离（轻量需求匹配用）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,        # 删除
                cur[j - 1] + 1,     # 插入
                prev[j - 1] + (ca != cb),  # 替换
            ))
        prev = cur
    return prev[-1]


def _fuzzy_in(token: str, text: str, max_dist: int = 1) -> bool:
    """token 是否在 text 中出现（精确，或编辑距离 <= max_dist 的近似）。"""
    if token in text:
        return True
    n = len(token)
    if n < 2:
        return False
    for i in range(len(text) - n + 1):
        if _levenshtein(token, text[i:i + n]) <= max_dist:
            return True
    return False


def _designed_terms(ctx: RuleContext) -> set:
    """图中已出现的全部名称（含同义词归一）。"""
    designed = set()
    for e in ctx.diagram.elements.values():
        if e.name:
            designed.add(e.name)
        for a in e.attributes:
            bare = strip_prefix(a)
            if bare:
                designed.add(bare)
    norm = set(designed)
    for key, syns in {**_REQUIREMENT_SYNONYMS, **_REQUIREMENT_ATTRS}.items():
        if any(s in designed for s in syns) or key in designed:
            norm.add(key)
    return norm


def rule_H18(ctx: RuleContext) -> List[Issue]:
    """H18 需求中的实体未覆盖（启发）"""
    req = ctx.diagram.requirement_text
    if not req:
        return []
    designed = _designed_terms(ctx)
    missing = [
        key for key, syns in _REQUIREMENT_SYNONYMS.items()
        if any(s in req for s in syns) and key not in designed
    ]
    if missing:
        return [_warn("H18", "", f"需求中提到的实体未出现在 ER 图中：{'、'.join(missing)}")]
    return []


def rule_H19(ctx: RuleContext) -> List[Issue]:
    """H19 需求中的联系未覆盖（启发）"""
    req = ctx.diagram.requirement_text
    if not req:
        return []
    designed_names = {d.name for d in ctx.diagram.relationships if d.name}
    missing = []
    for key, syns in [("借阅", _REQUIREMENT_SYNONYMS["借阅"]),
                      ("选修", _REQUIREMENT_SYNONYMS["选修"]),
                      ("授课", _REQUIREMENT_SYNONYMS["授课"])]:
        if any(s in req for s in syns) and not any(
                _levenshtein(key, dn) <= 2 or key in dn for dn in designed_names):
            missing.append(key)
    if missing:
        return [_warn("H19", "", f"需求中提到的联系未出现在 ER 图中：{'、'.join(missing)}")]
    return []


def rule_H20(ctx: RuleContext) -> List[Issue]:
    """H20 需求中的属性未覆盖（启发）"""
    req = ctx.diagram.requirement_text
    if not req:
        return []
    designed = _designed_terms(ctx)
    missing = [
        key for key, syns in _REQUIREMENT_ATTRS.items()
        if any(s in req for s in syns) and key not in designed
    ]
    if missing:
        return [_warn("H20", "", f"需求中提到的属性未出现在 ER 图中：{'、'.join(missing)}")]
    return []


def rule_H21(ctx: RuleContext) -> List[Issue]:
    """H21 命名与需求用词不一致（启发，编辑距离近似）"""
    req = ctx.diagram.requirement_text
    if not req:
        return []
    out = []
    for e in ctx.diagram.elements.values():
        n = e.name
        if not n:
            continue
        for key, syns in _REQUIREMENT_SYNONYMS.items():
            if n in syns and n != key and key in req:
                out.append(_warn(
                    "H21", e.id,
                    f"需求中使用'{key}'，图中命名为'{n}'，建议统一"))
                break
    return out


# ======================================================================
# 规则注册表：rule_id -> (函数, 触发事件列表)
# ======================================================================

# 元素级规则触发事件
EV_ELEMENT = ["element_added", "element_modified"]
# 连线级规则触发事件
EV_CONNECTION = ["connection_added", "connection_modified"]
# 删除事件（可能造成悬空/孤立）
EV_DELETED = ["element_deleted"]
# 图结构级 & 需求级：挂通配，仅在有全图快照时放行
EV_GLOBAL = ["*"]

RULE_SPECS: List[tuple] = [
    # --- 元素级 -------------------------------------------------------
    ("R01", rule_R01, EV_ELEMENT),
    ("R02", rule_R02, EV_ELEMENT),
    ("R03", rule_R03, EV_ELEMENT),
    ("R04", rule_R04, EV_ELEMENT),
    ("R05", rule_R05, EV_ELEMENT),
    ("R06", rule_R06, EV_ELEMENT),
    ("R07", rule_R07, EV_ELEMENT),
    ("R08", rule_R08, EV_ELEMENT),
    ("R09", rule_R09, EV_ELEMENT),
    ("H01", rule_H01, EV_ELEMENT),
    ("H02", rule_H02, EV_ELEMENT),
    ("H03", rule_H03, EV_ELEMENT),
    ("H04", rule_H04, EV_ELEMENT),
    ("H06", rule_H06, EV_ELEMENT),
    ("H07", rule_H07, EV_ELEMENT),
    ("H08", rule_H08, EV_ELEMENT),
    # --- 连线级 -------------------------------------------------------
    ("R10", rule_R10, EV_CONNECTION + EV_DELETED),
    ("R11", rule_R11, EV_CONNECTION),
    ("R12", rule_R12, EV_CONNECTION),
    ("R13", rule_R13, EV_CONNECTION),
    ("R14", rule_R14, EV_CONNECTION),
    ("R15", rule_R15, EV_CONNECTION),
    ("R16", rule_R16, EV_CONNECTION),
    ("H09", rule_H09, EV_CONNECTION),
    ("H10", rule_H10, EV_CONNECTION),
    ("H11", rule_H11, EV_CONNECTION + EV_DELETED),
    # --- 图结构级 -----------------------------------------------------
    ("R17", rule_R17, EV_CONNECTION + EV_DELETED),
    ("R18", rule_R18, EV_CONNECTION + EV_DELETED),
    ("R19", rule_R19, EV_CONNECTION + EV_DELETED),
    ("R20", rule_R20, EV_GLOBAL),
    ("R21", rule_R21, EV_GLOBAL),
    ("R22", rule_R22, EV_GLOBAL),
    ("R23", rule_R23, EV_GLOBAL),
    ("H05", rule_H05, EV_GLOBAL),
    ("H12", rule_H12, EV_GLOBAL),
    ("H13", rule_H13, EV_GLOBAL),
    ("H14", rule_H14, EV_GLOBAL),
    ("H15", rule_H15, EV_GLOBAL),
    ("H16", rule_H16, EV_GLOBAL),
    ("H17", rule_H17, EV_GLOBAL),
    # --- 需求对齐 -----------------------------------------------------
    ("H18", rule_H18, EV_GLOBAL),
    ("H19", rule_H19, EV_GLOBAL),
    ("H20", rule_H20, EV_GLOBAL),
    ("H21", rule_H21, EV_GLOBAL),
]

# 规则元信息（供自检与文档核对）
RULE_IDS: List[str] = [rid for rid, _, _ in RULE_SPECS]

# ----------------------------------------------------------------------
# 显式等级声明（v1.3 起关键改动）
# ----------------------------------------------------------------------
# INTERFACE.md 的编号规范（R=刚性红 / H=启发橙）在 v1.1–v1.3 的教学审查后
# 出现了三处**有意偏离**：R07（复合主键合法）、R13（ISA 直连合法）、
# R16（基数写错位置属操作失误）改为启发级 warn。教学正确性 > 前缀字面义。
#
# 因此"前缀"与"等级"自 v1.3 起是**两个独立概念**：
#   - 前缀只是历史编号，运行时上色以 issue.level 为准（前端 highlight.ts）
#   - 等级以本表声明为准；未列出的规则按前缀默认
# 契约偏离已在 PROTOCOL-EXTENSIONS.md 与 RULES.md 记录。
LEVEL_OVERRIDE: Dict[str, str] = {
    "R07": "warn",   # 多个主键属性——可能是合法的复合主键
    "R09": "warn",   # 属性名与实体名相同——命名质量建议，提示语本身就说"建议"
    "R13": "warn",   # 实体间直接连线——可能是 ISA 继承
    "R16": "warn",   # 普通连线标基数——操作失误，不损坏模型
}


def level_of(rule_id: str) -> str:
    """规则的运行时等级（v1.3 起以前缀默认 + 显式覆盖表为准）。"""
    if rule_id in LEVEL_OVERRIDE:
        return LEVEL_OVERRIDE[rule_id]
    return "error" if rule_id.startswith("R") else "warn"


# 派生集合：按**实际等级**统计（此前按前缀统计，把 R07/R13/R16 错算成刚性）
RIGID_IDS = [r for r in RULE_IDS if level_of(r) == "error"]
HEURISTIC_IDS = [r for r in RULE_IDS if level_of(r) == "warn"]

assert len(RULE_IDS) == len(set(RULE_IDS)), "规则编号重复"
assert len(RULE_IDS) >= 35, f"规则数不足 35，当前 {len(RULE_IDS)}"
