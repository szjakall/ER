# B 后端交付目标（已全部达成）

> 交付时的可判定契约与最终验收状态。
> 实现细节、使用说明、实测数据以 [`README.md`](README.md) 为准。

## 目标

交付符合 `INTERFACE.md` 协议的 ER 规则引擎后端服务（`backend/`），
字典树索引 35+ 条刚性/启发规则，WebSocket 实时校验，延迟 <100ms。

## 成功准则与最终验收

| id | 准则 | 状态 | 验收证据 |
|---|---|---|---|
| g1 | 新服务落在 `backend/`，`er-rule-engine/` 与 `frontend/` 零改动 | ✅ | `git status` 仅 backend/ 与文档 |
| g2 | 规则总数 ≥35，每条有唯一 id、等级、触发事件 | ✅ | **44 条**（刚性 19 / 启发 25），见 RULES.md |
| g3 | 字典树按事件类型索引，单次只跑规则子集 | ✅ | 单测断言 + trie stats（element_added 命中 16/44） |
| g4 | WS 服务监听 `ws://localhost:8000/ws`，支持 5 类消息 | ✅ | e2e + 学生流程走查实测 |
| g5 | 输出符合协议：violations(error) / suggestions(warn) | ✅ | 协议一致性审计 58 项 |
| g6 | 每条规则至少有正例或反例测试，全通过 | ✅ | 单元测试 89 项 + 规则真实性 44/44 |
| g7 | 延迟基准实测 p95 < 100ms | ✅ | 单笔 p95 最高 0.64ms（v1.4 实测） |
| g8 | 端到端：前端同款消息格式，得到正确结果 | ✅ | e2e 20 项 + 学生流程 21 项 |

超出原目标的交付（需求书研究内容三的完整落地）：

| 能力 | 位置 |
|---|---|
| 薄弱点记录（用户标识/错误类型/时间/次数/上下文） | `weakness.py` + HTTP `/weakness` |
| 学情数据持久化（重启不丢、崩溃半行自愈） | JSONL 追加写 + `audit_persist/crash_recovery` |
| LLM 深度归因（Provider 抽象 + 自动降级） | `llm.py` + HTTP `/diagnosis` |
| 异步调度（规则引擎优先、LLM 异步增强） | `diagnose_queue.py`（投递 0.8μs，热路径 O(1)） |

## 约束（用户明确）

- **不改动 `er-rule-engine/`**（现有 32 条规则原样保留，作为参考）
- **不改动 `frontend/`**（A 的前端已完成）
- 只新增后端服务
- 严格遵循 `INTERFACE.md` 消息格式（扩展项在 PROTOCOL-EXTENSIONS.md 单独声明）

## 关键设计决定

**现有 er-rule-engine 的 32 条规则不可复用**：它用 `relationships[]`/`from_entity`/`is_primary_key`
的表结构语义模型，而 INTERFACE.md + 前端用 **Chen 记法**（菱形=联系图元、单字符基数 1/N/M/P 写在
联系分支线上、属性为 `string[]` 靠 `*` 前缀表主键）。两者是不同范式，无法靠字段改名适配。
故新引擎按 Chen 记法重写，规则语义参考旧规则清单但判定逻辑全新。
