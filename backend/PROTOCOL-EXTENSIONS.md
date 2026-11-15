# 协议扩展说明（backend 侧新增）

> **前提**：`INTERFACE.md` 是 A/B/C 三人的**基础契约**，其中原文明确写着
> 「此文件中定义的任何消息格式变更，必须三人同时确认」。
> 因此本文件**不修改** `INTERFACE.md`，只记录 backend 在不破坏原契约的前提下
> **新增**的内容，供三方评审是否需要并入正式契约。

---

## 一、新增的 WebSocket 消息：`action="diagnosis"`

### 为什么需要

需求书（研究内容三）要求「LLM 在后台进行语义级深度分析，结果以**非侵入式**提示呈现」。
规则校验结果（`result` / `batch_result`）走的是**同步请求-响应**语义，
而诊断是**异步生成、主动推送**的，两者生命周期完全不同：

- `result` 必须与请求一一对应（前端靠 `element_id` 匹配 pending 槽位）
- `diagnosis` 是服务端主动推送，**没有对应的前端请求**

若强行混入 `result`，会破坏前端「一次请求一次响应」的匹配逻辑。

### 消息格式

```jsonc
// 后端 → 前端（服务端主动推送，无需前端请求）
{
  "action": "diagnosis",          // 新增的 action 值
  "user_id": "2023001",           // 诊断归属的学生
  "data": {                       // 诊断报告全文
    "user_id": "2023001",
    "source": "heuristic",        // "heuristic" | "llm"，标明来源便于教师判断可信度
    "summary": "…自然语言诊断正文…",
    "weak_points": [
      { "rule_id": "R02", "count": 4, "share": 0.8, "level": "error",
        "topic": "主键完整性", "why": "…", "advice": "…" }
    ],
    "suggestions": ["复习「主键/候选键」一节…"],
    "error_profile": { "total": 5, "error_count": 5, "warning_count": 0,
                       "by_rule": [ … ], "by_level": { "error": 5 } },
    "generated_at": 1763000000.0,
    "time_str": "2026-11-14 01:40:00",
    "meta": { "elapsed_ms": 0.09, "provider": "heuristic" }
  }
}
```

### 对前端的影响（重要）

- **必须忽略未知 action**：旧前端收到 `action="diagnosis"` 时，
  `ws.ts` 的 `onMessage` 会走到末尾的 `return`（不匹配任何已知 action），
  **不会报错、不会影响现有功能**。已核对 `frontend/src/protocol/ws.ts` 第 125–154 行确认。
- **前端接入是可选的**：不接也能正常绘图；接入后可在侧栏展示学习建议。
- **不宜当作阻塞式提示**：需求书要求"非侵入式"，建议以侧栏/抽屉呈现，
  不要弹窗打断绘图。

---

## 二、新增的 HTTP 接口

这些是**新增通路**，不影响原 WebSocket 契约：

| 接口 | 用途 |
|---|---|
| `GET /weakness/{user_id}` | 个人错误清单 |
| `GET /weakness` | 班级学情 |
| `DELETE /weakness/{user_id}` | 清除某学生记录 |
| `GET /diagnosis/{user_id}` | 个人学情诊断报告 |
| `GET /diagnosis` | 班级学情摘要 + 教学建议 |
| `GET /diagnosis/queue/stats` | 异步诊断队列状态（返回 `running` 及 pending/generated/dropped/failed） |
| `GET /stats` | 服务运行统计 |
| `GET /` | 健康检查 |

---

## 三、请求侧新增的可选字段

前端**可以**在消息里带上以下字段（都是可选的，不带也能工作）：

| 字段 | 位置 | 作用 |
|---|---|---|
| `user_id` / `student_id` | 消息体 或 WS 连接查询参数 | 标明学生身份，使薄弱点记录能归属到人 |
| `requirement_text` | `batch_check` 消息体 | 需求文本，用于 H18–H21 需求对齐规则 |

> `user_id` 建议用连接参数传入：`ws://localhost:8000/ws?user_id=2023001`。
> 不带时服务端退化为用连接标识记账（可记录，但**教师无法按学生查询**）。

---

## 四、未改动的内容（确认）

- `INTERFACE.md` 原文件**未修改**
- 原有 5 种 `event`、3 种回包 `action`（`result` / `batch_result` / `error`）
  的格式与语义**完全未变**
- `frontend/` 目录**零改动**

---

## 五、对 INTERFACE.md 编号规范的**有意偏离**（需三方知会）

`INTERFACE.md` 第 188–192 行的编号规范：

> `R` = 刚性规则（必须修复），红色；`H` = 启发规则（建议优化），橙色

**自 v1.3 起有三条例外**（独立教学审查的结论，教学正确性优先于前缀字面义）：

| 规则 | 前缀 | 实际 level | 颜色 | 理由 |
|---|---|---|---|---|
| R07 | R | `warn` | 🟠 橙 | 复合主键是合法建模（`选课(*学号,*课号)`），判红会教坏学生 |
| R13 | R | `warn` | 🟠 橙 | 实体间直接连线可能是 ISA 继承（教材合法画法） |
| R16 | R | `warn` | 🟠 橙 | 基数写错位置是操作失误，不损坏模型语义 |

**运行时语义不受影响**：前端 `highlight.ts` 按 issue 的 `level` 字段上色
（`error`→红、`warn`→橙），**不看前缀**——所以画布上颜色始终正确。
受影响的只是"按前缀推断等级"的文档描述与工具假设。

backend 侧的处理：
- `rules.LEVEL_OVERRIDE` 显式声明偏离；`level_of()` 是等级的**唯一事实来源**
- `RIGID_IDS / HEURISTIC_IDS` 按**实际等级**派生（刚性 20 / 启发 24，非 23/21）
- `audit_rules.py` 增加等级断言（触发时 level 必须 == 声明）
- `audit_consistency.py` 检查"偏离清单 == 声明清单"，防止无意偏离混入

**建议**：若三方认可，将 INTERFACE.md 编号规范改为
"`R/H` 为历史编号前缀，显示颜色以消息的 `level` 字段为准"。

---

> 本文件由 backend 侧维护。若三方确认要把 `action="diagnosis"` 并入正式契约，
> 请同步更新 `INTERFACE.md` 并知会 A/C 两位同学。
