# -*- coding: utf-8 -*-
"""
ER 规则引擎（调度层）
=====================

职责：
    1) 构建规则字典树（按事件类型索引）
    2) 收到检查请求 → 选出相关规则子集 → 执行 → 按协议组包
    3) 维护会话级图缓存（单元素事件也需要全图才能判图结构级规则）

输出严格遵循 INTERFACE.md：
    单次： {"action":"result",  "element_id":..., "violations":[...], "suggestions":[...]}
    批量： {"action":"batch_result", "results": {id: {violations, suggestions}}}
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from model import Diagram, Element
from rules import RULE_SPECS, RuleContext, Issue
from trie import (
    EVENT_BATCH_CHECK,
    EVENT_ELEMENT_DELETED,
    EVENT_ELEMENT_ADDED,
    EVENT_ELEMENT_MODIFIED,
    EVENT_CONNECTION_ADDED,
    EVENT_CONNECTION_MODIFIED,
    WILDCARD,
    RuleTrie,
)
import weakness as ws_mod


# ----------------------------------------------------------------------
# 字典树构建
# ----------------------------------------------------------------------

def build_trie() -> Tuple[RuleTrie, Dict[str, object]]:
    """按 RULE_SPECS 构建字典树，返回 (trie, rule_id -> 函数)。"""
    trie = RuleTrie()
    fn_by_id: Dict[str, object] = {}
    for rule_id, fn, events in RULE_SPECS:
        fn_by_id[rule_id] = fn
        trie.insert_many(events, fn)
    return trie, fn_by_id


TRIE, RULE_FN_BY_ID = build_trie()

# 规则 id 反查（函数 -> id），用于把 Issue 归位到目标元素
RULE_ID_BY_FN: Dict[int, str] = {id(fn): rid for rid, fn, _ in RULE_SPECS}


# ----------------------------------------------------------------------
# 会话状态（图缓存）
# ----------------------------------------------------------------------

class Session:
    """
    一个 WebSocket 连接的会话状态。

    单元素/单连线事件只带被改动的那个对象，但图结构级规则
    （如"联系是否连了 2 个实体"）需要全图。故服务端缓存全图快照：
      - element_added/modified → upsert 元素（若带 attributes 等）
      - element_deleted        → 移除元素
      - connection_added/modified → upsert 连线
      - batch_check            → 整体替换
    """

    def __init__(self) -> None:
        self.elements: Dict[str, dict] = {}
        self.connections: Dict[str, dict] = {}
        self.requirement_text: str = ""
        self._fingerprint: Optional[tuple] = None
        # 上一次校验产出的全部 issue（用于识别"本次新出现的问题"）
        self.last_issues: List[Issue] = []

    def compute_fingerprint(self) -> tuple:
        return graph_fingerprint(self)

    def graph_changed(self) -> bool:
        """图结构是否相对上次检查发生了变化。"""
        fp = self.compute_fingerprint()
        if fp != self._fingerprint:
            self._fingerprint = fp
            return True
        return False

    def upsert_element(self, el: Optional[dict]) -> None:
        if isinstance(el, dict) and el.get("id"):
            # 合并：单元素事件可能不带 position，保留已有字段
            cur = self.elements.get(el["id"], {})
            merged = {**cur, **{k: v for k, v in el.items() if v is not None}}
            self.elements[el["id"]] = merged

    def remove_element(self, el: Optional[dict]) -> None:
        if isinstance(el, dict) and el.get("id"):
            self.elements.pop(el["id"], None)
            # 连带清掉挂在该元素上的连线（服务端视角保持自洽）
            self.connections = {
                cid: c for cid, c in self.connections.items()
                if c.get("from") != el["id"] and c.get("to") != el["id"]
            }

    def upsert_connection(self, conn: Optional[dict]) -> None:
        if isinstance(conn, dict) and conn.get("id"):
            cur = self.connections.get(conn["id"], {})
            merged = {**cur, **{k: v for k, v in conn.items() if v is not None}}
            self.connections[conn["id"]] = merged

    def replace_all(self, elements: List[dict], connections: List[dict],
                    requirement_text: str = "") -> None:
        self.elements = {
            e["id"]: e for e in (elements or []) if isinstance(e, dict) and e.get("id")
        }
        self.connections = {
            c["id"]: c for c in (connections or []) if isinstance(c, dict) and c.get("id")
        }
        if requirement_text:
            self.requirement_text = requirement_text

    def to_diagram(self) -> Diagram:
        return Diagram(
            list(self.elements.values()),
            list(self.connections.values()),
            requirement_text=self.requirement_text,
        )


# ----------------------------------------------------------------------
# 规则选择（核心：只跑子集，不跑全量）
# ----------------------------------------------------------------------

def select_rules(event: str, has_full_graph: bool, graph_dirty: bool = True) -> List[object]:
    """
    按事件选出应执行的规则函数。

    - batch_check：整图检查，语义上等价于"所有规则各跑一遍"，直接返回全量；
    - 其余事件：精确分支（该事件挂载的规则）
                + 通配分支（图结构级 / 需求对齐级）

    通配分支的放行条件（graph_dirty）：
        图结构级规则（孤立实体、重名、多实体无联系…）只有在
        "图结构发生变化"时才需要重算。若本次事件只改了标签/属性文本、
        并未增删元素或连线，这些规则的结果必然不变，直接跳过。

        这既保证正确性（结果不变则不重算），又让索引真正生效：
        纯文本编辑时 element_added 只跑 16 条而非 31 条。

    注：batch_check 走全量是刻意的——它是导入/打开已有设计时的一次性体检，
    与绘图过程中的增量检查目标不同；此时延迟预算是整图而非单笔操作。
    """
    if event == EVENT_BATCH_CHECK:
        return TRIE.all_rules()
    selected = TRIE.match(event)
    if has_full_graph and graph_dirty:
        selected = _dedup(selected + TRIE.match(WILDCARD))
    return selected


def _dedup(fns: List[object]) -> List[object]:
    seen, out = set(), []
    for f in fns:
        if id(f) not in seen:
            seen.add(id(f))
            out.append(f)
    return out


def graph_fingerprint(session: "Session") -> tuple:
    """
    图结构指纹：只纳入"影响图结构级规则"的字段。

    纳入：元素 id/形状/名称/弱实体标记、属性列表、连线两端与类型。
    不纳入：position（画布坐标，后端不参与校验）、连线 label。

    若指纹不变，则图结构级规则的结果必然与上次相同，可安全跳过。
    """
    els = tuple(sorted(
        (eid, e.get("shape", ""), str(e.get("label") or ""),
         bool(e.get("is_weak")), tuple(str(a) for a in (e.get("attributes") or [])))
        for eid, e in session.elements.items()
    ))
    conns = tuple(sorted(
        (cid, c.get("from", ""), c.get("to", ""), c.get("type", ""))
        for cid, c in session.connections.items()
    ))
    return (els, conns, session.requirement_text)


# ----------------------------------------------------------------------
# 执行
# ----------------------------------------------------------------------

def run_rules(
    diagram: Diagram,
    event: str = "",
    target_element: Optional[Element] = None,
    target_connection=None,
    changes: Optional[dict] = None,
    has_full_graph: bool = True,
    graph_dirty: bool = True,
) -> List[Issue]:
    """执行选中规则，返回原始 Issue 列表。"""
    ctx = RuleContext(
        diagram=diagram,
        event=event,
        target_element=target_element,
        target_connection=target_connection,
        changes=changes,
        has_full_graph=has_full_graph,
    )
    issues: List[Issue] = []
    for fn in select_rules(event, has_full_graph, graph_dirty):
        try:
            result = fn(ctx)
            if result:
                issues.extend(result)
        except Exception as ex:  # 规则自身的 bug 不应拖垮整个检查
            rid = RULE_ID_BY_FN.get(id(fn), getattr(fn, "__name__", "unknown"))
            issues.append(Issue(rid, "error", f"规则执行异常: {ex}", ""))
    return issues


# ----------------------------------------------------------------------
# 组包（按协议分流 violations / suggestions）
# ----------------------------------------------------------------------

def _split(issues: List[Issue], focus_id: str = "") -> Dict[str, List[dict]]:
    """
    把 Issue 分成 violations(level=error) 与 suggestions(level=warn)。

    归位策略：一条 issue 面向"它的目标元素"，但协议的回包是按
    请求中的 element_id 组织的。故：
      - 若 issue.target_id 为空（图级问题）→ 归给本次焦点元素
      - 若 issue.target_id == 焦点 → 归给焦点
      - 否则（问题在别的元素上）→ 也归给焦点，避免结果丢失
        （前端按 element_id 取结果，丢了学生就看不到提示）

    注：批量模式不做归位，直接按各元素自身 id 分发。
    """
    violations, suggestions = [], []
    for it in issues:
        payload = {
            "rule_id": it["rule_id"],
            "level": it["level"],
            "message": it["message"],
        }
        if it["level"] == "error":
            violations.append(payload)
        else:
            suggestions.append(payload)
    return {"violations": violations, "suggestions": suggestions}


def check_single(session: Session, msg: dict) -> dict:
    """处理 action=check。"""
    event = str(msg.get("event") or "")
    element_raw = msg.get("element") if isinstance(msg.get("element"), dict) else None
    conn_raw = msg.get("connection") if isinstance(msg.get("connection"), dict) else None

    # 1) 先更新会话缓存
    if event in (EVENT_ELEMENT_ADDED, EVENT_ELEMENT_MODIFIED):
        session.upsert_element(element_raw)
    elif event == EVENT_ELEMENT_DELETED:
        session.remove_element(element_raw)
    elif event in (EVENT_CONNECTION_ADDED, EVENT_CONNECTION_MODIFIED):
        session.upsert_connection(conn_raw)

    # 2) 以"更新后的全图"建模
    diagram = session.to_diagram()
    has_full = bool(session.elements) or event == EVENT_BATCH_CHECK
    # 图结构是否变化：未变则可跳过图结构级规则（结果必然与上次相同）
    graph_dirty = session.graph_changed()

    target_el = None
    if element_raw and element_raw.get("id"):
        target_el = diagram.get(str(element_raw["id"]))
    target_conn = None
    if conn_raw and conn_raw.get("id"):
        target_conn = diagram.connections.get(str(conn_raw["id"]))

    focus_id = ""
    if element_raw:
        focus_id = str(element_raw.get("id") or "")
    elif conn_raw:
        focus_id = str(conn_raw.get("id") or "")

    issues = run_rules(
        diagram,
        event=event,
        target_element=target_el,
        target_connection=target_conn,
        changes=msg.get("changes") if isinstance(msg.get("changes"), dict) else None,
        has_full_graph=has_full,
        graph_dirty=graph_dirty,
    )

    # 3) 只回"与本次焦点相关"的提示 + 本次新出现的问题，
    #    避免每画一笔就刷全图报错，同时不丢掉挂在别处的**新增**问题
    #    （如把实体改名造成重名，R21 报在另一个实体上）
    focused = _focus_filter(issues, focus_id, event,
                            prev_issues=session.last_issues)
    session.last_issues = issues
    body = _split(focused, focus_id)
    return {
        "action": "result",
        "element_id": focus_id,
        "violations": body["violations"],
        "suggestions": body["suggestions"],
    }


def _focus_filter(issues: List[Issue], focus_id: str, event: str,
                  prev_issues: Optional[List[Issue]] = None) -> List[Issue]:
    """
    焦点过滤：单元素/单连线事件只回与该对象相关的提示 + 图级提示。

    为什么不能只按 target_id == focus_id 过滤（真实缺陷）：
        有些规则的"报告对象"不是被编辑的那个元素。典型是 **R21 实体重名**——
        它报告在**首个**重名元素上（e1），而学生改的是 e2。
        若只留 target_id == e2，这条重名警告就永远到不了学生眼前
        （实测：把 e2 改名成与 e1 同名，前端收不到 R21）。

    修正策略（保留"不刷屏"的初衷，同时不丢新增问题）：
        - 保留 target_id 为空（图级）或 == focus_id 的问题；
        - **额外保留"本次新出现的问题"**——即 在 issues 里、但不在
          prev_issues 里的 (rule_id, target_id, message)。
          这类问题正是本次操作引发的，必须告知学生，
          哪怕它挂在别的元素 id 上。
        - 已经在 prev_issues 里存在过的问题不重复回，避免每画一笔刷全图。

    element_deleted 例外：删除会影响全图（悬空/孤立），放开全部。
    """
    if event == EVENT_ELEMENT_DELETED or not focus_id:
        return issues

    prev_keys = set()
    for it in (prev_issues or []):
        prev_keys.add((it["rule_id"], it.target_id, it["message"]))

    out = []
    for it in issues:
        tid = it.target_id
        if not tid or tid == focus_id:
            out.append(it)
            continue
        # 挂在别的元素上，但如果是本次新出现的，也要回
        key = (it["rule_id"], it.target_id, it["message"])
        if key not in prev_keys:
            out.append(it)
    return out


def check_batch(session: Session, msg: dict) -> dict:
    """处理 action=batch_check（整图一次性检查）。"""
    diagram_raw = msg.get("diagram") if isinstance(msg.get("diagram"), dict) else {}
    elements = diagram_raw.get("elements") if isinstance(diagram_raw.get("elements"), list) else []
    connections = diagram_raw.get("connections") if isinstance(diagram_raw.get("connections"), list) else []
    req_text = str(msg.get("requirement_text") or diagram_raw.get("requirement_text") or "")

    session.replace_all(elements, connections, requirement_text=req_text)
    diagram = session.to_diagram()

    issues = run_rules(diagram, event=EVENT_BATCH_CHECK, has_full_graph=True)

    # 批量：按每个元素自身 id 分发
    results: Dict[str, Dict[str, List[dict]]] = {}
    for eid in list(session.elements.keys()) + list(session.connections.keys()):
        results[eid] = {"violations": [], "suggestions": []}

    for it in issues:
        tid = it.target_id
        payload = {
            "rule_id": it["rule_id"],
            "level": it["level"],
            "message": it["message"],
        }
        bucket = "violations" if it["level"] == "error" else "suggestions"
        if tid and tid in results:
            results[tid][bucket].append(payload)
        else:
            # 图级提示（target_id 为空，如 H05 命名混用、H13 多实体无联系）：
            # 只由**第一个元素**承载。
            #
            # 为什么不能分发给所有元素（旧实现，200 元素图实测复制 600 条）：
            #   前端 IssuePanel 把 results 里每个 id 的提示摊平显示，
            #   分发全部会让面板出现 N 条完全相同的提示，学生被刷屏。
            # 为什么不能发给不存在的"图级伪 id"：
            #   协议上 batch_result.results 的 key 必须是图内元素 id，
            #   前端 applyResult 按 id 匹配本地模型，未知 id 被静默丢弃。
            # 承载元素只影响面板归属（提示文字本身说明是图级问题），
            # 不影响画布其余元素的正确校验。
            if results:
                first = next(iter(results))
                results[first][bucket].append(payload)

    return {"action": "batch_result", "results": results}


# ----------------------------------------------------------------------
# 引擎门面
# ----------------------------------------------------------------------

class Engine:
    """规则引擎门面：持有字典树与会话状态，供 WebSocket 层调用。"""

    def __init__(self) -> None:
        self.trie = TRIE
        self.sessions: Dict[str, Session] = {}
        self.last_timing: List[float] = []
        # 会话键 → 学生标识（消息首次带 user_id 时记住，后续沿用）
        self._user_of_session: Dict[str, str] = {}
        # 是否自动投递 LLM 诊断任务（默认开；跑纯规则基准时可关）
        self.auto_diagnose: bool = True
        # 薄弱点台账引用（可注入：测试用隔离台账，生产用全局 TRACKER）。
        # 此前硬绑定 ws_mod.TRACKER，完整 handle 路径无法用隔离台账做端到端验证
        # （课堂演练脚本实测暴露）。
        self.tracker = ws_mod.TRACKER

    def session(self, key: str) -> Session:
        s = self.sessions.get(key)
        if s is None:
            s = Session()
            self.sessions[key] = s
        return s

    def drop_session(self, key: str) -> None:
        self.sessions.pop(key, None)
        self._user_of_session.pop(key, None)

    def bind_user(self, session_key: str, user_id: str) -> None:
        """
        把会话绑定到学生标识（连接建立时调用，如 ?user_id=2023001）。
        之后该连接的所有校验都记到该学生名下。
        """
        if user_id and user_id.strip():
            self._user_of_session[session_key] = user_id.strip()

    def _maybe_enqueue_diagnosis(self, user_id: str) -> None:
        """
        若统计信号足够强，投递一个诊断任务（不等待生成）。

        触发判断在 diagnose_queue.should_trigger 里，含冷却与阈值，
        避免每次绘图操作都去调 LLM。
        该方法是"尽力而为"：任何异常都不影响实时校验主流程。
        """
        try:
            from diagnose_queue import QUEUE
            if QUEUE is None:
                return
            if QUEUE.should_trigger(user_id):
                QUEUE.enqueue(user_id)
        except Exception:
            # 异步增强层的任何问题都不应影响实时校验
            pass

    def handle(self, session_key: str, msg: dict) -> dict:
        """
        处理一条消息，返回回包 dict。
        时间统计写入 last_timing（微秒），供基准测试取用。
        """
        t0 = time.perf_counter()
        try:
            # 用户标识解析（研究内容三要求"含用户标识"）：
            #   1) 消息里带 user_id / student_id  → 用它（同一学生可跨连接/跨次绘图聚合）
            #   2) 否则退化为 session_key（一个连接 ≈ 一次绘图会话）
            # 前端当前不发 user_id，故需服务端在建立连接时用 ?user_id= 指定，
            # 或在首条消息里带上；两种都支持。
            user_id = self._resolve_user_id(session_key, msg)
            action = msg.get("action")
            if action == "check":
                reply = self._handle_check(session_key, msg)
            elif action == "batch_check":
                reply = check_batch(self.session(session_key), msg)
            else:
                reply = {
                    "action": "error",
                    "element_id": msg.get("element_id"),
                    "message": f"不支持的消息：action={action}",
                }
            # 薄弱点记账：校验完成后追加，O(1) 写入，不做统计，不拖慢实时反馈。
            # 同时传 session_key —— 图缓存挂在会话键下，而 user_id 可能是
            # 学生标识，二者不同名；只传 user_id 会查不到图规模，
            # 导致需求书要求的「设计上下文」永远为空。
            self._track(user_id, reply, session_key)
            # LLM 异步增强（需求书："规则引擎优先、LLM 异步增强"）：
            # 只在统计信号足够强时才投递任务，且投递本身是 O(1)、不等结果。
            # 注意：should_trigger 会做一次轻量统计，故设开关可关闭，
            # 避免影响纯规则基准测量。
            if self.auto_diagnose:
                self._maybe_enqueue_diagnosis(user_id)
        except Exception as ex:
            reply = {
                "action": "error",
                "element_id": msg.get("element_id"),
                "message": f"后端处理异常: {ex}",
            }
        dt_us = (time.perf_counter() - t0) * 1_000_000
        self.last_timing.append(dt_us)
        # 上限保护：一节课数万条消息会让该列表无限增长（内存缓慢泄漏）。
        # 与 server 端 STATS.timings_us 一致，只留最近 5000 条。
        if len(self.last_timing) > 5000:
            del self.last_timing[: len(self.last_timing) // 2]
        return reply

    def _resolve_user_id(self, session_key: str, msg: dict) -> str:
        """
        确定这次校验归属哪个学生。

        - 消息里显式带 user_id/student_id → 优先
        - 否则用会话键（并记住，使同一连接后续消息归属一致）
        """
        for k in ("user_id", "student_id"):
            v = msg.get(k)
            if isinstance(v, str) and v.strip():
                uid = v.strip()
                self._user_of_session[session_key] = uid
                return uid
        return self._user_of_session.get(session_key, session_key)

    def _track(self, user_id: str, reply: dict,
               session_key: Optional[str] = None) -> None:
        """
        把本次校验结果记入薄弱点台账。

        - 用户标识：已由 _resolve_user_id 解析（优先消息里的 user_id，
          否则退化为会话键）。
        - 设计上下文：图规模必须从**会话键**取图缓存，不能从 user_id 取——
          user_id 可能是学生标识（如 ?user_id=2023001），
          而 self.sessions 的键始终是会话键，两者不同名。
          早期实现只用 user_id 查，导致显式指定学生时上下文恒为空。
        """
        if not isinstance(reply, dict):
            return
        action = reply.get("action")
        sess = self.sessions.get(session_key) if session_key else None
        if sess is None:
            ctx: Dict[str, int] = {}
        else:
            ctx = {
                "elements": len(sess.elements),
                "connections": len(sess.connections),
            }
        if action == "result":
            eid = str(reply.get("element_id") or "")
            self.tracker.record_issues(
                user_id, reply.get("violations", []), eid, ctx)
            self.tracker.record_issues(
                user_id, reply.get("suggestions", []), eid, ctx)
        elif action == "batch_result":
            for eid, body in (reply.get("results") or {}).items():
                self.tracker.record_issues(
                    user_id, body.get("violations", []), eid, ctx)
                self.tracker.record_issues(
                    user_id, body.get("suggestions", []), eid, ctx)

    def _handle_check(self, session_key: str, msg: dict) -> dict:
        # 输入校验：attributes 必须是数组（协议要求）
        el = msg.get("element")
        if isinstance(el, dict) and "attributes" in el and not isinstance(el["attributes"], list):
            return {
                "action": "error",
                "element_id": el.get("id"),
                "message": "消息格式错误: 'attributes' 字段应为数组，"
                           f"收到了 {type(el['attributes']).__name__}",
            }
        event = msg.get("event")
        valid_events = {
            EVENT_ELEMENT_ADDED, EVENT_ELEMENT_MODIFIED, EVENT_ELEMENT_DELETED,
            EVENT_CONNECTION_ADDED, EVENT_CONNECTION_MODIFIED,
        }
        if event not in valid_events:
            return {
                "action": "error",
                "element_id": el.get("id") if isinstance(el, dict) else None,
                "message": f"不支持的事件：{event}",
            }
        return check_single(self.session(session_key), msg)


# 全局引擎实例
ENGINE = Engine()


def trie_summary() -> str:
    return TRIE.describe()
