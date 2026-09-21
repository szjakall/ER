# frontend —— ER 图实时规范校验（前端 / A 同学）

Vue 3 + Fabric.js。画布是**本地事实源**，WebSocket 只做校验、不阻塞继续画图。

## 运行

```powershell
npm.cmd install
npm.cmd run mock     # 终端 1：本地模拟后端 ws://localhost:8000/ws（可选）
npm.cmd run dev      # 终端 2：http://localhost:5173
```

> PowerShell 里必须用 `npm.cmd`。详见仓库根目录 `README.md`。

## 结构

```
frontend/
├─ src/
│  ├─ App.vue                 布局 / 状态栏 / 提示条
│  ├─ ui/                     Toolbar / ErCanvasView / Inspector / IssuePanel
│  ├─ canvas/
│  │  ├─ ErCanvas.ts          Fabric 画布：元素/连线/属性椭圆、拖拽跟随、缩放平移
│  │  ├─ shapes.ts            图形绘制、属性扇形排布（松弛避让）、弱实体双线框
│  │  ├─ connectors.ts        连线绘制、基数符号（写在连线上方）
│  │  ├─ overlap.ts           几何重叠检测（R20）
│  │  ├─ geometry.ts          文本宽度估算、射线与图形求交
│  │  └─ highlight.ts         状态 → 颜色映射（红/橙/绿/灰）
│  ├─ protocol/               INTERFACE.md 的消息类型与编解码
│  ├─ model/store.ts          Pinia：模型 + 各操作自动发消息 + 着色状态
│  └─ samples/                三个示例图 JSON
├─ mock/mockServer.mjs        本地模拟后端（仅示例规则，便于前端联调）
└─ index.html / vite.config.ts / tsconfig.json
```

## 约定

- 协议字段名与 `INTERFACE.md` **1:1**，不要改成 camelCase。
- 基数：一条线只写一个符号（`1`/`N`/`M`/`P`），两个符号合起来才是 `M:N` 这类对应关系。
- 属性前缀：`*` = 主键，`#` = 部分键。
- `attr_offsets` 只用于画布排版，**不发给后端**。