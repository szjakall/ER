# ER 图实时规范校验（课题二）

学生画 ER 图时实时给出规范校验反馈。前端负责画布与交互，通过 WebSocket 把每次操作发给后端，
再把后端返回的 `violations` / `suggestions` 在画布上标成红 / 橙 / 绿。

## 目录结构

| 路径 | 负责 | 说明 |
|---|---|---|
| `frontend/` | **A（前端）** | ER 图画布 + WebSocket 客户端 + 三色标注 |
| `INTERFACE.md` | 三人共同 | 接口契约。**字段名以它为准，改动必须三人确认** |
| `ER.md` | — | 课题说明 |
| `使用说明.txt` | — | 前端启动速查 |

后端（B）与规则/测试（C）的目录待补充。

## 快速开始（复现前端）

需要 Node.js 18+（本项目在 Node 24 上验证通过）。

```bash
git clone https://github.com/szjakall/ER.git
cd ER/frontend
npm install
```

然后开 **两个终端**：

```powershell
# 终端 1：本地模拟后端（ws://localhost:8000/ws），只为前端联调三色标注
npm.cmd run mock

# 终端 2：前端开发服务器
npm.cmd run dev        # 浏览器打开 http://localhost:5173
```

> - **Windows PowerShell 里必须写 `npm.cmd`**，直接写 `npm` 会被脚本执行策略拦住（running scripts is disabled）。
> - 不启动 mock 也能画图，只是所有元素保持**灰色**（没有校验结果）。
> - 等 B 的后端就绪后，停掉 mock、启动他的服务（同样监听 `ws://localhost:8000/ws`），**前端代码一行都不用改**。

## 前端功能

- **画布**：矩形 = 实体、椭圆 = 属性、菱形 = 联系。
  工具栏「实体 / 属性 / 联系 / 连线」**单击建一个，双击进入连续创建**（`Esc` 退出）。
- **属性**：选中实体或联系 → 右侧「**批量添加属性**」，一行一个（也支持逗号 / 空格分隔），一次全部添加。
  - `*属性名` = 主键（实线下划线）；`#属性名` = 部分键（虚线下划线）。
  - 属性会自动画成旁边的椭圆并**扇形散开**（互相不重叠），也可以**拖动**微调位置。
- **联系基数**：只写在「菱形联系 ↔ 实体」的连线上，**一条线一个符号**（`1` / `N` / `M`，三元联系用 `P`）。
  点选那条线，线上会弹出 `1 N M P` 选择器。实体连属性的线不写基数。
- **三色反馈**：`violations` → 🔴 红，`suggestions` → 🟠 橙，通过 → 🟢 绿，未检查 → 灰。
- **本地几何规则 R20**：连线压到其它元素或属性椭圆时，该连线标红提示「请拖动元素或属性椭圆避开」。
- **示例图**：工具栏三个按钮 —— 学生选课（M:N）/ 三元联系（M:N:P）/ 弱实体（1:N，双线矩形 + 部分键）。
- **文件**：导入 / 导出 JSON、全量检查、撤销 / 重做 / 清空。

## 与后端联调

- 地址固定 `ws://localhost:8000/ws`，UTF-8 JSON，2 秒超时（超时忽略，不阻塞画布）。
- 前端发出：`element_added` / `element_modified` / `element_deleted` / `connection_added` / `connection_modified` / `batch_check`。
- 前端接收：`result` / `batch_result` / `error`。
- 字段细节见 `INTERFACE.md`。

## 构建

```bash
npm run build       # 产物在 frontend/dist/
npm run preview     # 本地预览构建产物
```