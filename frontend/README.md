# frontend —— ER 图实时规范校验（前端 / A 同学）

Vue 3 + Fabric.js。画布是**本地事实源**，WebSocket 只做校验、不阻塞继续画图。
视觉规则见仓库根目录 `DESIGN.md`：画布是教材式黑白陈氏记法，外壳是 Premium SaaS。

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
│  ├─ App.vue                 应用外壳：顶栏 / 工作区 / 诊断 Dock / 状态栏，面板尺寸持久化
│  ├─ ui/                     TopBar / LeftToolbar / ErCanvasView / Inspector / IssuePanel
│  │  ├─ SplitHandle.vue      可拖拽、可键盘操作的 8px 面板分隔条
│  │  └─ usePersistentNumber.ts  面板尺寸的 localStorage 读写
│  ├─ canvas/
│  │  ├─ ErCanvas.ts          Fabric 画布：层序、选择、外环、拖拽吸附、滚轮/空格、页面
│  │  ├─ theme.ts             画布唯一真值：墨色 / 纸白 / 线宽 / 字级 / 几何
│  │  ├─ shapes.ts            图形本体、属性扇形排布、双矩形/双椭圆/虚椭圆/双菱形
│  │  ├─ connectors.ts        连线、实体端基数符号
│  │  ├─ page.ts              比例预设（含 A4 纵向）、页面计算、点阵 Pattern、8px 吸附
│  │  ├─ layout.ts            智能布局：图结构分层 / 联系居中 / 属性环绕 / 去重叠 / 页面填充 / 统一缩放
│  │  ├─ overlay.ts           外环 / 悬停框 / 选择框的统一轮廓
│  │  ├─ overlap.ts           几何重叠检测（R20）
│  │  ├─ geometry.ts          文本宽度估算、射线与图形求交
│  │  └─ highlight.ts         严重度 → 外环颜色（不再改图形填充 / 描边）
│  ├─ protocol/               INTERFACE.md 的消息类型与编解码（白名单，剥离本地排版字段）
│  ├─ model/store.ts          Pinia：模型 + 操作自动发消息 + 着色状态 + 整理布局
│  └─ samples/                三个示例图 JSON
├─ mock/mockServer.mjs        本地模拟后端（仅示例规则，便于前端联调）
└─ index.html / vite.config.ts / tsconfig.json
```

## 回归

开发服务器（5173）与 mock（8000）启动后：

```powershell
node scripts/regression.mjs          # 第三轮 34 项回归
node scripts/layout-regression.mjs   # 第四轮 6 组测试图 × 5 比例 = 459 项布局回归
node scripts/round5-regression.mjs   # 第五轮 77 项：画布比例 / 自动布局 / 视口解耦
node scripts/layout-shots.mjs        # 生成 .impeccable/review/clean-*.png 核查截图
```

## 约定

- 协议字段名与 `INTERFACE.md` **1:1**，不要改成 camelCase。
- 基数：一条线只写一个符号（`1`/`N`/`M`/`P`），两个符号合起来才是 `M:N` 这类对应关系。
- 属性前缀：`*` = 主键，`#` = 部分键。
- `attr_offsets` / `attr_style` / `size` / `layout_scale` / `is_identifying` 只用于画布排版，**不发给后端**。
- `layout_scale` 是内容级缩放：图形尺寸、字号、描边、连线端点、基数标签共用它；
  Fabric 的 `viewportTransform` 只负责把页面装进屏幕，两者不能重复缩放。
- 三个系统互相独立：**画布比例**只决定页面盒尺寸；**自动布局**只重排图形并装进当前页面（不改比例、不改画布宽高、不重置视口，内容过多时才按比例扩大）；
  **视口**只由缩放 / 平移 / 适应命令控制。「适应画布」只装页面，「适应全部图形」只装图形包围盒。
- 可见描边（图形、属性椭圆、连线、归属线）随 `viewportTransform` 缩放，与文字保持同一比例；
  只有命中线、选择框、严重度外环使用 `strokeUniform` 固定在屏幕上。
- 画布图形永远白底墨线；错误 / 建议只用图外环、诊断卡与状态栏表达。
- 画布比例 / 自动布局菜单是 Teleport 到 `body` 的固定定位浮层，不参与画布容器布局，也不改变缩放状态。
