/**
 * 第五轮：画布尺寸 / 自动布局 / 视口系统解耦回归。
 *
 * 运行前：vite dev（5173）与 mock ws（8000）已启动。
 * 用法：node scripts/round5-regression.mjs
 *
 * 验收项：
 * 1. 16:9 / 4:3 / 1:1 / A4 等比例画布正确显示；
 * 2. 打开自动布局菜单时比例入口仍可见；浮层不改变画布容器尺寸 / 缩放；
 * 3. 自动布局只重排图形，比例与视口不变；
 * 4. 自动布局后仍能切换 4:3；
 * 5. 切换比例后文字 / 图形清晰且不重叠；
 * 6. 放大缩小时文字、边框、连线同步缩放（可见描边不再 strokeUniform）；
 * 7. 适应画布 = 整页装进视口；
 * 8. 适应全部图形 = 所有图形装进视口；两者结果不同；
 * 9. 连续切换比例不出现画布错位；
 * 10. 撤销自动布局恢复布局前位置。
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, pass, detail = "") {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

const DIAGRAM = {
  elements: [
    {
      id: "rect_001",
      shape: "rectangle",
      label: "学生",
      attributes: ["*学号", "姓名", "性别"],
      position: { x: 300, y: 300 },
    },
    {
      id: "rect_002",
      shape: "rectangle",
      label: "课程",
      attributes: ["*课程号", "课程名"],
      position: { x: 820, y: 300 },
    },
    { id: "dia_001", shape: "diamond", label: "选修", attributes: [], position: { x: 560, y: 170 } },
    { id: "ell_001", shape: "ellipse", label: "独立属性", attributes: [], position: { x: 300, y: 560 } },
  ],
  connections: [
    { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "M" },
    { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
  ],
};

const RATIO_ITEMS = [
  ["16:9", 16 / 9],
  ["4:3", 4 / 3],
  ["3:2", 3 / 2],
  ["1:1", 1],
  ["黄金比例", 1.618],
  ["A4 横向", 297 / 210],
  ["A4 纵向", 210 / 297],
];

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1", "--font-render-hinting=none"],
  defaultViewport: null,
});
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await page.goto(URL, { waitUntil: "networkidle0", timeout: 30000 });
await page.waitForFunction(() => window.__erStore && window.__erCanvas, { timeout: 15000 });
await sleep(300);

/* ---------------- 页面内状态快照 ---------------- */
async function state() {
  return page.evaluate(() => {
    const s = window.__erStore;
    const c = window.__erCanvas;
    const vpt = c.viewportTransform ? [...c.viewportTransform] : null;
    const host = document.querySelector(".host");
    const pageObj = c
      .getObjects()
      .find(
        (o) =>
          o.type === "rect" &&
          o.visible &&
          o.fill &&
          typeof o.fill === "object" &&
          !(o.width === 16000 && o.height === 16000),
      );
    const pageBox = pageObj
      ? {
          x: pageObj.left,
          y: pageObj.top,
          w: pageObj.width,
          h: pageObj.height,
          left: pageObj.left,
          top: pageObj.top,
          right: pageObj.left + pageObj.width,
          bottom: pageObj.top + pageObj.height,
        }
      : null;
    const cw = c.getWidth();
    const ch = c.getHeight();
    const pageScreen = pageBox
      ? {
          left: pageBox.x * vpt[0] + vpt[4],
          top: pageBox.y * vpt[3] + vpt[5],
          right: (pageBox.x + pageBox.w) * vpt[0] + vpt[4],
          bottom: (pageBox.y + pageBox.h) * vpt[3] + vpt[5],
        }
      : null;

    const visuals = [];
    for (const o of c.getObjects()) {
      if (o.erKind !== "element" && o.erKind !== "attribute") continue;
      const b = o.getBoundingRect();
      visuals.push({
        kind: o.erKind,
        id: o.erId ?? `${o.erAttrOwner}#${o.erAttrIndex}`,
        left: b.left,
        top: b.top,
        right: b.left + b.width,
        bottom: b.top + b.height,
      });
    }
    const insidePage =
      !!pageBox &&
      visuals.every(
        (b) =>
          b.left >= pageBox.x - 2 &&
          b.top >= pageBox.y - 2 &&
          b.right <= pageBox.x + pageBox.w + 2 &&
          b.bottom <= pageBox.y + pageBox.h + 2,
      );
    const visualScreen = visuals.map((b) => ({
      ...b,
      sleft: b.left * vpt[0] + vpt[4],
      stop: b.top * vpt[3] + vpt[5],
      sright: b.right * vpt[0] + vpt[4],
      sbottom: b.bottom * vpt[3] + vpt[5],
    }));
    const contentScreen = visualScreen.length
      ? {
          left: Math.min(...visualScreen.map((b) => b.sleft)),
          top: Math.min(...visualScreen.map((b) => b.stop)),
          right: Math.max(...visualScreen.map((b) => b.sright)),
          bottom: Math.max(...visualScreen.map((b) => b.sbottom)),
        }
      : null;
    const contentInCanvas =
      !!contentScreen &&
      contentScreen.left >= -1 &&
      contentScreen.top >= -1 &&
      contentScreen.right <= cw + 1 &&
      contentScreen.bottom <= ch + 1;
    const pageFits =
      !!pageScreen &&
      pageScreen.left >= -1 &&
      pageScreen.top >= -1 &&
      pageScreen.right <= cw + 1 &&
      pageScreen.bottom <= ch + 1;
    const pageCentered =
      !!pageScreen &&
      Math.abs((pageScreen.left + pageScreen.right) / 2 - cw / 2) <= 1.5 &&
      Math.abs((pageScreen.top + pageScreen.bottom) / 2 - ch / 2) <= 1.5;

    const labels = [];
    for (const o of c.getObjects()) {
      if (o.type === "text") labels.push(o);
      if (o.type === "group" && Array.isArray(o._objects)) {
        for (const child of o._objects) if (child.type === "text") labels.push(child);
      }
    }
    const elementVisual = c.getObjects().find((o) => o.erKind === "element");
    const elementBody = elementVisual?._objects?.find((o) => o.type !== "text");
    const attrVisual = c.getObjects().find((o) => o.erKind === "attribute");
    const fonts = labels
      .filter((t) => t.visible && t.text)
      .map((t) => ({ text: t.text, size: Number(t.fontSize) || 0, kind: t.erKind || "" }));
    const minFont = fonts.length ? Math.min(...fonts.map((f) => f.size)) : 0;

    return {
      pageRatio: s.pageRatio,
      pageBox,
      pageRatioValue: pageBox ? pageBox.w / pageBox.h : null,
      pageScreen,
      pageFits,
      pageCentered,
      insidePage,
      visualCount: visuals.length,
      contentScreen,
      contentInCanvas,
      zoom: c.getZoom(),
      vpt,
      cw,
      ch,
      host: host ? { w: host.clientWidth, h: host.clientHeight } : null,
      minFont,
      fonts,
      objectScale: [elementVisual, attrVisual]
        .filter(Boolean)
        .flatMap((o) => [o.scaleX, o.scaleY])
        .filter((v) => Math.abs(v - 1) > 1e-6),
      bodyStrokeUniform: elementBody?.strokeUniform,
      attrStrokeUniform: attrVisual?.strokeUniform ?? null,
      ratios: {
        bodyStroke: elementBody?.strokeWidth ?? null,
        bodyFont: elementVisual?._objects?.find((o) => o.type === "text")?.fontSize ?? null,
      },
      positions: s.elements.map((e) => `${e.id}:${e.position.x},${e.position.y}`).join("|"),
      semantics: {
        elements: s.elements.map((e) => ({
          id: e.id,
          shape: e.shape,
          label: e.label,
          attributes: [...e.attributes],
          is_weak: e.is_weak ?? false,
          is_identifying: e.is_identifying ?? false,
        })),
        connections: s.connections.map((c2) => ({
          id: c2.id,
          from: c2.from,
          to: c2.to,
          type: c2.type,
          label: c2.label,
          cardinality: c2.cardinality ?? null,
          mode: c2.mode ?? "smart",
        })),
      },
      counts: { elements: s.elements.length, connections: s.connections.length },
      layoutStats: s.layoutStats ? { ...s.layoutStats } : null,
    };
  });
}

async function panelState(which) {
  return page.evaluate((kind) => {
    const sel = kind === "ratio" ? ".ratio-menu" : ".layout-menu";
    const panel = document.querySelector(sel);
    const host = document.querySelector(".host");
    const chip = document.querySelector(kind === "ratio" ? ".ratio-wrap .chip" : ".layout-wrap .chip");
    const ratioChip = document.querySelector(".ratio-wrap .chip");
    const layoutChip = document.querySelector(".layout-wrap .chip");
    const scroll = panel?.querySelector(".panel-scroll");
    const clone = (r) =>
      r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height } : null;
    const style = panel ? getComputedStyle(panel) : null;
    const scrollStyle = scroll ? getComputedStyle(scroll) : null;
    return {
      exists: !!panel,
      panel: panel ? clone(panel.getBoundingClientRect()) : null,
      chip: chip ? clone(chip.getBoundingClientRect()) : null,
      ratioChip: ratioChip ? clone(ratioChip.getBoundingClientRect()) : null,
      layoutChip: layoutChip ? clone(layoutChip.getBoundingClientRect()) : null,
      host: host ? { w: host.clientWidth, h: host.clientHeight } : null,
      position: style?.position ?? null,
      overflowY: scrollStyle?.overflowY ?? null,
      maxHeight: style?.maxHeight ?? null,
      ratioItems: [...document.querySelectorAll(".ratio-menu .ratio-item")].map((b) => b.textContent.trim()),
      layoutActions: [...document.querySelectorAll(".layout-menu .mact")].map((b) => b.textContent.replace(/\s+/g, " ").trim()),
      closeButtons: [...document.querySelectorAll(`${sel} .panel-close`)].length,
      ratioEntryVisible: !!document.querySelector(".ratio-wrap .chip"),
      layoutEntryVisible: !!document.querySelector(".layout-wrap .chip"),
      panelHasLayoutActions: !!panel?.querySelector(".mact"),
    };
  }, which);
}

function rectsIntersect(a, b) {
  if (!a || !b) return false;
  return a.left < b.right - 0.5 && a.right > b.left + 0.5 && a.top < b.bottom - 0.5 && a.bottom > b.top + 0.5;
}

async function openRatio() {
  if (!(await page.$(".ratio-menu"))) {
    await page.click(".ratio-wrap .chip");
    await page.waitForSelector(".ratio-menu", { timeout: 3000 });
    await sleep(180);
  }
}
async function openLayout() {
  if (!(await page.$(".layout-menu"))) {
    await page.click(".layout-wrap .chip");
    await page.waitForSelector(".layout-menu", { timeout: 3000 });
    await sleep(180);
  }
}
async function clickInPanel(selector, text) {
  const ok = await page.evaluate(
    (sel, needle) => {
      const btn = [...document.querySelectorAll(sel)].find((b) => b.textContent.replace(/\s+/g, " ").includes(needle));
      if (!btn) return false;
      btn.click();
      return true;
    },
    selector,
    text,
  );
  if (!ok) throw new Error(`panel button not found: ${selector} / ${text}`);
  await sleep(420);
}
async function pickRatioUI(label) {
  await openRatio();
  await clickInPanel(".ratio-menu .ratio-item", label);
  await page.waitForFunction(() => !document.querySelector(".ratio-menu"), { timeout: 3000 });
  await sleep(420);
}

/* ---------------- 准备：自由画布 + 固定示例 ---------------- */
await page.evaluate(() => {
  window.__erStore.clearAll();
  window.__erStore.setPageRatio("free", { relayout: false });
});
await sleep(300);
await page.evaluate((d) => window.__erStore.importDiagram(d), DIAGRAM);
await sleep(900);
let before = await state();
check("准备：导入 4 个元素 / 2 条连线", before.counts.elements === 4 && before.counts.connections === 2, JSON.stringify(before.counts));

/* ---------------- 1. 浮层独立性 / 不改变画布与视口 ---------------- */
const zoomBeforeMenu = before.zoom;
const vptBeforeMenu = before.vpt;
const hostBeforeMenu = before.host;

await openRatio();
let ratioPanel = await panelState("ratio");
await page.screenshot({ path: path.join(OUT, "round5-ratio-panel.png") });
check("比例浮层：独立出现且固定定位", ratioPanel.exists && ratioPanel.position === "fixed", JSON.stringify({ position: ratioPanel.position }));
check("比例浮层：不覆盖比例入口", !rectsIntersect(ratioPanel.panel, ratioPanel.chip), JSON.stringify({ panel: ratioPanel.panel, chip: ratioPanel.chip }));
check("比例浮层：包含全部 8 个比例入口", ratioPanel.ratioItems.length === 8, JSON.stringify(ratioPanel.ratioItems));
check("比例浮层：不含自动布局按钮", !ratioPanel.panelHasLayoutActions, JSON.stringify(ratioPanel.layoutActions));
check("比例浮层：有明确关闭按钮", ratioPanel.closeButtons === 1, String(ratioPanel.closeButtons));
check("比例浮层：内容超出时可内部滚动", ratioPanel.overflowY === "auto" && ratioPanel.maxHeight !== "none", JSON.stringify({ overflowY: ratioPanel.overflowY, maxHeight: ratioPanel.maxHeight }));

let afterOpen = await state();
check(
  "比例浮层：不改变画布容器尺寸",
  afterOpen.host.w === hostBeforeMenu.w && afterOpen.host.h === hostBeforeMenu.h && afterOpen.cw === before.cw && afterOpen.ch === before.ch,
  JSON.stringify({ before: hostBeforeMenu, after: afterOpen.host }),
);
check(
  "比例浮层：不改变缩放 / 平移",
  Math.abs(afterOpen.zoom - zoomBeforeMenu) < 1e-9 && JSON.stringify(afterOpen.vpt) === JSON.stringify(vptBeforeMenu),
  JSON.stringify({ before: { z: zoomBeforeMenu, vpt: vptBeforeMenu }, after: { z: afterOpen.zoom, vpt: afterOpen.vpt } }),
);

await page.click(".ratio-menu .panel-close");
await sleep(220);
check("比例浮层：关闭按钮生效", !(await page.$(".ratio-menu")), "");

await openLayout();
let layoutPanel = await panelState("layout");
await page.screenshot({ path: path.join(OUT, "round5-layout-panel.png") });
check("自动布局浮层：独立出现且比例入口仍可见", layoutPanel.exists && layoutPanel.ratioEntryVisible, JSON.stringify({ exists: layoutPanel.exists, ratioEntry: layoutPanel.ratioEntryVisible }));
check(
  "自动布局浮层：不覆盖比例 / 自动布局入口",
  !rectsIntersect(layoutPanel.panel, layoutPanel.ratioChip) && !rectsIntersect(layoutPanel.panel, layoutPanel.layoutChip),
  JSON.stringify({ panel: layoutPanel.panel, ratio: layoutPanel.ratioChip, layout: layoutPanel.layoutChip }),
);
check("自动布局浮层：包含自动适配 / 重新排列 / 撤销", ["自动适配布局", "重新排列", "撤销布局"].every((t) => layoutPanel.layoutActions.some((x) => x.includes(t))), JSON.stringify(layoutPanel.layoutActions));
check("自动布局浮层：有明确关闭按钮", layoutPanel.closeButtons === 1, String(layoutPanel.closeButtons));
const layoutOpenState = await state();
check(
  "自动布局浮层：不改变缩放 / 平移",
  Math.abs(layoutOpenState.zoom - zoomBeforeMenu) < 1e-9 && JSON.stringify(layoutOpenState.vpt) === JSON.stringify(vptBeforeMenu),
  JSON.stringify({ z: layoutOpenState.zoom, vpt: layoutOpenState.vpt }),
);

/* ---------------- 2. 选择 16:9：比例正确、整页可见、图形不被裁切 ---------------- */
const freeBefore169 = await state();
await pickRatioUI("16:9");
let s169 = await state();
await page.screenshot({ path: path.join(OUT, "round5-16-9.png") });
check("16:9：比例正确", s169.pageRatio === "16:9" && Math.abs(s169.pageRatioValue - 16 / 9) < 0.01, JSON.stringify(s169.pageBox));
check("16:9：整个页面装进视口", s169.pageFits && s169.pageCentered, JSON.stringify({ screen: s169.pageScreen, cw: s169.cw, ch: s169.ch }));
check("16:9：所有图形 / 文字在页面内", s169.insidePage, `visuals=${s169.visualCount}`);
check("16:9：切换比例不重排图形（位置不变）", s169.positions === freeBefore169.positions, `${freeBefore169.positions} -> ${s169.positions}`);
check("16:9：文字清晰（≥12px）", s169.minFont >= 12, `minFont=${s169.minFont}`);

/* ---------------- 3. 自动布局：只重排、不改比例 / 视口，可撤销 ---------------- */
const beforeLayout = await state();
await openLayout();
await clickInPanel(".layout-menu .mact", "自动适配布局");
let laid = await state();
await page.screenshot({ path: path.join(OUT, "round5-after-autolayout.png") });
check("自动布局：图形位置确实改变", laid.positions !== beforeLayout.positions, `${beforeLayout.positions} -> ${laid.positions}`);
check("自动布局：画布比例不变", laid.pageRatio === "16:9" && Math.abs(laid.pageRatioValue - 16 / 9) < 0.01, JSON.stringify(laid.pageBox));
check(
  "自动布局：不改变画布宽高",
  !!laid.pageBox &&
    !!beforeLayout.pageBox &&
    Math.abs(laid.pageBox.w - beforeLayout.pageBox.w) <= 1 &&
    Math.abs(laid.pageBox.h - beforeLayout.pageBox.h) <= 1,
  JSON.stringify({ before: beforeLayout.pageBox, after: laid.pageBox }),
);
check("自动布局后：屏幕文字仍清晰（≥11px）", laid.minFont * laid.zoom >= 11, `font=${laid.minFont} zoom=${laid.zoom}`);
check(
  "自动布局：视口缩放 / 平移不被重置",
  Math.abs(laid.zoom - beforeLayout.zoom) < 1e-9 && JSON.stringify(laid.vpt) === JSON.stringify(beforeLayout.vpt),
  JSON.stringify({ before: { z: beforeLayout.zoom, vpt: beforeLayout.vpt }, after: { z: laid.zoom, vpt: laid.vpt } }),
);
check("自动布局：语义数据完全保留", JSON.stringify(laid.semantics) === JSON.stringify(beforeLayout.semantics), "");
check("自动布局：所有图形仍在页面内", laid.insidePage, "");
check("自动布局：无对象级重复缩放", laid.objectScale.length === 0, JSON.stringify(laid.objectScale));

await openLayout();
await clickInPanel(".layout-menu .mact", "撤销布局");
let undone = await state();
check("撤销自动布局：位置完全恢复", undone.positions === beforeLayout.positions, `${laid.positions} -> ${undone.positions}`);
check("撤销自动布局：比例仍为 16:9", undone.pageRatio === "16:9", undone.pageRatio);

// 再执行一次，供后续比例 / 缩放测试使用
await openLayout();
await clickInPanel(".layout-menu .mact", "自动适配布局");
laid = await state();

/* ---------------- 4. 自动布局后仍可切换 4:3 ---------------- */
await pickRatioUI("4:3");
let s43 = await state();
await page.screenshot({ path: path.join(OUT, "round5-4-3.png") });
check("自动布局后切换 4:3：比例正确", s43.pageRatio === "4:3" && Math.abs(s43.pageRatioValue - 4 / 3) < 0.01, JSON.stringify(s43.pageBox));
check("自动布局后切换 4:3：不再次重排图形", s43.positions === laid.positions, `${laid.positions} -> ${s43.positions}`);
check("切换 4:3：整页可见且居中", s43.pageFits && s43.pageCentered, JSON.stringify(s43.pageScreen));
check("切换 4:3：所有图形在页面内", s43.insidePage, "");
check("切换 4:3：文字仍然清晰（≥12px）", s43.minFont >= 12, `minFont=${s43.minFont}`);
check("切换 4:3：屏幕文字仍清晰（≥11px）", s43.minFont * s43.zoom >= 11, `font=${s43.minFont} zoom=${s43.zoom}`);
check("切换 4:3：没有对象级重复缩放", s43.objectScale.length === 0, JSON.stringify(s43.objectScale));

/* ---------------- 5. 缩放一致性：边框 / 连线随文字同步 ---------------- */
check("缩放一致性：图形描边不再 strokeUniform", s43.bodyStrokeUniform === false, String(s43.bodyStrokeUniform));
check("缩放一致性：属性椭圆描边不再 strokeUniform", s43.attrStrokeUniform === false, String(s43.attrStrokeUniform));

const zoomRatio1 = await page.evaluate(() => {
  const c = window.__erCanvas;
  const el = c.getObjects().find((o) => o.erKind === "element");
  const body = el._objects.find((o) => o.type !== "text");
  const text = el._objects.find((o) => o.type === "text");
  const z = c.getZoom();
  return { ratio: (Number(text.fontSize) * z) / (Number(body.strokeWidth) * z), z, font: text.fontSize, stroke: body.strokeWidth };
});
await page.evaluate(() => {
  const c = window.__erCanvas;
  c.setViewportTransform([2, 0, 0, 2, 40, 40]);
  c.requestRenderAll();
});
await sleep(250);
const zoomRatio2 = await page.evaluate(() => {
  const c = window.__erCanvas;
  const el = c.getObjects().find((o) => o.erKind === "element");
  const body = el._objects.find((o) => o.type !== "text");
  const text = el._objects.find((o) => o.type === "text");
  const z = c.getZoom();
  return { ratio: (Number(text.fontSize) * z) / (Number(body.strokeWidth) * z), z, font: text.fontSize, stroke: body.strokeWidth };
});
check(
  "缩放一致性：文字/描边屏幕比例在 100% 与 200% 下一致",
  Math.abs(zoomRatio1.ratio - zoomRatio2.ratio) < 1e-6 && zoomRatio2.z > zoomRatio1.z,
  JSON.stringify({ at1: zoomRatio1, at2: zoomRatio2 }),
);

/* ---------------- 6. 适应画布 vs 适应全部图形 ---------------- */
await page.evaluate(() => document.querySelector('.zoom button[aria-label="适应画布"]')?.click());
await sleep(350);
const fitPageState = await state();
check("适应画布：整页装进视口并居中", fitPageState.pageFits && fitPageState.pageCentered, JSON.stringify({ zoom: fitPageState.zoom, screen: fitPageState.pageScreen }));
const pageFitZoom = fitPageState.zoom;

await page.evaluate(() => document.querySelector('.zoom button[aria-label="适应全部图形"]')?.click());
await sleep(350);
const fitAllState = await state();
await page.screenshot({ path: path.join(OUT, "round5-fit-all.png") });
check("适应全部图形：所有图形装进视口", fitAllState.contentInCanvas, JSON.stringify(fitAllState.contentScreen));
check(
  "适应画布 / 适应全部图形：是两个不同结果",
  fitAllState.zoom > pageFitZoom + 0.005 && fitAllState.contentInCanvas,
  JSON.stringify({ pageFitZoom, contentZoom: fitAllState.zoom, pageFitsAfterContentFit: fitAllState.pageFits }),
);

/* ---------------- 7. 连续切换比例：不出现画布错位 ---------------- */
const stateBeforeRatios = await state();
const semanticsBeforeRatios = stateBeforeRatios.semantics;
const positionsBeforeRatios = stateBeforeRatios.positions;
for (const [label, value] of RATIO_ITEMS) {
  await pickRatioUI(label);
  const st = await state();
  check(
    `${label}：比例正确、整页可见且居中`,
    st.pageRatio !== "free" && Math.abs(st.pageRatioValue - value) < 0.01 && st.pageFits && st.pageCentered,
    JSON.stringify({ box: st.pageBox, screen: st.pageScreen }),
  );
  check(`${label}：所有图形在页面内`, st.insidePage, `visuals=${st.visualCount}`);
  check(`${label}：语义数据不变`, JSON.stringify(st.semantics) === JSON.stringify(semanticsBeforeRatios), "");
  check(`${label}：连续切换不移动图形`, st.positions === positionsBeforeRatios, "");
  check(`${label}：画布容器尺寸不变`, st.host.w === hostBeforeMenu.w && st.host.h === hostBeforeMenu.h, JSON.stringify(st.host));
  if (["1:1", "A4 纵向"].includes(label)) {
    const safe = label.replace(/[\\/:*?"<>|\s]+/g, "");
    await page.screenshot({ path: path.join(OUT, `round5-ratio-${safe}.png`) });
  }
}

// 回到 16:9，并确认自由画布没有页面
await pickRatioUI("16:9");
await pickRatioUI("自由");
let freeState = await state();
check(
  "自由画布：不绘制页面，但图形保留",
  freeState.pageBox === null && freeState.visualCount === 9 && freeState.pageRatio === "free",
  JSON.stringify({ page: freeState.pageBox, visual: freeState.visualCount, ratio: freeState.pageRatio }),
);
await pickRatioUI("16:9");

/* ---------------- 8. 鼠标滚轮缩放 / 拖动平移 ---------------- */
await page.evaluate(() => document.querySelector('.zoom button[aria-label="适应画布"]')?.click());
await sleep(300);
const panStart = await state();
const hostRect = await page.evaluate(() => {
  const r = document.querySelector(".host").getBoundingClientRect();
  return { left: r.left, top: r.top, w: r.width, h: r.height };
});
await page.mouse.move(hostRect.left + hostRect.w / 2, hostRect.top + hostRect.h / 2);
const wheelBefore = (await state()).zoom;
await page.mouse.wheel({ deltaY: -240 });
await sleep(300);
const wheelAfter = (await state()).zoom;
check("鼠标滚轮：向上滚动放大", wheelAfter > wheelBefore + 1e-6, `${wheelBefore} -> ${wheelAfter}`);

const shiftBefore = (await state()).vpt[4];
await page.keyboard.down("Shift");
await page.mouse.wheel({ deltaY: -200 });
await page.keyboard.up("Shift");
await sleep(250);
const shiftAfter = (await state()).vpt[4];
check("Shift+滚轮：横向平移（滚轮不再是唯一平移方式）", Math.abs(shiftAfter - shiftBefore) > 1, `${shiftBefore} -> ${shiftAfter}`);

await page.evaluate(() => document.querySelector('.zoom button[aria-label="适应画布"]')?.click());
await sleep(250);
const dragBefore = (await state()).vpt;
const empty = { x: hostRect.left + 24, y: hostRect.top + 18 };
await page.mouse.move(empty.x, empty.y);
await page.mouse.down();
await page.mouse.move(empty.x + 90, empty.y + 44, { steps: 6 });
await page.mouse.up();
await sleep(250);
const dragAfter = (await state()).vpt;
check(
  "拖动空白处：平移视口",
  Math.abs(dragAfter[4] - dragBefore[4]) > 10 || Math.abs(dragAfter[5] - dragBefore[5]) > 10,
  `${JSON.stringify(dragBefore)} -> ${JSON.stringify(dragAfter)}`,
);
void panStart;

/* ---------------- 9. 导入 / 导出 / 数据交互保持 ---------------- */
// 通过 JSON 字符串往返，等价于真实「导出文件 → 导入文件」，并避免宿主序列化响应式代理
const exportedJson = await page.evaluate(() => JSON.stringify(window.__erStore.exportDiagram()));
const exported = JSON.parse(exportedJson);
check(
  "导出：保留实体 / 属性 / 联系 / 基数与排版字段",
  exported.elements.length === 4 &&
    exported.connections.length === 2 &&
    exported.elements.every((e) => "layout_scale" in e && "attr_offsets" in e) &&
    exported.elements.some((e) => Object.keys(e.attr_offsets ?? {}).length > 0) &&
    exported.connections.some((c) => c.cardinality === "M"),
  JSON.stringify({ elements: exported.elements.length, connections: exported.connections.length }),
);
await page.evaluate((raw) => window.__erStore.importDiagram(JSON.parse(raw)), exportedJson);
await sleep(900);
const reimported = await state();
check(
  "导入：实体 / 属性 / 连线 / 基数完整恢复",
  reimported.counts.elements === 4 &&
    reimported.counts.connections === 2 &&
    JSON.stringify(reimported.semantics.connections) === JSON.stringify(exported.connections.map((c) => ({
      id: c.id,
      from: c.from,
      to: c.to,
      type: c.type,
      label: c.label,
      cardinality: c.cardinality ?? null,
      mode: c.mode ?? "smart",
    }))),
  JSON.stringify(reimported.counts),
);
check(
  "导入后：比例仍为当前选择且整页可见",
  reimported.pageRatio === "16:9" && reimported.insidePage,
  JSON.stringify({ ratio: reimported.pageRatio, page: reimported.pageBox, inside: reimported.insidePage, visuals: reimported.visualCount }),
);

/* ---------------- 10. Esc 关闭浮层 ---------------- */
await openRatio();
await page.keyboard.press("Escape");
await sleep(220);
check("Esc：关闭比例浮层", !(await page.$(".ratio-menu")), "");
await openLayout();
await page.keyboard.press("Escape");
await sleep(220);
check("Esc：关闭自动布局浮层", !(await page.$(".layout-menu")), "");

/* ---------------- 汇总 ---------------- */
check("运行期间无控制台错误", errors.length === 0, errors.slice(0, 6).join(" | "));

const passed = results.filter((r) => r.pass).length;
console.log(`\nSUMMARY ${passed}/${results.length} passed`);
if (passed !== results.length) {
  console.log("FAILED:");
  for (const r of results.filter((r) => !r.pass)) console.log(`  - ${r.name} ${r.detail}`);
}
fs.writeFileSync(path.join(OUT, "round5-report.json"), JSON.stringify({ results, errors }, null, 2));
await browser.close();
process.exit(passed === results.length ? 0 : 1);
