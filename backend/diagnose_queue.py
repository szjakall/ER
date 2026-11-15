# -*- coding: utf-8 -*-
"""
LLM 异步调度层（"规则引擎优先、LLM 异步增强"的落地）
====================================================

对应需求书：
    「采用'规则引擎优先、LLM 异步增强'的混合策略：规则引擎完成毫秒级
      实时校验，LLM 在后台进行语义级深度分析，结果以非侵入式提示呈现。」
    「设计异步调用队列：实时校验完全由规则引擎处理，LLM 调用放入后台队列，
      结果通过 WebSocket 推送到前端，确保绘图交互的实时性不受影响。」

本模块解决的核心问题：
    **绝不能让 LLM 的秒级延迟污染规则引擎的毫秒级反馈。**

做法：
    - 触发条件交给规则引擎的**统计信号**（如某类错误重复 N 次），
      而不是每次操作都调 LLM；
    - 命中后只往队列里 **丢一个任务**（O(1)，不等待）；
    - 后台 worker 串行消费，生成诊断后通过回调推送结果。

架构：
    DiagnoseQueue
        ├── enqueue(user_id)        规则引擎侧调用，立即返回
        ├── worker 循环             后台线程/协程，逐个生成诊断
        └── on_result(user_id, d)   回调 → WebSocket 推送

    队列满时**丢弃最旧任务**（合并同用户），保证不堆积、不阻塞。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

from llm import Diagnosis, Diagnoser
from weakness import TRACKER, WeaknessTracker


# 触发策略：满足任一条件才值得调用一次 LLM
TRIGGER_MIN_RECORDS = 5      # 累计违规至少 5 条
TRIGGER_REPEAT_COUNT = 3     # 或某条规则重复出现 3 次
TRIGGER_COOLDOWN_SEC = 60.0  # 同一学生两次诊断的最小间隔（防抖）


class DiagnoseQueue:
    """
    异步诊断队列。

    线程安全：enqueue 与 worker 在不同线程，用锁保护共享状态。
    """

    def __init__(
        self,
        diagnoser: Optional[Diagnoser] = None,
        tracker: Optional[WeaknessTracker] = None,
        max_pending: int = 64,
        max_cached_results: int = 256,
        on_result: Optional[Callable[[str, Diagnosis], None]] = None,
    ) -> None:
        self.diagnoser = diagnoser or Diagnoser(tracker=tracker)
        self.tracker = tracker or TRACKER
        self.max_pending = max_pending
        self.max_cached_results = max_cached_results
        self.on_result = on_result

        # user_id -> 入队时间（OrderedDict 便于丢弃最旧）
        self._pending: "OrderedDict[str, float]" = OrderedDict()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        # 同一学生的冷却时间
        self._last_done: Dict[str, float] = {}
        # 已生成的最近结果（供 HTTP 查询 / 断线补发）
        self._results: Dict[str, Diagnosis] = {}

        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

        # 统计（供诊断）
        self.enqueued = 0
        self.dropped = 0
        self.generated = 0
        self.failed = 0

    # ------------------------------------------------------------------
    # 生产者侧（规则引擎调用，必须极快）
    # ------------------------------------------------------------------
    def should_trigger(self, user_id: str) -> bool:
        """
        判断是否值得为该学生触发一次 LLM 诊断。

        只在"有足够多的错误信号"时才触发，避免每次操作都调模型。

        **本方法在引擎热路径上每条消息调用一次，必须全程 O(1)**：
            - 冷却检查：O(1) 字典查询
            - 阈值检查：record_count / max_rule_count 均为 O(1)/O(规则数)
              （WeaknessTracker 维护轻量计数器，见其 _rule_counts 说明）

            不在此处调用 summary()——那是 O(记录数)，实测 2000 条记录时
            每条绘图消息要多花 1.15ms，且随错误累积线性变差。
        """
        # O(1) 快速路径 1：冷却期内直接拒绝
        last = self._last_done.get(user_id)
        now = time.time()
        if last is not None and (now - last) < TRIGGER_COOLDOWN_SEC:
            return False

        # O(1) 快速路径 2：总记录数不足
        total = self.tracker.record_count(user_id)
        if total < TRIGGER_MIN_RECORDS:
            return False

        # O(规则数)：需要存在重复出现的规则（概念性问题才值得归因）
        if self.tracker.max_rule_count(user_id) < TRIGGER_REPEAT_COUNT:
            return False

        # 双重冷却检查（防竞态：统计期间任务可能刚完成）
        last = self._last_done.get(user_id)
        if last is not None and (time.time() - last) < TRIGGER_COOLDOWN_SEC:
            return False
        return True

    def enqueue(self, user_id: str) -> bool:
        """
        投递一个诊断任务，**立即返回**（不等待生成）。

        返回是否真的入队（被冷却/去重/队满丢弃时返回 False）。
        """
        if not user_id:
            return False
        with self._cv:
            if user_id in self._pending:
                # 已在队列中，合并（不重复排队）
                return False
            if len(self._pending) >= self.max_pending:
                # 队列满：丢弃最旧的（保证不堆积、不阻塞）
                self._pending.popitem(last=False)
                self.dropped += 1
            self._pending[user_id] = time.time()
            self.enqueued += 1
            self._cv.notify()
        return True

    # ------------------------------------------------------------------
    # 消费者侧（后台 worker）
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="diagnose-worker",
                                        daemon=True)
        self._worker.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=timeout)
            self._worker = None

    def _run(self) -> None:
        while not self._stop.is_set():
            item = None
            with self._cv:
                if not self._pending:
                    # 等待新任务或停止信号（带超时，便于定期检查 stop）
                    self._cv.wait(timeout=0.5)
                    continue
                user_id, _ = self._pending.popitem(last=False)
                item = user_id

            if item is None:
                continue
            self._process(item)

        # 退出前把剩余任务处理完（尽力而为）
        while True:
            with self._cv:
                if not self._pending:
                    break
                user_id, _ = self._pending.popitem(last=False)
            self._process(user_id)

    def _process(self, user_id: str) -> None:
        try:
            d = self.diagnoser.diagnose_user(user_id)
            with self._lock:
                self._results[user_id] = d
                # 缓存上限：每学生一份报告（几 KB），全班 2000 人 ≈ 数 MB。
                # 超限时丢最旧的——缓存仅供"断线补发/查询最近结果"，
                # 学情真相在 TRACKER，这里丢的只是缓存副本。
                if len(self._results) > self.max_cached_results:
                    for k in list(self._results)[: len(self._results) // 2]:
                        self._results.pop(k, None)
                self._last_done[user_id] = time.time()
                self.generated += 1
            if self.on_result is not None:
                try:
                    self.on_result(user_id, d)
                except Exception:
                    # 推送失败不影响队列继续工作
                    pass
        except Exception:
            with self._lock:
                self.failed += 1

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_result(self, user_id: str) -> Optional[Diagnosis]:
        with self._lock:
            return self._results.get(user_id)

    def stats(self) -> Dict:
        with self._lock:
            return {
                "pending": len(self._pending),
                "enqueued": self.enqueued,
                "generated": self.generated,
                "dropped": self.dropped,
                "failed": self.failed,
                "cached_results": len(self._results),
                "worker_alive": bool(self._worker and self._worker.is_alive()),
            }

    def reset(self) -> None:
        """清空队列与缓存（测试用）。"""
        with self._lock:
            self._pending.clear()
            self._results.clear()
            self._last_done.clear()
            self.enqueued = self.dropped = self.generated = self.failed = 0


# ----------------------------------------------------------------------
# 全局队列（server 启动时 start()，engine 侧懒加载引用）
# ----------------------------------------------------------------------
# 注意：engine.py 在 _maybe_enqueue_diagnosis 里用 `from diagnose_queue import QUEUE`
# 懒加载，避免循环导入（engine ← diagnose_queue ← llm ← weakness）。
QUEUE: Optional[DiagnoseQueue] = None


def init_queue(on_result=None) -> DiagnoseQueue:
    """由 server 调用：创建并启动全局队列。"""
    global QUEUE
    QUEUE = DiagnoseQueue(on_result=on_result)
    QUEUE.start()
    return QUEUE
