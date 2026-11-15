# -*- coding: utf-8 -*-
"""
LLM 深度归因层（研究内容三：统计 + LLM 归因）
=============================================

对应需求书：
    「使用 LLM 深度归因：将学生的错误历史、错误类型分布、设计上下文
      输入大模型，生成自然语言诊断报告。」
    「采用"规则引擎优先、LLM 异步增强"的混合策略：规则引擎完成毫秒级
      实时校验，LLM 在后台进行语义级深度分析，结果以非侵入式提示呈现。」

本模块的职责边界：
    - 只做**归因与建议生成**，不参与实时校验（实时校验在 engine.py，
      毫秒级，绝不等待本模块）。
    - 提供 **Provider 抽象**：有真实 LLM 就用；没有（离线/未配 key）
      则用本地启发式生成同结构的诊断，保证功能始终可用、可测试。

设计取舍说明：
    为什么不直接依赖某个具体大模型 API？
      1) 教学场景常在离线/内网环境，不能假设有外网与 key；
      2) 本项目要求"开源模型本地部署"，部署形态未定（Ollama/vLLM）；
      3) 硬依赖会让测试与演示无法在没有模型时运行。
    故把"生成"抽象成 Provider，默认用启发式兜底，真实 LLM 作为可选增强。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from weakness import TRACKER, ViolationRecord, WeaknessTracker


# ======================================================================
# 诊断报告结构
# ======================================================================

@dataclass
class Diagnosis:
    """
    一份学情诊断报告。

    source 字段标明来源，便于教师判断可信度（需求书要求"保留教师复核空间，
    LLM 诊断结果以'可能性等级'呈现"）：
        "heuristic" = 本地规则生成（确定性，可解释）
        "llm"       = 大模型生成（语义深度，但可能有偏差）
    """

    user_id: str
    source: str
    summary: str                       # 一段自然语言总述
    weak_points: List[Dict] = field(default_factory=list)   # 高频薄弱点
    suggestions: List[str] = field(default_factory=list)    # 个性化学习建议
    error_profile: Dict = field(default_factory=dict)       # 错误类型分布
    generated_at: float = 0.0
    meta: Dict = field(default_factory=dict)                # 耗时/provider 等

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "source": self.source,
            "summary": self.summary,
            "weak_points": self.weak_points,
            "suggestions": self.suggestions,
            "error_profile": self.error_profile,
            "generated_at": self.generated_at,
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(self.generated_at)),
            "meta": self.meta,
        }


# ======================================================================
# 规则知识库：把 rule_id 映射成"知识点 / 学习建议"
# ======================================================================

# 每条规则对应：知识点名称、一句话解释、学习建议
RULE_KNOWLEDGE: Dict[str, Dict[str, str]] = {
    "R01": {"topic": "元素命名", "why": "ER 图中每个元素都必须有名称才能被理解",
            "advice": "先给图形起名再画连线，命名是设计的第一步"},
    "R02": {"topic": "主键完整性", "why": "实体必须有能唯一标识实例的主键",
            "advice": "复习「主键/候选键」一节，注意主键用 * 前缀标注"},
    "R03": {"topic": "属性命名", "why": "属性无名无法判断其含义",
            "advice": "每个属性椭圆都应写上属性名"},
    "R04": {"topic": "联系命名", "why": "联系无名无法表达实体间的语义",
            "advice": "联系名建议用动词或动宾短语，如「选修」「属于」"},
    "R05": {"topic": "弱实体标识", "why": "弱实体的标识由「强实体主键 + 自身部分键」构成",
            "advice": "复习弱实体与鉴别器（部分键用 # 前缀），不要给弱实体另立独立主键"},
    "R06": {"topic": "属性完整性", "why": "空白属性名说明编辑未完成",
            "advice": "检查是否有未填完的属性"},
    "R07": {"topic": "主键设计", "why": "多个 * 可能是复合主键，也可能是误标",
            "advice": "复习复合主键：多个属性共同唯一标识实例是合法的，确认后再保留"},
    "R08": {"topic": "属性唯一性", "why": "同一实体内属性名重复会造成歧义",
            "advice": "同一实体的属性名应各不相同"},
    "R09": {"topic": "命名规范", "why": "属性名与实体名相同易混淆",
            "advice": "避免「学生.学生」这类重名，属性名应描述具体特征"},
    "R10": {"topic": "连线完整性", "why": "连线端点必须指向真实存在的元素",
            "advice": "检查是否有悬空连线（可能是删除元素后残留）"},
    "R11": {"topic": "连线合法性", "why": "连线不能自连",
            "advice": "确认连线两端是不同的元素"},
    "R12": {"topic": "连线唯一性", "why": "端点、类型、基数全同的连线是重复的",
            "advice": "注意：递归联系的两条分支线基数不同，不算重复"},
    "R13": {"topic": "联系表达", "why": "实体间直接连线多数情况是漏画了联系菱形",
            "advice": "若表达关联请用菱形联系；若表达 ISA 继承则可直连"},
    "R14": {"topic": "基数标注", "why": "联系分支线必须标基数才能表达数量关系",
            "advice": "复习 Chen 记法：在联系分支线上写 1 / N / M / P"},
    "R15": {"topic": "基数合法性", "why": "基数只允许 1 / N / M / P",
            "advice": "注意基数符号的书写规范"},
    "R16": {"topic": "基数位置", "why": "基数只有写在联系分支线上才有语义",
            "advice": "检查是否把基数写到了属性线或普通连线上"},
    "R17": {"topic": "基数完整性", "why": "联系必须标注基数",
            "advice": "每条联系的两个（或多个）分支线都要标基数"},
    "R18": {"topic": "联系连通性", "why": "联系至少应连接两个实体",
            "advice": "检查是否有联系只连了一个实体"},
    "R19": {"topic": "联系连通性", "why": "孤立菱形说明联系还没画完",
            "advice": "把联系的各端都连到实体上"},
    "R20": {"topic": "联系命名唯一性", "why": "同名联系会造成语义混淆",
            "advice": "不同联系应使用不同名称"},
    "R21": {"topic": "实体命名唯一性", "why": "同名实体会造成设计歧义",
            "advice": "同一张图中实体名应唯一"},
    "R22": {"topic": "设计完整性", "why": "ER 图至少应包含一个实体",
            "advice": "从识别业务中的实体开始设计"},
    "R23": {"topic": "弱实体依赖", "why": "弱实体必须通过联系依赖某个强实体",
            "advice": "复习弱实体：它的存在依赖于强实体，需用双线矩形并连到强实体"},
    "H01": {"topic": "实体命名规范", "why": "实体是「一类事物」，宜用单数名词",
            "advice": "用「学生」而非「学生们」"},
    "H02": {"topic": "联系命名规范", "why": "联系表达动作或关联，宜用动词",
            "advice": "用「选修」「属于」这类动词命名；业务惯例名可保留"},
    "H03": {"topic": "多值属性", "why": "电话、地址等属性可能有多个值",
            "advice": "复习多值属性：可拆为独立实体，或用双线椭圆表示"},
    "H04": {"topic": "派生属性", "why": "年龄等可由其他属性算出",
            "advice": "复习派生属性：不直接存储，用虚线椭圆表示"},
    "H05": {"topic": "命名风格统一", "why": "同类元素命名风格混用影响可读性",
            "advice": "同一类元素统一用中文或统一用英文"},
    "H06": {"topic": "范式与拆分", "why": "属性过多的实体可能存在冗余",
            "advice": "检查是否符合范式，考虑是否需要拆分实体"},
    "H07": {"topic": "名称规范", "why": "名称中的多余空格或符号影响规范性",
            "advice": "清理名称中的空格与特殊符号"},
    "H08": {"topic": "名称简洁性", "why": "过长的名称影响图的可读性",
            "advice": "精简名称，把细节放到属性里"},
    "H09": {"topic": "联系表达", "why": "实体间用联系分支线直连不规范",
            "advice": "实体之间应通过菱形联系连接"},
    "H10": {"topic": "属性归属", "why": "属性归属连线方向应统一",
            "advice": "属性椭圆的连线建议由属性指向实体"},
    "H11": {"topic": "联系完整性", "why": "联系未连完说明设计未完成",
            "advice": "补齐联系的另一端实体"},
    "H12": {"topic": "实体连通性", "why": "孤立实体未参与任何联系",
            "advice": "确认该实体是否需要与其他实体建立联系"},
    "H13": {"topic": "整体设计", "why": "多实体之间应有联系才有意义",
            "advice": "识别实体之间的业务关联并画上联系"},
    "H14": {"topic": "基数判断", "why": "各端基数均为 1 表示一对一",
            "advice": "确认确实是一对一；若是 ISA 继承可忽略"},
    "H15": {"topic": "多元联系", "why": "三元以上联系的基数组合较复杂",
            "advice": "复习三元联系：M:N:P 是常见形式"},
    "H16": {"topic": "属性完整性", "why": "仅有主键的实体缺少描述性信息",
            "advice": "补充该实体的描述性属性"},
    "H17": {"topic": "设计规模", "why": "实体过少可能遗漏业务对象",
            "advice": "回到需求，检查是否还有未识别的实体"},
    "H18": {"topic": "需求对齐", "why": "需求提到的实体未在图中出现",
            "advice": "对照需求文本，补齐遗漏的实体"},
    "H19": {"topic": "需求对齐", "why": "需求提到的联系未在图中出现",
            "advice": "对照需求文本，补齐遗漏的联系"},
    "H20": {"topic": "需求对齐", "why": "需求提到的属性未在图中出现",
            "advice": "对照需求文本，补齐遗漏的属性"},
    "H21": {"topic": "命名一致性", "why": "图中命名与需求用词不一致",
            "advice": "统一图与需求的用词，便于对照检查"},
}


def knowledge_of(rule_id: str) -> Dict[str, str]:
    return RULE_KNOWLEDGE.get(rule_id, {
        "topic": "设计规范", "why": "该规则用于检查设计规范性",
        "advice": "请根据提示调整设计"})


# ======================================================================
# Provider 抽象
# ======================================================================

class DiagnosisProvider:
    """诊断生成器的接口。"""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def generate(self, prompt: str, profile: Dict) -> str:
        """返回自然语言诊断正文。"""
        raise NotImplementedError


class HeuristicProvider(DiagnosisProvider):
    """
    本地启发式生成器（默认兜底）。

    为什么需要它：
        教学工具必须能在**无外网、无 API key、无本地模型**时照常给出诊断。
        且它输出确定性结果，便于测试与演示。

    它不是"假 LLM"——而是把教育领域知识（RULE_KNOWLEDGE）与统计特征
    结合的确定性归因，可靠性高于大模型，只是语义深度有限。
    """

    name = "heuristic"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, profile: Dict) -> str:
        user_id = profile.get("user_id", "该同学")
        total = profile.get("total", 0)
        rigid = profile.get("error_count", 0)
        hint = profile.get("warning_count", 0)
        weak = profile.get("weak_points", [])

        if total == 0:
            return f"{user_id}本次绘图未触发任何规则问题，设计规范良好。"

        lines = []
        # 总体判断
        if rigid == 0:
            lines.append(
                f"{user_id}本次共触发 {total} 条提示，其中**没有刚性错误**，"
                f"基础规范掌握良好；另有 {hint} 条优化建议可供参考。")
        else:
            lines.append(
                f"{user_id}本次共触发 {total} 条提示，其中刚性错误 {rigid} 条、"
                f"优化建议 {hint} 条。刚性错误会直接影响 ER 模型的正确性，建议优先修复。")

        # 薄弱点分析（取前 3）
        if weak:
            lines.append("")
            lines.append("**主要薄弱点：**")
            for i, w in enumerate(weak[:3], 1):
                k = knowledge_of(w["rule_id"])
                pct = int(w.get("share", 0) * 100)
                lines.append(
                    f"{i}. 「{k['topic']}」（{w['rule_id']}，出现 {w['count']} 次，"
                    f"占比 {pct}%）—— {k['why']}。")

            # 归因：区分"概念不清"与"操作疏忽"
            top = weak[0]
            topic = knowledge_of(top["rule_id"])["topic"]
            if top["count"] >= 3:
                lines.append("")
                lines.append(
                    f"其中「{topic}」反复出现 {top['count']} 次，"
                    f"更可能是**概念理解**问题而非偶发疏忽，建议重点复习该知识点。")
            elif len(weak) >= 3:
                lines.append("")
                lines.append(
                    f"薄弱点分布较广（涉及 {len(weak)} 类规则），"
                    f"建议按上面的顺序逐个梳理，而不是一次全部修改。")

        return "\n".join(lines)


class OpenAICompatProvider(DiagnosisProvider):
    """
    OpenAI 兼容接口的 Provider（可选）。

    适配大多数国内开源模型的部署方式：Ollama、vLLM、LM Studio 等
    都提供 OpenAI 兼容的 /v1/chat/completions。

    环境变量：
        ER_LLM_BASE_URL   如 http://localhost:11434/v1
        ER_LLM_API_KEY    本地部署通常任意值
        ER_LLM_MODEL      如 qwen2.5:14b
    未配置时 available() 返回 False，自动退回启发式。
    """

    name = "llm"

    def __init__(self) -> None:
        self.base_url = (os.environ.get("ER_LLM_BASE_URL") or "").rstrip("/")
        self.api_key = os.environ.get("ER_LLM_API_KEY") or "not-needed"
        self.model = os.environ.get("ER_LLM_MODEL") or ""
        self.timeout = float(os.environ.get("ER_LLM_TIMEOUT", "30"))

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def generate(self, prompt: str, profile: Dict) -> str:
        url = f"{self.base_url}/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "你是一名数据库原理课程的助教，"
                            "负责分析学生在 ER 图设计中的错误并给出学习建议。"
                            "回答要具体、有教学价值，不要空泛。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()


# ======================================================================
# Prompt 构造
# ======================================================================

PROMPT_TEMPLATE = """以下是学生在《数据库原理及应用》课程中绘制 ER 图时的错误记录，请生成一份学习诊断报告。

## 错误统计
- 总提示数：{total}（刚性错误 {error_count} 条，优化建议 {warning_count} 条）
- 设计上下文：绘图时画布上有 {elements} 个元素、{connections} 条连线

## 错误类型分布（按出现次数排序）
{by_rule_text}

## 请输出
1. **整体评价**：该学生的设计规范掌握情况（2-3 句）
2. **主要薄弱点归因**：指出最突出的 2-3 个知识点，并分析是「概念理解不足」还是「操作疏忽」
3. **个性化学习建议**：针对薄弱点给出可操作的学习路径

要求：结合数据库课程知识点讲解，避免空泛套话；不要复述规则编号，要说人话。"""


def build_prompt(profile: Dict) -> str:
    """把统计档案转成给大模型的 Prompt。"""
    by_rule = profile.get("by_rule", [])[:8]
    lines = []
    for item in by_rule:
        k = knowledge_of(item["rule_id"])
        lines.append(
            f"- {k['topic']}（{item['rule_id']}）：{item['count']} 次 —— {k['why']}")
    by_rule_text = "\n".join(lines) if lines else "（无）"

    ctx = {}
    recs = profile.get("_records") or []
    if recs:
        ctx = recs[0].context or {}

    return PROMPT_TEMPLATE.format(
        total=profile.get("total", 0),
        error_count=profile.get("error_count", 0),
        warning_count=profile.get("warning_count", 0),
        elements=ctx.get("elements", "?"),
        connections=ctx.get("connections", "?"),
        by_rule_text=by_rule_text,
    )


# ======================================================================
# 归因器
# ======================================================================

class Diagnoser:
    """
    学情归因器：把统计档案 → 诊断报告。

    调度策略（对齐需求书）：
        - 默认用启发式（确定性、快、无需外部依赖）
        - 配了真实 LLM 就用 LLM，失败时**自动降级**回启发式，
          保证任何情况下都能给出诊断
    """

    def __init__(self, tracker: Optional[WeaknessTracker] = None,
                 provider: Optional[DiagnosisProvider] = None) -> None:
        self.tracker = tracker or TRACKER
        self.provider = provider or self._default_provider()

    @staticmethod
    def _default_provider() -> DiagnosisProvider:
        llm = OpenAICompatProvider()
        if llm.available():
            return llm
        return HeuristicProvider()

    def diagnose_user(self, user_id: str, top_n: int = 3,
                      force_source: Optional[str] = None) -> Diagnosis:
        """生成某学生的诊断报告。"""
        t0 = time.perf_counter()
        summary = self.tracker.summary(user_id, top_n=top_n)
        recs = self.tracker.records_of(user_id)
        profile = dict(summary)
        profile["user_id"] = user_id
        profile["_records"] = recs

        # 默认启发式产出"结构化解读"（薄弱点、建议）
        weak_points = []
        for w in summary.get("weak_points", []):
            k = knowledge_of(w["rule_id"])
            weak_points.append({
                **w,
                "topic": k["topic"],
                "why": k["why"],
                "advice": k["advice"],
            })

        suggestions = [w["advice"] for w in weak_points]

        # 生成自然语言正文
        source = "heuristic"
        provider = self.provider
        if force_source == "heuristic":
            provider = HeuristicProvider()
        elif force_source == "llm":
            provider = OpenAICompatProvider()
            if not provider.available():
                provider = HeuristicProvider()

        try:
            if isinstance(provider, HeuristicProvider):
                text = provider.generate("", profile)
                source = "heuristic"
            else:
                text = provider.generate(build_prompt(profile), profile)
                source = provider.name
        except Exception as ex:
            # LLM 失败 → 自动降级，绝不让诊断整体失败
            fallback = HeuristicProvider()
            text = fallback.generate("", profile)
            source = "heuristic"
            profile["llm_error"] = str(ex)

        dt_ms = (time.perf_counter() - t0) * 1000
        return Diagnosis(
            user_id=user_id,
            source=source,
            summary=text,
            weak_points=weak_points,
            suggestions=suggestions,
            error_profile={
                "total": summary.get("total", 0),
                "error_count": summary.get("error_count", 0),
                "warning_count": summary.get("warning_count", 0),
                "by_rule": summary.get("by_rule", []),
                "by_level": summary.get("by_level", {}),
            },
            generated_at=time.time(),
            meta={"elapsed_ms": round(dt_ms, 2),
                  "provider": self.provider.name},
        )

    def diagnose_class(self, top_n: int = 5) -> Dict:
        """班级整体学情摘要（对应需求书"自动为教师生成整体学情分析报告"）。"""
        cs = self.tracker.class_summary(top_n=top_n)
        n = cs.get("student_count", 0)
        issues = cs.get("common_issues", [])

        if n == 0:
            return {**cs, "summary": "暂无学生绘图数据。", "teaching_advice": []}

        lines = [f"本次共记录 {n} 名学生的绘图数据。"]
        advice = []
        if issues:
            top = issues[0]
            k = knowledge_of(top["rule_id"])
            pct = int(top["student_share"] * 100)
            lines.append(
                f"最突出的共性问题是「{k['topic']}」："
                f"{pct}% 的学生（{top['student_count']}/{n} 人）出现过，"
                f"累计 {top['total_count']} 次。")
            lines.append(f"该知识点为：{k['why']}。")
            advice.append(
                f"建议在课堂上集中讲解「{k['topic']}」，"
                f"并安排针对性练习（{pct}% 学生存在困难）。")

            for item in issues[1:3]:
                k2 = knowledge_of(item["rule_id"])
                p2 = int(item["student_share"] * 100)
                lines.append(
                    f"其次是「{k2['topic']}」，{p2}% 的学生出现过。")
                if p2 >= 30:
                    advice.append(
                        f"「{k2['topic']}」也有 {p2}% 学生存在困难，"
                        f"可作为课堂补充内容。")
        else:
            lines.append("未发现明显的共性问题，整体掌握情况良好。")

        return {
            **cs,
            "summary": "\n".join(lines),
            "teaching_advice": advice,
        }


# 全局归因器
DIAGNOSER = Diagnoser()
