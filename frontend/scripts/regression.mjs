/**
 * ER Studio 第三轮回归脚本（开发环境）。
 * 运行前：npm run dev（5173）与 npm run mock（8000）已启动。
 * 用法：node scripts/regression.mjs
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";

const CHROME =
  process.env.CHROME_PATH ||
  path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe");
const URL = process.env.APP_URL || "http://127.0.0.1:5173/";
const OUT = path.resolve(".impeccable/review");
fs.mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, pass, detail = "") {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const diagram = {
  elements: [
    {
      id: "rect_001",
      shape: "rectangle",
      label: "读者",
      attributes: [
        "*读者ID",
        "xues",
        "姓名",
        "longEnglishAttributeName",
        "中英文Mixed属性Name",
        "超长属性名称测试用例",
      ],
      position: { x: 320, y: 300 },
    },
    {
      id: "rect_002",
      shape: "rectangle",
      label: "图书",
      attributes: [
        "*图书ID",
        "书名",
        "编号",
        "联系名称",
        "这是一个非常非常长的属性名称用于验证自动换行和椭圆扩展",
      ],
      position: { x: 820, y: 300 },
    },
    { id: "dia_001", shape: "diamond", label: "借阅", attributes: [], position: { x: 570, y: 170 } },
    { id: "ell_001", shape: "ellipse", label: "独立属性", attributes: [], position: { x: 320, y: 540 } },
  ],
  connections: [
    { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "M" },
    { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
  ],
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1", "--font-render-hinting=none"],
  defaultViewport: null,
});

const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("pageerror", (e) => consoleErrors.push(String(e)));

await page.evaluateOnNewDocument(() => {
  window.__wsSent = [];
  const orig = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    try {
      window.__wsSent.push(String(data));
    } catch {
      /* ignore */
    }
    return orig.call(this, data);
  };
});

await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await page.goto(URL, { waitUntil: "networkidle0", timeout: 30000 });
await page.waitForFunction(() => window.__erStore && window.__erCanvas, { timeout: 15000 });
await sleep(400);

async function worldToScreen(x, y) {
  return page.evaluate(
    ({ x, y }) => {
      const c = window.__erCanvas;
      const v = c.viewportTransform;
      const r = c.upperCanvasEl.getBoundingClientRect();
      return { x: r.left + x * v[0] + v[4], y: r.top + y * v[3] + v[5] };
    },
    { x, y },
  );
}
async function elementCenter(id) {
  const p = await page.evaluate((id) => {
    const c = window.__erCanvas;
    const o = c.getObjects().find((o) => o.erKind === "element" && o.erId === id);
    return o ? o.getCenterPoint() : null;
  }, id);
  if (!p) throw new Error(`element not found: ${id}`);
  return worldToScreen(p.x, p.y);
}
async function canvasCorner() {
  return page.evaluate(() => {
    const r = window.__erCanvas.upperCanvasEl.getBoundingClientRect();
    return { x: r.left + 40, y: r.top + 40 };
  });
}
async function freeConnection() {
  return page.evaluate(() => {
    const c = window.__erStore.connections.find((c) => c.mode === "free");
    return c ? { ...c, free_end: c.free_end ? { ...c.free_end } : null } : null;
  });
}
async function freeLineScreenPoint() {
  return page.evaluate(() => {
    const c = window.__erCanvas;
    const free = window.__erStore.connections.find((conn) => conn.mode === "free");
    if (!free) return null;
    const hit = c.getObjects().find((o) => o.erKind === "connection" && o.erId === free.id);
    if (!hit) return null;
    const v = c.viewportTransform;
    const r = c.upperCanvasEl.getBoundingClientRect();
    const mx = (hit.x1 + hit.x2) / 2;
    const my = (hit.y1 + hit.y2) / 2;
    return { x: r.left + mx * v[0] + v[4], y: r.top + my * v[3] + v[5] };
  });
}
async function screenToWorld(x, y) {
  return page.evaluate(
    ({ x, y }) => {
      const c = window.__erCanvas;
      const v = c.viewportTransform;
      const r = c.upperCanvasEl.getBoundingClientRect();
      return { x: (x - r.left - v[4]) / v[0], y: (y - r.top - v[5]) / v[3] };
    },
    { x, y },
  );
}
async function sendKey(key, modifiers) {
  if (modifiers) for (const m of modifiers) await page.keyboard.down(m);
  await page.keyboard.press(key);
  if (modifiers) for (const m of [...modifiers].reverse()) await page.keyboard.up(m);
}

// ---------- 导入样例，检查文本 ----------
await page.evaluate((d) => window.__erStore.importDiagram(d), diagram);
await sleep(900);
await page.screenshot({ path: path.join(OUT, "round3-textbook-1440.png") });

const textReport = await page.evaluate(() => {
  const c = window.__erCanvas;
  const objs = c.getObjects();
  const bad = [];
  const labels = [];
  const failures = [];
  const textNodes = [];
  for (const o of objs) {
    if (o.type === "text" && typeof o.text === "string") textNodes.push(o);
    if (o.erKind === "element" && Array.isArray(o._objects)) {
      for (const child of o._objects) if (child.type === "text") textNodes.push(child);
    }
  }
  for (const t of textNodes) {
    if (/…|\.\.\./.test(t.text)) bad.push(t.text);
  }
  const ellipses = objs.filter((o) => o.erKind === "attribute");
  for (const t of textNodes.filter((t) => t.erKind === "attrLabel")) {
    const e = ellipses.find(
      (e) => e.erAttrOwner === t.erAttrOwner && e.erAttrIndex === t.erAttrIndex,
    );
    if (!e) {
      failures.push(`no ellipse for: ${t.text}`);
      continue;
    }
    const tb = t.getBoundingRect();
    const eb = e.getBoundingRect();
    const inside =
      tb.left >= eb.left - 1 &&
      tb.top >= eb.top - 1 &&
      tb.left + tb.width <= eb.left + eb.width + 1 &&
      tb.top + tb.height <= eb.top + eb.height + 1;
    if (!inside) failures.push(`outside ellipse: ${t.text}`);
    labels.push({
      name: t.text.replace(/\n/g, " / "),
      textW: Math.round(tb.width),
      ellipseW: Math.round(eb.width),
      ellipseH: Math.round(eb.height),
      inside,
    });
  }
  return { bad, labels, failures, texts: textNodes.map((t) => t.text) };
});
check("属性文字没有省略号", textReport.bad.length === 0, JSON.stringify(textReport.bad));
check("属性文字全部在椭圆内", textReport.failures.length === 0, textReport.failures.join("；"));
check(
  "长中文 / 长英文 / 中英混合都保留完整",
  ["xues", "longEnglishAttributeName", "中英文Mixed属性Name", "超长属性名称测试用例"].every((s) =>
    textReport.texts.some((t) => t.includes(s)),
  ),
  JSON.stringify(textReport.labels),
);
const wrapped = textReport.labels.find((l) => l.name.includes("验证自动换行"));
check(
  "超长属性名称合理换行并加高椭圆",
  !!wrapped && wrapped.name.includes(" / ") && wrapped.ellipseH > 40 && wrapped.inside,
  JSON.stringify(wrapped),
);
const twoChar = textReport.labels.find((l) => l.name === "姓名");
const fourChar = textReport.labels.find((l) => l.name === "联系名称");
check("两个汉字 / 四个汉字完整显示", !!twoChar && !!fourChar, JSON.stringify({ twoChar, fourChar }));

// 属性面板改名后立即同步
await page.evaluate(() => window.__erStore.select("element", "rect_001"));
await sleep(200);
const firstAttrSelector = ".attr-row:nth-child(2) .attr-name";
const beforeRename = await page.evaluate(
  () => window.__erStore.findElement("rect_001").attributes,
);
await page.click(firstAttrSelector);
await page.keyboard.down("Control");
await page.keyboard.press("a");
await page.keyboard.up("Control");
await page.type(firstAttrSelector, "xuesNewName");
await page.keyboard.press("Tab");
await sleep(600);
const renameReport = await page.evaluate(() => {
  const el = window.__erStore.findElement("rect_001");
  const c = window.__erCanvas;
  const label = c
    .getObjects()
    .filter((o) => o.type === "text" && o.erKind === "attrLabel")
    .find((o) => o.text === "xuesNewName");
  return { attrs: Array.from(el?.attributes ?? []), canvasHasText: !!label };
});
check(
  "属性面板改名后画布即时同步",
  renameReport.canvasHasText && renameReport.attrs.includes("xuesNewName"),
  JSON.stringify(renameReport),
);

// ---------- 画布外观 ----------
const modelBefore = await page.evaluate(() => JSON.stringify(window.__erStore.elements));
await page.click('.look-wrap .chip');
await page.click('[data-bg="dark"]');
await page.click('[data-grid="lines"]');
await page.click('[data-theme="display"]');
await page.click('[data-accent="teal"]');
await sleep(400);
const look = await page.evaluate(() => {
  const c = window.__erCanvas;
  const el = c.getObjects().find((o) => o.erKind === "element");
  return {
    bg: c.backgroundColor,
    stored: JSON.parse(localStorage.getItem("erstudio.appearance") || "null"),
    bodyFill: el ? el._objects.find((o) => o.type === "rect")?.fill : null,
    model: JSON.stringify(window.__erStore.elements),
  };
});
check("背景实时切换为深色", String(look.bg).toUpperCase() === "#20242C", String(look.bg));
check(
  "网格 / 主题 / 配色写入本地持久化",
  look.stored?.grid === "lines" && look.stored?.theme === "display" && look.stored?.accent === "#0F766E",
  JSON.stringify(look.stored),
);
check("图形主题改变渲染不改数据模型", look.model === modelBefore, "elements unchanged");
check("展示主题下图形有克制填充", look.bodyFill && look.bodyFill !== "#FFFFFF", String(look.bodyFill));
await page.screenshot({ path: path.join(OUT, "round3-dark-display-1440.png") });
if (await page.$(".look-menu")) {
  await page.click('.look-wrap .chip');
  await sleep(200);
}
await page.keyboard.press("Escape");
await page.mouse.click((await canvasCorner()).x, (await canvasCorner()).y);

// ---------- 自由端连线 ----------
await page.evaluate(() => window.__erStore.setTool("select"));
const beforeTexts = await page.evaluate(
  () => window.__erCanvas.getObjects().filter((o) => o.type === "text").length,
);
await page.click('button[title^="自由端连线"]');
const rectCenter = await elementCenter("rect_001");
await page.mouse.click(rectCenter.x, rectCenter.y);
await sleep(150);
const pending = await page.evaluate(() => window.__erStore.pendingFromId);
check("自由端：第一次点击固定参与者", pending === "rect_001", String(pending));

await page.mouse.move(rectCenter.x + 230, rectCenter.y + 130, { steps: 8 });
await sleep(200);
const targetScreen = { x: rectCenter.x + 230, y: rectCenter.y + 130 };
const targetWorld = await screenToWorld(targetScreen.x, targetScreen.y);
const preview = await page.evaluate(() => {
  const o = window.__erCanvas
    .getObjects()
    .find((o) => o.type === "line" && String(o.stroke).toUpperCase() === "#7C93FF");
  return o ? { dashed: Array.isArray(o.strokeDashArray), x1: o.x1, y1: o.y1, x2: o.x2, y2: o.y2 } : null;
});
check("自由端：移动时显示淡蓝预览线", !!preview && preview.dashed, JSON.stringify(preview));
await page.screenshot({ path: path.join(OUT, "round3-free-preview-1440.png") });

await page.mouse.click(rectCenter.x + 230, rectCenter.y + 130);
await sleep(500);
let free = await freeConnection();
check("自由端：点击画布生成 free 连线", !!free && free.from === "rect_001", JSON.stringify(free));
check(
  "自由端：终点没有吸附到其它图形",
  !!free &&
    Math.abs(free.free_end.x - targetWorld.x) <= 2 &&
    Math.abs(free.free_end.y - targetWorld.y) <= 2,
  `${JSON.stringify(free?.free_end)} vs ${JSON.stringify(targetWorld)}`,
);
const afterTexts = await page.evaluate(
  () => window.__erCanvas.getObjects().filter((o) => o.type === "text").length,
);
check("自由端：不添加任何标签 / 端点文字", afterTexts === beforeTexts, `${beforeTexts} -> ${afterTexts}`);
const freeCount = await page.evaluate(
  () => window.__erCanvas.getObjects().filter((o) => o.erKind === "freeEnd").length,
);
check("自由端：选中时显示临时编辑控制点", freeCount === 1, `handles=${freeCount}`);
await page.screenshot({ path: path.join(OUT, "round3-free-selected-1440.png") });

// 取消选中后控制点隐藏
await page.mouse.click((await canvasCorner()).x, (await canvasCorner()).y);
await sleep(250);
const freeCountAfterBlur = await page.evaluate(
  () => window.__erCanvas.getObjects().filter((o) => o.erKind === "freeEnd").length,
);
check("自由端：取消选中后隐藏控制点", freeCountAfterBlur === 0, `handles=${freeCountAfterBlur}`);

// 重新选中并拖动自由端
const linePoint = await freeLineScreenPoint();
await page.mouse.click(linePoint.x, linePoint.y);
await sleep(300);
const handlePoint = await page.evaluate(() => {
  const c = window.__erCanvas;
  const h = c.getObjects().find((o) => o.erKind === "freeEnd");
  if (!h) return null;
  const p = h.getCenterPoint();
  const v = c.viewportTransform;
  const r = c.upperCanvasEl.getBoundingClientRect();
  return { x: r.left + p.x * v[0] + v[4], y: r.top + p.y * v[3] + v[5] };
});
const freeBeforeDrag = await freeConnection();
const handleState = await page.evaluate(() => ({
  selected: window.__erStore.selectedKind,
  id: window.__erStore.selectedId,
  handles: window.__erCanvas.getObjects().filter((o) => o.erKind === "freeEnd").length,
}));
check(
  "自由端：重新选中连线后出现控制点",
  handleState.selected === "connection" && handleState.handles === 1,
  JSON.stringify(handleState),
);
if (handlePoint) {
  await page.mouse.move(handlePoint.x, handlePoint.y);
  await page.mouse.down();
  await page.mouse.move(handlePoint.x + 55, handlePoint.y + 35, { steps: 8 });
  await page.mouse.up();
  await sleep(500);
}
const freeAfterDrag = await freeConnection();
check(
  "自由端：控制点可独立拖动",
  !!freeAfterDrag &&
    !!freeBeforeDrag &&
    (freeAfterDrag.free_end.x !== freeBeforeDrag.free_end.x ||
      freeAfterDrag.free_end.y !== freeBeforeDrag.free_end.y),
  `${JSON.stringify(freeBeforeDrag?.free_end)} -> ${JSON.stringify(freeAfterDrag?.free_end)}`,
);

// 拖动自由端本身也可以撤销 / 重做
await sendKey("z", ["Control"]);
await sleep(500);
const freeAfterHandleUndo = await freeConnection();
await sendKey("y", ["Control"]);
await sleep(500);
const freeAfterHandleRedo = await freeConnection();
check(
  "自由端：拖动端点可撤销 / 重做",
  freeAfterHandleUndo.free_end.x === freeBeforeDrag.free_end.x &&
    freeAfterHandleUndo.free_end.y === freeBeforeDrag.free_end.y &&
    freeAfterHandleRedo.free_end.x === freeAfterDrag.free_end.x &&
    freeAfterHandleRedo.free_end.y === freeAfterDrag.free_end.y,
  `${JSON.stringify(freeAfterHandleUndo?.free_end)} / ${JSON.stringify(freeAfterHandleRedo?.free_end)}`,
);

// 拖动起点图形：自由端保持不动
const freeEndBeforeMove = { ...freeAfterDrag.free_end };
const moveFrom = await elementCenter("rect_001");
await page.mouse.click(moveFrom.x, moveFrom.y);
await sleep(250);
await page.mouse.move(moveFrom.x, moveFrom.y);
await page.mouse.down();
await page.mouse.move(moveFrom.x + 60, moveFrom.y + 45, { steps: 10 });
await page.mouse.up();
await sleep(500);
const afterMove = await page.evaluate(() => {
  const s = window.__erStore;
  const c = s.connections.find((c) => c.mode === "free");
  return { free: c ? { ...c.free_end } : null, pos: { ...s.findElement("rect_001").position } };
});
check(
  "自由端：拖动起点图形时自由终点不动",
  afterMove.free.x === freeEndBeforeMove.x && afterMove.free.y === freeEndBeforeMove.y,
  `${JSON.stringify(freeEndBeforeMove)} -> ${JSON.stringify(afterMove.free)}`,
);
const lineAfterMove = await freeLineScreenPoint();
const lineBeforeMove = await page.evaluate(() => {
  const c = window.__erCanvas.getObjects().find((o) => o.type === "line" && o.strokeDashArray === null && o.erKind === undefined);
  return null;
});
void lineAfterMove;
void lineBeforeMove;

// 撤销 / 重做
const posAfterMove = { ...afterMove.pos };
await sendKey("z", ["Control"]);
await sleep(600);
const posUndo = await page.evaluate(() => ({ ...window.__erStore.findElement("rect_001").position }));
await sendKey("y", ["Control"]);
await sleep(600);
const posRedo = await page.evaluate(() => ({ ...window.__erStore.findElement("rect_001").position }));
check(
  "自由端：撤销 / 重做可用",
  (posUndo.x !== posAfterMove.x || posUndo.y !== posAfterMove.y) &&
    posRedo.x === posAfterMove.x &&
    posRedo.y === posAfterMove.y,
  `${JSON.stringify(posAfterMove)} / ${JSON.stringify(posUndo)} / ${JSON.stringify(posRedo)}`,
);

// 删除 / 撤销恢复
const delPoint = await freeLineScreenPoint();
await page.mouse.click(delPoint.x, delPoint.y);
await sleep(250);
await page.keyboard.press("Delete");
await sleep(400);
const afterDelete = await page.evaluate(() => window.__erStore.connections.some((c) => c.mode === "free"));
await sendKey("z", ["Control"]);
await sleep(600);
const afterDeleteUndo = await freeConnection();
check("自由端：可删除并撤销恢复", afterDelete === false && !!afterDeleteUndo, `${afterDelete} / ${!!afterDeleteUndo}`);

// 导出 / 导入
const exported = await page.evaluate(() => window.__erStore.exportDiagram());
const exportedFree = exported.connections.find((c) => c.mode === "free");
check(
  "自由端：导出包含 mode/free_end",
  !!exportedFree && !!exportedFree.free_end,
  JSON.stringify(exportedFree),
);
await page.evaluate((d) => window.__erStore.importDiagram(d), exported);
await sleep(700);
const reimported = await freeConnection();
check(
  "自由端：导入后端点保持",
  !!reimported &&
    Math.abs(reimported.free_end.x - exportedFree.free_end.x) <= 1 &&
    Math.abs(reimported.free_end.y - exportedFree.free_end.y) <= 1,
  JSON.stringify(reimported?.free_end),
);

// 全量检查不把自由端发给后端
await page.evaluate(() => window.__erStore.batchCheck());
await sleep(600);
const wsReport = await page.evaluate(() => {
  const sent = window.__wsSent || [];
  const bad = [];
  for (const raw of sent) {
    try {
      const msg = JSON.parse(raw);
      if (msg.action === "batch_check") {
        for (const c of msg.diagram?.connections || []) {
          if (c.mode === "free" || "free_end" in c || c.to === "") bad.push(c);
        }
      }
      if (msg.connection && (msg.connection.mode === "free" || "free_end" in msg.connection)) {
        bad.push(msg.connection);
      }
    } catch {
      /* ignore */
    }
  }
  return { bad, count: sent.length };
});
check("自由端：不进入后端协议报文", wsReport.bad.length === 0, JSON.stringify(wsReport.bad));
const draft = await page.evaluate(() =>
  window.__erStore.allIssues.some((r) => r.issue.rule_id === "D01" && r.issue.level === "warn"),
);
check("自由端：全量检查标记为草稿 D01", draft, "");

// 三类参与者都能作为自由端起点
const participants = await page.evaluate(() => {
  const s = window.__erStore;
  s.addFreeConnection("ell_001", { x: 180, y: 650 });
  s.addFreeConnection("dia_001", { x: 760, y: 90 });
  return s.connections.filter((c) => c.mode === "free").map((c) => c.from);
});
check(
  "自由端：实体 / 属性 / 联系都可作为起点",
  ["rect_001", "ell_001", "dia_001"].every((id) => participants.includes(id)),
  JSON.stringify(participants),
);

// ---------- 缩放下的文字 ----------
await page.evaluate(() => window.__erCanvas.setViewportTransform([0.6, 0, 0, 0.6, 120, 80]));
await sleep(300);
const zoomText = await page.evaluate(() => {
  const t = window.__erCanvas.getObjects().find((o) => o.type === "text" && o.erKind === "attrLabel");
  return t ? { text: t.text, scale: t.getTotalScale?.( ) } : null;
});
void zoomText;
await page.screenshot({ path: path.join(OUT, "round3-zoom-60-1440.png") });
await page.evaluate(() => window.__erCanvas.setViewportTransform([1, 0, 0, 1, 0, 0]));

// ---------- 刷新持久化 ----------
const expectedBg = look.bg;
await page.reload({ waitUntil: "networkidle0" });
await page.waitForFunction(() => window.__erCanvas, { timeout: 15000 });
await sleep(500);
const persisted = await page.evaluate(() => ({
  bg: window.__erCanvas.backgroundColor,
  stored: JSON.parse(localStorage.getItem("erstudio.appearance") || "null"),
}));
check(
  "刷新后保留画布外观",
  String(persisted.bg).toUpperCase() === String(expectedBg).toUpperCase() &&
    persisted.stored?.theme === "display",
  JSON.stringify(persisted),
);

// 网格关闭 / 自定义背景 / 恢复默认
await page.click('.look-wrap .chip');
await page.click('[data-grid="off"]');
await sleep(250);
const gridOff = await page.evaluate(() => {
  const c = window.__erCanvas;
  const big = c.getObjects().find((o) => o.type === "rect" && o.width === 16000);
  return {
    grid: JSON.parse(localStorage.getItem("erstudio.appearance") || "null")?.grid,
    visible: big ? big.visible : null,
    bg: c.backgroundColor,
  };
});
check("网格可关闭且不覆盖背景", gridOff.grid === "off" && gridOff.visible === false, JSON.stringify(gridOff));

await page.$eval('input[type="color"]', (el) => {
  el.value = "#123456";
  el.dispatchEvent(new Event("input", { bubbles: true }));
});
await sleep(300);
const custom = await page.evaluate(() => ({
  bg: window.__erCanvas.backgroundColor,
  stored: JSON.parse(localStorage.getItem("erstudio.appearance") || "null"),
}));
check(
  "自定义背景颜色实时生效",
  String(custom.bg).toUpperCase() === "#123456" && custom.stored?.background === "#123456",
  JSON.stringify(custom),
);
await page.click(".menu-head .reset");
await sleep(250);
const reset = await page.evaluate(() => ({
  bg: window.__erCanvas.backgroundColor,
  stored: JSON.parse(localStorage.getItem("erstudio.appearance") || "null"),
}));
check(
  "恢复默认外观",
  String(reset.bg).toUpperCase() === "#FFFFFF" && reset.stored?.theme === "textbook" && reset.stored?.grid === "dots",
  JSON.stringify(reset),
);
if (await page.$(".look-menu")) await page.click('.look-wrap .chip');

// 窄屏抽屉式检查器
await page.setViewport({ width: 800, height: 720, deviceScaleFactor: 1 });
await sleep(400);
const closedRect = await page.evaluate(() => {
  const r = document.querySelector("#inspector-panel").getBoundingClientRect();
  const t = document.querySelector(".drawer-toggle");
  return { right: r.right, left: r.left, toggle: !!t, overflow: document.documentElement.scrollWidth > innerWidth };
});
await page.click(".drawer-toggle");
await sleep(300);
const openRect = await page.evaluate(() => {
  const r = document.querySelector("#inspector-panel").getBoundingClientRect();
  const s = document.querySelector(".drawer-scrim");
  return { left: r.left, right: r.right, width: r.width, scrim: !!s, vw: innerWidth };
});
await page.screenshot({ path: path.join(OUT, "round3-narrow-drawer-800.png") });
await page.mouse.click(80, 200);
await sleep(300);
const closedAgain = await page.evaluate(
  () => !document.querySelector("#inspector-panel")?.classList.contains("drawer-open"),
);
check(
  "窄屏：检查器以抽屉形式打开 / 关闭",
  closedRect.toggle &&
    closedRect.right > 800 &&
    openRect.right <= openRect.vw + 1 &&
    openRect.width > 280 &&
    openRect.scrim &&
    closedAgain,
  JSON.stringify({ closedRect, openRect, closedAgain }),
);
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });

check("无控制台错误", consoleErrors.length === 0, consoleErrors.slice(0, 4).join(" | "));

console.log("\nSUMMARY");
for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}\t${r.name}`);
const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
await browser.close();
process.exit(failed.length ? 1 : 0);
