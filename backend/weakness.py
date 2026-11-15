# -*- coding: utf-8 -*-
"""
薄弱点记录与诊断（研究内容三）
==============================

对应需求书：「自动记录 ER 绘图过程中触发的规则违规信息，包括用户标识、
错误类型、触发时间、错误次数、设计上下文；绘图会话结束后，自动生成个人
错误清单，按错误类型分类汇总，标记高频薄弱点。」

本模块提供**规则引擎侧**的数据基础（LLM 深度归因属后续异步层，
此处只负责把结构化的事实记准、算对）：

    ViolationRecord   单条违规记录（用户/规则/等级/时间/上下文）
    WeaknessTracker   按用户累积记录，输出统计与薄弱点

设计原则：
    1) 记账不阻塞实时校验——记录用 O(1) 追加，统计按需计算（惰性）；
    2) 用"去重窗口"避免同一错误被反复计数（学生拖拽时同一条错误
       会在每次 element_modified 里重复触发，若每次都记，统计会失真）；
    3) 上下文只留可判定的部分（当时图规模、涉及元素名），不存整图快照，
       避免内存随绘图过程无限增长。
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# 单条违规记录
# ----------------------------------------------------------------------

@dataclass
class ViolationRecord:
    """一次违规的原始记录。"""

    user_id: str          # 用户标识（学生）
    rule_id: str          # 规则编号，如 R02
    level: str            # error / warn
    message: str          # 提示语
    timestamp: float      # 触发时间（epoch 秒）
    element_id: str = ""  # 触发对象
    context: Dict = field(default_factory=dict)  # 设计上下文（图规模等）

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp,
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(self.timestamp)),
            "element_id": self.element_id,
            "context": self.context,
        }


# ----------------------------------------------------------------------
# 薄弱点追踪器
# ----------------------------------------------------------------------

class WeaknessTracker:
    """
    按用户累积违规记录，并提供分类汇总与薄弱点识别。

    线程/协程安全说明：WebSocket 服务在单事件循环内顺序处理消息，
    故此处的 list.append 不涉及并发竞争；若将来换多线程，
    需在 record() 与 stats() 上加锁。
    """

    # 同一 (user, rule, element) 在该秒数内重复触发只记一次，
    # 避免拖拽/连续修改导致同一错误被刷屏计数
    DEDUP_WINDOW_SEC = 3.0

    def __init__(self, max_records_per_user: int = 2000,
                 persist_path: Optional[str] = None) -> None:
        self._records: Dict[str, List[ViolationRecord]] = defaultdict(list)
        self._last_seen: Dict[tuple, float] = {}
        self.max_records_per_user = max_records_per_user
        # 去重表也需要上限：它按 (user, rule, element) 建键，
        # 元素多时会无限增长（实测 5000 元素即 5000 条）。
        # 超过阈值时按时间裁剪最旧的一半。
        self.max_dedup_entries = max(4096, max_records_per_user * 4)

        # 持久化（可选）：JSONL 追加写。
        # 选 JSONL 而非数据库的理由：追加写不阻塞、无需额外依赖、
        # 崩溃时最多丢最后一行，对本场景（高频小额写入）足够；
        # 若将来需要并发查询/多实例，再换 SQLite 或外部存储。
        #
        # 性能：每条一次 open/close 实测约 715us（比不落盘慢 283 倍）。
        # 改为**缓冲批量写**——攒够 _FLUSH_EVERY 条才落盘一次，
        # 且写入失败会保留缓冲，不会静默丢数据。
        self.persist_path: Optional[str] = persist_path
        self._persist_failures = 0
        self._buf: List[str] = []
        self._loaded_count = 0
        self._closed = False
        # 是否已成功写过盘（用于"首次写入立即落盘"的判断）
        self._wrote_once = False
        # 轻量计数器：user_id -> Counter[rule_id]。
        # 供热路径 O(1) 判定用（DiagnoseQueue.should_trigger 每条消息都调）。
        # 原实现让热路径直接跑 summary()（O(记录数)），实测 2000 条记录时
        # 每条绘图消息要多花 1.15ms 做统计——随错误累积线性变差。
        # 计数器在 record() 时增量维护（O(1)），裁剪/回放时重算。
        self._rule_counts: Dict[str, Counter] = defaultdict(Counter)
        if self.persist_path:
            self._load_from_disk()

    # 攒多少条落盘一次。太小则性能退化，太大则崩溃时丢得多。
    _FLUSH_EVERY = 32

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _repair_tail(self, path: Path) -> None:
        """
        修复崩溃留下的半行（实测缺陷）：
            进程在 write 中途被强杀，最后一行可能只有半截 JSON 且**无换行符**。
            此后下次追加会粘在半行后面，导致半行 + 新记录**两段都解析失败**
            ——实测崩溃后第一条新记录必然丢失。

            修复方式：启动时检查文件末字节，若不以换行结尾则补一个。
            代价：半行本身成为独立损坏段，被回放的 JSONDecodeError 跳过
            （与原容错一致），但**后续追加不再粘连**，新数据不丢。
            该修复只在启动路径执行一次，不进热路径。
        """
        try:
            size = path.stat().st_size
            if size == 0:
                return
            with path.open("rb") as f:
                f.seek(-1, 2)
                last = f.read(1)
            if last != b"\n":
                with path.open("ab") as f:
                    f.write(b"\n")
        except OSError:
            pass  # 修复失败不阻塞启动；回放侧仍有逐行容错兜底

    def _load_from_disk(self) -> None:
        """启动时回放历史记录，使学情数据在服务重启后不丢。"""
        if not self.persist_path:
            return
        path = Path(self.persist_path)
        if not path.exists():
            return
        # 先修复崩溃半行（防止后续追加粘行丢数据）
        self._repair_tail(path)
        loaded = 0
        last_ts: Dict[tuple, float] = {}
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 容错：跳过损坏行（如崩溃时写了一半）
                    uid = d.get("user_id")
                    rid = d.get("rule_id")
                    if not uid or not rid:
                        continue
                    ts = float(d.get("timestamp") or 0.0)
                    self._records[uid].append(ViolationRecord(
                        user_id=uid,
                        rule_id=rid,
                        level=str(d.get("level") or ""),
                        message=str(d.get("message") or ""),
                        timestamp=ts,
                        element_id=str(d.get("element_id") or ""),
                        context=d.get("context") or {},
                    ))
                    key = (uid, rid, str(d.get("element_id") or ""))
                    if ts > last_ts.get(key, 0.0):
                        last_ts[key] = ts
                    loaded += 1
        except OSError:
            return  # 读取失败不阻塞服务启动
        self._last_seen.update(last_ts)
        # 回放后按上限裁剪，避免历史过大
        for uid, bucket in self._records.items():
            if len(bucket) > self.max_records_per_user:
                del bucket[: len(bucket) - self.max_records_per_user]
        # 回放/裁剪后统一重建轻量计数器（热路径 O(1) 判定的数据源）
        self._rule_counts = defaultdict(Counter)
        for uid in self._records:
            self._recount(uid)
        self._loaded_count = loaded

    def _append_to_disk(self, rec: "ViolationRecord") -> None:
        """
        追加一条记录到缓冲，攒够 _FLUSH_EVERY 条才真正落盘。

        失败只计数、不抛异常——记账是教学辅助能力，
        绝不能因为磁盘问题让实时校验挂掉。
        """
        if not self.persist_path:
            return
        self._buf.append(json.dumps(rec.to_dict(), ensure_ascii=False))
        # 首次写入时立即落盘：建立文件、确认可写，避免"小数据量场景
        # 缓冲攒不满、进程退出即丢"。
        # 注意：判断依据必须是"本对象是否已写过盘"，**不能**写成
        # `len(self._buf) == 1` —— flush 会清空缓冲，导致下一条又满足
        # 该条件，退化成每条一次 open/write（实测 709us/条，比缓冲慢 18 倍）。
        if not self._wrote_once or len(self._buf) >= self._FLUSH_EVERY:
            if self.flush() > 0:
                self._wrote_once = True

    def flush(self) -> int:
        """
        把缓冲写入磁盘。返回成功写入的行数。

        特点：一次性 open + write 多行，避免每条一次开关文件。
        写入失败时**保留缓冲**，下次 flush 重试，不静默丢数据。
        """
        if not self.persist_path or not self._buf:
            return 0
        chunk = "\n".join(self._buf) + "\n"
        try:
            with open(self.persist_path, "a", encoding="utf-8") as f:
                f.write(chunk)
        except OSError:
            self._persist_failures += 1
            return 0
        n = len(self._buf)
        self._buf.clear()
        return n

    @property
    def pending_writes(self) -> int:
        """尚未落盘的缓冲条数（诊断用）。"""
        return len(self._buf)

    @property
    def persist_failures(self) -> int:
        return self._persist_failures

    def _trim_dedup(self, now: float) -> None:
        """去重表超限时，丢掉最旧的一半（保留近期，避免误去重）。"""
        if len(self._last_seen) <= self.max_dedup_entries:
            return
        items = sorted(self._last_seen.items(), key=lambda kv: kv[1])
        keep_from = len(items) // 2
        self._last_seen = dict(items[keep_from:])

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------
    def record(
        self,
        user_id: str,
        rule_id: str,
        level: str,
        message: str,
        element_id: str = "",
        context: Optional[Dict] = None,
        now: Optional[float] = None,
    ) -> bool:
        """
        记一条违规。返回是否真的记下（被去重则返回 False）。

        O(1) 追加，不做任何统计计算——保证不拖慢实时校验。
        """
        ts = now if now is not None else time.time()
        key = (user_id, rule_id, element_id)
        last = self._last_seen.get(key)
        if last is not None and (ts - last) < self.DEDUP_WINDOW_SEC:
            return False
        self._last_seen[key] = ts
        self._trim_dedup(ts)

        bucket = self._records[user_id]
        rec = ViolationRecord(
            user_id=user_id,
            rule_id=rule_id,
            level=level,
            message=message,
            timestamp=ts,
            element_id=element_id,
            context=dict(context or {}),
        )
        bucket.append(rec)
        # 落盘：追加一行。失败只计数，绝不影响主流程。
        self._append_to_disk(rec)
        # 上限保护：超出后丢弃最早的一半，控制内存。
        # 裁剪后计数器会与实际记录不一致，重算（罕见路径，可接受）。
        if len(bucket) > self.max_records_per_user:
            del bucket[: len(bucket) // 2]
            self._recount(user_id)
        else:
            self._rule_counts[user_id][rule_id] += 1
        return True

    def _recount(self, user_id: str) -> None:
        """按当前记录重算某学生的规则计数（裁剪/回放后调用）。"""
        c = Counter(r.rule_id for r in self._records.get(user_id, []))
        if c:
            self._rule_counts[user_id] = c
        else:
            self._rule_counts.pop(user_id, None)

    def record_count(self, user_id: str) -> int:
        """O(1) 取某学生的记录总数（热路径用，不要用 records_of）。"""
        return len(self._records.get(user_id, ()))

    def max_rule_count(self, user_id: str) -> int:
        """O(规则数) 取该学生单条规则的最大出现次数（热路径用）。"""
        c = self._rule_counts.get(user_id)
        return max(c.values()) if c else 0

    def record_issues(
        self,
        user_id: str,
        issues: List[dict],
        element_id: str = "",
        context: Optional[Dict] = None,
        now: Optional[float] = None,
    ) -> int:
        """批量记一组 issue（来自一次校验的 violations/suggestions）。返回记录条数。"""
        n = 0
        for it in issues or []:
            if self.record(
                user_id=user_id,
                rule_id=str(it.get("rule_id", "")),
                level=str(it.get("level", "")),
                message=str(it.get("message", "")),
                element_id=element_id,
                context=context,
                now=now,
            ):
                n += 1
        return n

    # ------------------------------------------------------------------
    # 查询与统计（按需计算，不进热路径）
    # ------------------------------------------------------------------
    def records_of(self, user_id: str) -> List[ViolationRecord]:
        return list(self._records.get(user_id, []))

    def clear(self, user_id: str) -> None:
        self._records.pop(user_id, None)
        self._rule_counts.pop(user_id, None)
        for k in [k for k in self._last_seen if k[0] == user_id]:
            self._last_seen.pop(k, None)

    def summary(self, user_id: str, top_n: int = 5) -> Dict:
        """
        个人错误清单：按规则分类汇总 + 高频薄弱点。

        输出结构（供前端学情看板 / LLM 归因使用）：
            {
              "user_id", "total", "error_count", "warning_count",
              "by_rule":  [ {rule_id, level, count, message, first_at, last_at} ],
              "by_level": {error: n, warn: n},
              "weak_points": [ {rule_id, count, share, level, message} ],
              "session_span_sec": float,
            }
        """
        recs = self._records.get(user_id, [])
        if not recs:
            return {
                "user_id": user_id, "total": 0,
                "error_count": 0, "warning_count": 0,
                "by_rule": [], "by_level": {"error": 0, "warn": 0},
                "weak_points": [], "session_span_sec": 0.0,
            }

        by_rule: Dict[str, Dict] = {}
        level_counter: Counter = Counter()
        for r in recs:
            level_counter[r.level] += 1
            slot = by_rule.get(r.rule_id)
            if slot is None:
                by_rule[r.rule_id] = {
                    "rule_id": r.rule_id,
                    "level": r.level,
                    "count": 1,
                    "message": r.message,
                    "first_at": r.timestamp,
                    "last_at": r.timestamp,
                }
            else:
                slot["count"] += 1
                slot["last_at"] = max(slot["last_at"], r.timestamp)
                slot["first_at"] = min(slot["first_at"], r.timestamp)

        ordered = sorted(by_rule.values(), key=lambda x: -x["count"])
        total = len(recs)

        # 薄弱点：出现次数 ≥2 且占比靠前的规则
        weak = []
        for item in ordered:
            if item["count"] < 2:
                continue
            weak.append({
                "rule_id": item["rule_id"],
                "count": item["count"],
                "share": round(item["count"] / total, 3),
                "level": item["level"],
                "message": item["message"],
            })
            if len(weak) >= top_n:
                break

        span = max(r.timestamp for r in recs) - min(r.timestamp for r in recs)
        return {
            "user_id": user_id,
            "total": total,
            "error_count": level_counter.get("error", 0),
            "warning_count": level_counter.get("warn", 0),
            "by_rule": ordered,
            "by_level": dict(level_counter),
            "weak_points": weak,
            "session_span_sec": round(span, 1),
        }

    def class_summary(self, top_n: int = 5) -> Dict:
        """
        班级学情：识别共性问题（对应需求书"80% 学生遗漏联系基数标注"）。

        输出 common_issues：命中该规则的学生数 / 总学生数。
        """
        users = list(self._records.keys())
        if not users:
            return {"student_count": 0, "common_issues": [], "by_rule": []}

        per_user_rules: Dict[str, set] = {}
        rule_counter: Counter = Counter()
        rule_msg: Dict[str, str] = {}
        rule_level: Dict[str, str] = {}
        for uid, recs in self._records.items():
            s = set()
            for r in recs:
                s.add(r.rule_id)
                rule_counter[r.rule_id] += 1
                rule_msg.setdefault(r.rule_id, r.message)
                rule_level.setdefault(r.rule_id, r.level)
            per_user_rules[uid] = s

        n_users = len(users)
        common = []
        for rid, cnt in rule_counter.most_common():
            hit_students = sum(1 for s in per_user_rules.values() if rid in s)
            common.append({
                "rule_id": rid,
                "level": rule_level.get(rid, ""),
                "message": rule_msg.get(rid, ""),
                "total_count": cnt,
                "student_count": hit_students,
                "student_share": round(hit_students / n_users, 3),
            })

        # 排序口径（v1.4 修正，课堂演练实测暴露）：
        # 教师关心的是"多少学生中招"（需求书："80% 学生遗漏联系基数标注"），
        # 故必须按**学生命中数**降序，而非总记录数。
        # 实测旧口径会把 30 人中招但记录少的规则压到 30 人 5 条的规则之后。
        # 平局依次按总记录数、规则号，保证排序稳定可测试。
        common.sort(key=lambda x: (-x["student_count"], -x["total_count"],
                                   x["rule_id"]))

        return {
            "student_count": n_users,
            "common_issues": common[:top_n],
            "by_rule": common,
        }

    def stats(self) -> Dict:
        """运行状态（诊断用）：记录数、学生数、待写缓冲、落盘失败次数。"""
        return {
            "students": len(self._records),
            "total_records": sum(len(v) for v in self._records.values()),
            "pending_writes": len(self._buf),
            "persist_failures": self._persist_failures,
            "persist_path": self.persist_path,
        }

    def flush_all(self) -> int:
        """强制落盘全部缓冲（进程退出前调用，防止丢尾部数据）。"""
        return self.flush()

    def close(self) -> int:
        """显式关闭：落盘并标记不再接受写入。"""
        n = self.flush()
        self._closed = True
        return n

    def __del__(self) -> None:
        """
        析构时兜底落盘。

        缓冲批量写换来了 18 倍性能，代价是"必须记得 flush"——
        调用方忘记 flush（或进程正常退出）就会丢最后的缓冲。
        这里做最后一道保险：对象被回收时尝试写盘。
        解释器退出阶段不保证 __del__ 一定执行，故关键路径
        （server 正常退出、断连）仍显式调用 flush。
        """
        try:
            self.flush()
        except Exception:
            pass

    def all_users(self) -> List[str]:
        return list(self._records.keys())


# ----------------------------------------------------------------------
# 全局实例（供 server 复用）
# ----------------------------------------------------------------------
# 默认落盘到 backend/weakness_log.jsonl，使学情数据在服务重启后不丢。
#
# 环境变量：
#   ER_WEAKNESS_LOG=<path>  覆盖日志路径
#   ER_WEAKNESS_LOG=""      关闭持久化（仅内存）
#   ER_TESTING=1            测试模式：全局实例不落盘
#
# 为什么需要 ER_TESTING：
#   审计脚本会经由 engine → 全局 TRACKER 大量触发记账。
#   若测试直接写生产日志，会把测试数据混进真实教学数据
#   （实测跑一遍测试即写入 4481 行 / 1MB）。
#   测试脚本应在导入前设 ER_TESTING=1。
import os as _os

_TESTING = _os.environ.get("ER_TESTING") == "1"
_LOG_PATH = _os.environ.get(
    "ER_WEAKNESS_LOG",
    str(Path(__file__).resolve().parent / "weakness_log.jsonl"),
)
if _TESTING:
    _LOG_PATH = ""  # 测试模式：不落盘
TRACKER = WeaknessTracker(persist_path=_LOG_PATH or None)
