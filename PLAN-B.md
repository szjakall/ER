# B（后端规则引擎）决策记录（已完成）

> **状态：已交付**。本文档保留的是开发过程中的关键决策脉络，供回溯；
> **最终实现、使用说明、实测数据一律以 [`backend/README.md`](backend/README.md) 为准。**
> 目标仓库：https://github.com/szjakall/ER

---

## 1. 核心决策：为什么重写而不是复用旧引擎

仓库里原有两套体系：

| | `INTERFACE.md`（根目录） | `er-rule-engine/`（原有代码） |
|---|---|---|
| 范式 | **Chen 记法**画布：菱形=联系图元、单字符基数（1/N/M/P）写在联系分支线上、属性为 `string[]` 靠 `*`/`#` 前缀 | 表结构语义：`relationships[]`/`from_entity`/`is_primary_key` |
| 输出 | `violations` + `suggestions` | 单一 `errors` 数组 |

前端（A）与 Mock（C）都按 `INTERFACE.md` 实现，旧引擎的输入模型在协议里
根本不存在。**结论：保留前端与 Mock，按 Chen 记法重写 44 条规则**；
旧 `er-rule-engine/` 原样保留作参考（18 项基线测试持续验证未被破坏）。

## 2. 当初识别的风险与后续走向

| 当初的判断 | 最终走向 |
|---|---|
| shell 不可用（0xC0000142）| 解除：沙箱策略放开后可正常运行 |
| "35+ 条规则"的缺口 | 交付 44 条（刚性 19 / 启发 25） |
| "字典树保证 <100ms"的表述 | 实测修正：字典树本身加速仅 ~1.15x；真正生效的是事件子集 + 图指纹跳过（见 README） |
| 规则教学正确性未知 | 三轮审计 + 两轮独立教学审查，累计修复 10+ 处误判/漏报（详见 RULES.md 修订记录 v1.1–v1.4） |

## 3. 遗留事项（需三方协作）

1. **前端 R12 那半**：`store.ts:372` 对同一对元素不分方向拒绝第二条连线，
   学生画不出递归联系（"员工—管理—员工"）。后端已支持；需 A 放行
   "实体 ↔ 同一菱形"的第二条分支线。
2. **INTERFACE.md 编号规范**：R07/R09/R13/R16 是 R 前缀但启发级（有意偏离），
   建议把规范改为"显示颜色以 `level` 字段为准"，见
   [`backend/PROTOCOL-EXTENSIONS.md`](backend/PROTOCOL-EXTENSIONS.md) 第五节。
3. **协议扩展确认**：`action="diagnosis"`（LLM 归因推送）已文档化，
   待三方确认是否并入正式契约。

## 4. 交付物导航

| 内容 | 位置 |
|---|---|
| 使用说明 + 实测数据 | [backend/README.md](backend/README.md) |
| 规则清单（44 条，v1.4 与代码逐行对齐） | [backend/RULES.md](backend/RULES.md) |
| 协议扩展声明 | [backend/PROTOCOL-EXTENSIONS.md](backend/PROTOCOL-EXTENSIONS.md) |
| 质量审计（18 脚本 / 21 项回归） | `backend/audit_*.py`、`backend/test_engine.py` |
