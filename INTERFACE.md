# 接口契约 —— ER图实时提示系统

> **警告**：此文件中定义的任何消息格式变更，必须三人同时确认。
> 修改后必须同步更新 `test/fixtures/test_cases.json`。

---

## 通信方式

```
前端（Vue.js + Fabric.js） ←──WebSocket──→ 后端（Python FastAPI）
         │                                        │
         ├─ 用户在画布上操作                       │
         ├─ 打包成 JSON 发给后端                   │
         │                                        ├─ 收到事件，匹配规则
         │                                        ├─ 返回 violations + suggestions
         ├─ 收到结果，在画布上渲染警告              │
```

- 地址: `ws://localhost:8000/ws`
- 编码: UTF-8 JSON
- 超时: 前端发消息后等 2 秒，超时忽略（不阻塞画布操作）

---

## 消息总览

| 方向 | action 值 | event 值 | 触发时机 |
|---|---|---|---|
| 前端→后端 | `check` | `element_added` | 用户在画布上新建矩形（实体）或椭圆（属性） |
| 前端→后端 | `check` | `element_modified` | 用户修改了元素名称或属性列表 |
| 前端→后端 | `check` | `connection_added` | 用户画了一条连线 |
| 前端→后端 | `check` | `connection_modified` | 用户修改了连线类型或基数 |
| 前端→后端 | `check` | `element_deleted` | 用户删除了元素（可能造成孤立属性） |
| 前端→后端 | `batch_check` | — | 一次性检查整张图（用于导入或打开已有设计） |
| 后端→前端 | `result` | — | 单次检查结果 |
| 后端→前端 | `batch_result` | — | 批量检查结果 |
| 后端→前端 | `error` | — | 后端处理异常 |

---

## 详细消息格式

### 1. 新增实体 element_added

```jsonc
// 前端 → 后端
{
  "action": "check",
  "event": "element_added",
  "element": {
    "id": "rect_001",           // string, 画布元素唯一ID
    "shape": "rectangle",       // "rectangle" | "ellipse" | "diamond"
    "label": "读者",            // string, 元素名称（可为空串）
    "attributes": [             // string[], 仅 rectangle/ellipse 有
      "读者ID",
      "姓名",
      "电话"
    ],
    "position": { "x": 120, "y": 300 }  // 画布坐标，暂不用，预留
  }
}

// 后端 → 前端
{
  "action": "result",
  "element_id": "rect_001",     // 对应请求中的 id
  "violations": [               // 刚性错误（红色标注）
    {
      "rule_id": "R01",
      "level": "error",
      "message": "实体'读者'缺少主键标注 —— 请在属性名前加 * 号"
    }
  ],
  "suggestions": [              // 启发建议（橙色标注）
    {
      "rule_id": "H03",
      "level": "warn",
      "message": "属性'电话'可能为多值属性，建议拆分为独立实体或关联表"
    }
  ]
}
```

### 2. 修改元素 element_modified

```jsonc
// 前端 → 后端
{
  "action": "check",
  "event": "element_modified",
  "element": {
    "id": "rect_001",
    "shape": "rectangle",
    "label": "读者",
    "attributes": ["*读者ID", "姓名", "电话", "邮箱"],
    "position": { "x": 120, "y": 300 }
  },
  "changes": {                  // 本次修改了哪些字段
    "attributes_changed": true,
    "label_changed": false
  }
}

// 后端 → 前端（格式同上）
```

### 3. 新增连线 connection_added

```jsonc
// 前端 → 后端
{
  "action": "check",
  "event": "connection_added",
  "connection": {
    "id": "conn_001",
    "from": "rect_001",         // 源元素 id
    "to": "rect_002",           // 目标元素 id
    "type": "line",             // "line"（普通连线）| "diamond_line"（联系）
    "label": "",                // 连线标签（联系名称）
    "cardinality": null         // null | "1:1" | "1:N" | "M:N" | "N:M"
  }
}

// 后端 → 前端
{
  "action": "result",
  "element_id": "conn_001",
  "violations": [
    {
      "rule_id": "R05",
      "level": "error",
      "message": "连线缺少基数标注（如 1:1, 1:N, M:N）"
    },
    {
      "rule_id": "R06",
      "level": "error",
      "message": "联系必须标注名称（如'借阅'、'属于'）"
    }
  ],
  "suggestions": []
}
```

### 4. 批量检查 batch_check

```jsonc
// 前端 → 后端（打开已保存的设计时一次性检查）
{
  "action": "batch_check",
  "diagram": {
    "elements": [
      { "id": "rect_001", "shape": "rectangle", "label": "读者", "attributes": ["*读者ID", "姓名"] },
      { "id": "rect_002", "shape": "rectangle", "label": "图书", "attributes": ["*图书ID", "书名"] }
    ],
    "connections": [
      { "id": "conn_001", "from": "rect_001", "to": "rect_002", "type": "diamond_line", "label": "借阅", "cardinality": "M:N" }
    ]
  }
}

// 后端 → 前端
{
  "action": "batch_result",
  "results": {
    "rect_001": { "violations": [], "suggestions": [] },
    "rect_002": { "violations": [], "suggestions": [] },
    "conn_001": { "violations": [], "suggestions": [] }
  }
}
```

### 5. 错误响应

```jsonc
// 后端 → 前端
{
  "action": "error",
  "element_id": "rect_001",
  "message": "消息格式错误: 'attributes' 字段应为数组，收到了字符串"
}
```

---

## 规则编号规范

| 前缀 | 含义 | 显示颜色 | 示例 |
|---|---|---|---|
| `R` | 刚性规则（必须修复） | 🔴 红色 | R01: 实体缺少主键 |
| `H` | 启发规则（建议优化） | 🟠 橙色 | H03: 可能的多值属性 |

详细规则列表见 `docs/RULES.md`。

---

## 变更记录

| 日期 | 变更内容 | 提出人 | 确认人 |
|---|---|---|---|
| 2026-06-12 | 初始版本，定义全部消息格式 | — | — |
