/**
 * 第四轮：智能页面比例 / 自动布局回归。
 * 运行前：vite dev（5173）与 mock ws（8000）已启动。
 * 用法：node scripts/layout-regression.mjs
 */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";
import { cases } from "./layout-cases.mjs";

const CHROME =
  process.env.CHROME_PATH ||
  path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe");
const URL = process.env.APP_URL || "http://127.0.0.1:5173/";
const OUT = path.resolve(".impeccable/review");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const RATIOS = ["16:9", "4:3", "1:1", "a4", "a4p"];
const RATIO_LABEL = { "16:9": "16:9", "4:3": "4:3", "1:1": "1:1", a4: "A4 横向", a4p: "A4 纵向" };

const results = [];

function check(name, pass, detail = "") {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

function semSnapshot() {
  const s = window.__erStore;
  return {
    elements: s.elements.map((e) => ({
      id: e.id,
      shape: e.shape,
      label: e.label,
      attributes: [...e.attributes],
      is_weak: e.is_weak ?? false,
      is_identifying: e.is_identifying ?? false,
      attr_style: e.attr_style ?? {},
    })),
    connections: s.connections.map((c) => ({
      id: c.id,
      from: c.from,
      to: c.to,
      type: c.type,
      label: c.label,
      cardinality: c.cardinality ?? null,
    })),
  };
}

function inspectInPage() {
  const plain = (v) => JSON.parse(JSON.stringify(v));
  const s = window.__erStore;
  const c = window.__erCanvas;
  const objs = c.getObjects();
  const coreEls = objs.filter((o) => o.erKind === "element");
  const attrEls = objs.filter((o) => o.erKind === "attribute");
  const textNodes = [];
  for (const o of objs) {
    if (o.type === "text") textNodes.push(o);
    if (o.type === "group" && Array.isArray(o._objects)) {
      for (const child of o._objects) if (child.type === "text") textNodes.push(child);
    }
  }
  const boxOf = (o) => {
    const b = o.getBoundingRect();
    return { left: b.left, top: b.top, right: b.left + b.width, bottom: b.top + b.height, w: b.width, h: b.height };
  };
  const boxes = [];
  for (const o of coreEls) boxes.push({ kind: "core", ...boxOf(o), id: o.erId });
  for (const o of attrEls) boxes.push({ kind: "attr", ...boxOf(o), id: `${o.erAttrOwner}#${o.erAttrIndex}` });

  // 用真实形状（矩形 / 椭圆 / 菱形）判断重叠，避免 AABB 在斜向属性上误报
  const shapeById = new Map(s.elements.map((e) => [e.id, e]));
  const shapes = [];
  for (const o of coreEls) {
    const e = shapeById.get(o.erId);
    if (!e) continue;
    const b = boxOf(o);
    shapes.push({
      id: o.erId,
      shape: e.shape,
      cx: e.position.x,
      cy: e.position.y,
      w: b.w,
      h: b.h,
      box: b,
    });
  }
  for (const o of attrEls) {
    const b = boxOf(o);
    shapes.push({
      id: `${o.erAttrOwner}#${o.erAttrIndex}`,
      shape: "ellipse",
      cx: (b.left + b.right) / 2,
      cy: (b.top + b.bottom) / 2,
      w: b.w,
      h: b.h,
      box: b,
    });
  }
  const contains = (shape, x, y) => {
    const hw = Math.max(1, shape.w / 2 - 1.5);
    const hh = Math.max(1, shape.h / 2 - 1.5);
    const dx = (x - shape.cx) / hw;
    const dy = (y - shape.cy) / hh;
    if (shape.shape === "rectangle") return Math.abs(dx) <= 1 && Math.abs(dy) <= 1;
    if (shape.shape === "ellipse") return dx * dx + dy * dy <= 1;
    return Math.abs(dx) + Math.abs(dy) <= 1;
  };
  const samples = (shape) => {
    const pts = [{ x: shape.cx, y: shape.cy }];
    const hw = Math.max(1, shape.w / 2 - 1.5);
    const hh = Math.max(1, shape.h / 2 - 1.5);
    if (shape.shape === "rectangle") {
      pts.push(
        { x: shape.cx - hw, y: shape.cy - hh },
        { x: shape.cx + hw, y: shape.cy - hh },
        { x: shape.cx + hw, y: shape.cy + hh },
        { x: shape.cx - hw, y: shape.cy + hh },
      );
    } else if (shape.shape === "ellipse") {
      for (let k = 0; k < 32; k++) {
        const a = (k / 32) * Math.PI * 2;
        pts.push({ x: shape.cx + Math.cos(a) * hw, y: shape.cy + Math.sin(a) * hh });
      }
    } else {
      pts.push(
        { x: shape.cx, y: shape.cy - hh },
        { x: shape.cx + hw, y: shape.cy },
        { x: shape.cx, y: shape.cy + hh },
        { x: shape.cx - hw, y: shape.cy },
      );
    }
    return pts;
  };
  const shapesOverlap = (a, b) => {
    for (const p of samples(a)) if (contains(b, p.x, p.y)) return true;
    for (const p of samples(b)) if (contains(a, p.x, p.y)) return true;
    return false;
  };
  let overlaps = 0;
  let aabbOverlaps = 0;
  const overlapPairs = [];
  for (let i = 0; i < shapes.length; i++) {
    for (let j = i + 1; j < shapes.length; j++) {
      const ox = Math.min(shapes[i].box.right, shapes[j].box.right) - Math.max(shapes[i].box.left, shapes[j].box.left);
      const oy = Math.min(shapes[i].box.bottom, shapes[j].box.bottom) - Math.max(shapes[i].box.top, shapes[j].box.top);
      if (ox <= 0 || oy <= 0) continue;
      aabbOverlaps += 1;
      if (shapesOverlap(shapes[i], shapes[j])) {
        overlaps += 1;
        if (overlapPairs.length < 6) overlapPairs.push([shapes[i].id, shapes[j].id, Math.round(ox), Math.round(oy)]);
      }
    }
  }

  const page = s.pageBox;
  const insidePage =
    !!page &&
    boxes.every(
      (b) =>
        b.left >= page.x - 1 &&
        b.top >= page.y - 1 &&
        b.right <= page.x + page.w + 1 &&
        b.bottom <= page.y + page.h + 1,
    );

  const attrSizes = {};
  const textOutside = [];
  for (const t of textNodes) {
    if (t.erKind === "attrLabel") {
      attrSizes[Math.round(t.fontSize * 10) / 10] = (attrSizes[Math.round(t.fontSize * 10) / 10] ?? 0) + 1;
      const e = attrEls.find(
        (x) => x.erAttrOwner === t.erAttrOwner && x.erAttrIndex === t.erAttrIndex,
      );
      if (e) {
        const tb = t.getBoundingRect();
        const eb = e.getBoundingRect();
        if (
          tb.left < eb.left - 1 ||
          tb.top < eb.top - 1 ||
          tb.left + tb.width > eb.left + eb.width + 1 ||
          tb.top + tb.height > eb.top + eb.height + 1
        ) {
          textOutside.push(t.text);
        }
      }
    }
  }
  const ellipsis = textNodes.filter((t) => /…|\.\.\./.test(t.text ?? "")).map((t) => t.text);
  const objectScale = objs
    .filter((o) => o.erKind === "element" || o.erKind === "attribute")
    .map((o) => [o.scaleX, o.scaleY])
    .filter(([x, y]) => Math.abs(x - 1) > 1e-6 || Math.abs(y - 1) > 1e-6);

  const fontAudit = textNodes.map((t) => ({
    text: t.text,
    fontSize: t.fontSize,
    kind: t.erKind ?? "",
    erId: t.erId ?? "",
    visible: t.visible,
  }));
  const r20Rows = s.allIssues.filter((row) => row.issue.rule_id === "R20");
  const r20 = r20Rows.length;
  const r20Messages = r20Rows.map((row) => row.issue.message);
  const ownerLines = objs.filter(
    (o) => o.type === "line" && Math.abs(Number(o.opacity ?? 1) - 0.45) < 1e-6,
  ).length;
  const standaloneAttrs = s.elements.filter(
    (e) =>
      e.shape === "ellipse" &&
      !s.connections.some((c) => c.mode !== "free" && (c.from === e.id || c.to === e.id)),
  ).length;
  const connLines = objs.filter((o) => o.erKind === "connection").length;
  const cardTexts = textNodes.filter((t) => t.erKind === "card").length;
  const cardVisible = objs.filter((o) => o.type === "text" && o.erId === undefined && o.text && /^[1NMP]$/.test(o.text) && o.visible).length;

  const cw = c.getWidth();
  const ch = c.getHeight();
  const zoom = c.getZoom();
  const vpt = c.viewportTransform;
  const pageScreen = page
    ? {
        left: page.x * vpt[0] + vpt[4],
        top: page.y * vpt[3] + vpt[5],
        right: (page.x + page.w) * vpt[0] + vpt[4],
        bottom: (page.y + page.h) * vpt[3] + vpt[5],
      }
    : null;
  const pageFits =
    !!pageScreen &&
    pageScreen.left >= -1 &&
    pageScreen.top >= -1 &&
    pageScreen.right <= cw + 1 &&
    pageScreen.bottom <= ch + 1;

  return plain({
    page,
    stats: s.layoutStats,
    elementCount: s.elements.length,
    connectionCount: s.connections.length,
    coreCount: coreEls.length,
    attrCount: attrEls.length,
    expectedAttrCount:
      s.elements.reduce((n, e) => n + e.attributes.length, 0),
    textCount: textNodes.length,
    attrSizes,
    textOutside,
    ellipsis,
    objectScale,
    overlaps,
    aabbOverlaps,
    overlapPairs,
    insidePage,
    connLines,
    cardTexts,
    cardVisible,
    ownerLines,
    standaloneAttrs,
    r20,
    r20Messages,
    fontAudit,
    zoom,
    pageFits,
    pageScreen,
    cw,
    ch,
    elements: s.elements.map((e) => ({
      id: e.id,
      shape: e.shape,
      pos: { ...e.position },
      size: e.size ? { ...e.size } : null,
      scale: e.layout_scale,
      label: e.label,
      attributes: [...e.attributes],
    })),
    connections: s.connections.map((c2) => ({ ...c2 })),
    positions: s.elements.map((e) => `${e.id}:${e.position.x},${e.position.y}`).join("|"),
  });
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1", "--font-render-hinting=none"],
  defaultViewport: null,
});
const page = await browser.newPage();
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
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await page.goto(URL, { waitUntil: "networkidle0", timeout: 30000 });
await page.waitForFunction(() => window.__erStore && window.__erCanvas, { timeout: 15000 });
await sleep(300);

for (const testCase of cases) {
  console.log(`\n=== ${testCase.name} ===`);
  await page.evaluate((d) => window.__erStore.importDiagram(d), testCase.diagram);
  await sleep(450);
  const semanticBefore = await page.evaluate(semSnapshot);

  for (const ratio of RATIOS) {
    await page.evaluate((r) => window.__erStore.setPageRatio(r, { relayout: true }), ratio);
    await sleep(360);
    const info = await page.evaluate(inspectInPage);
    const semanticAfter = await page.evaluate(semSnapshot);
    const tag = `${testCase.id}-${ratio}`;

    check(`${tag} 语义数据保持不变`, JSON.stringify(semanticBefore) === JSON.stringify(semanticAfter));
    check(
      `${tag} 页面比例正确`,
      !!info.page && Math.abs(info.page.w / info.page.h - ({ "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1, a4: 297 / 210, a4p: 210 / 297 })[ratio]) < 0.01,
      JSON.stringify(info.page),
    );
    check(
      `${tag} 图形 / 属性 / 连线完整`,
      info.coreCount === info.elementCount &&
        info.attrCount >= info.expectedAttrCount &&
        info.connectionCount === testCase.diagram.connections.length,
      JSON.stringify({
        core: info.coreCount,
        elements: info.elementCount,
        attrs: info.attrCount,
        expected: info.expectedAttrCount,
        conns: info.connectionCount,
      }),
    );
    check(`${tag} 内容全部在页面内`, info.insidePage, JSON.stringify(info.page));
    check(`${tag} 无图形 / 属性重叠`, info.overlaps === 0, JSON.stringify(info.overlapPairs));
    check(`${tag} 无 R20 连线压属性`, info.r20 === 0, `R20=${info.r20} ${JSON.stringify(info.r20Messages)}`);
    check(`${tag} 文字无省略号`, info.ellipsis.length === 0, JSON.stringify(info.ellipsis));
    check(`${tag} 属性文字在椭圆内`, info.textOutside.length === 0, JSON.stringify(info.textOutside.slice(0, 4)));
    check(
      `${tag} 字号统一且 ≥ 12px`,
      Object.keys(info.attrSizes).length === 1 && Number(Object.keys(info.attrSizes)[0]) >= 12,
      JSON.stringify(info.attrSizes),
    );
    check(`${tag} 没有对象级重复缩放`, info.objectScale.length === 0, JSON.stringify(info.objectScale.slice(0, 3)));
    const S = info.stats.scale;
    const shapeById = new Map(info.elements.map((e) => [e.id, e.shape]));
    const badFonts = info.fontAudit
      .map((t) => {
        let expected = null;
        if (t.kind === "attrLabel") expected = 14 * S;
        else if (t.kind === "elementLabel") expected = (shapeById.get(t.erId) === "rectangle" ? 15 : 14) * S;
        else if (t.visible && /^[1NMP]$/.test(t.text ?? "")) expected = 13 * S;
        if (expected === null) return null;
        return { ...t, expected };
      })
      .filter((t) => t && (Math.abs(t.fontSize - t.expected) > 0.3 || t.fontSize < 12));
    check(
      `${tag} 字号与内容缩放统一且 ≥ 12px`,
      badFonts.length === 0,
      JSON.stringify(badFonts.slice(0, 3)),
    );
    check(
      `${tag} 页面得到合理利用`,
      info.stats && info.stats.fill >= 0.4,
      info.stats ? `fill=${info.stats.fill.toFixed(2)}` : "no stats",
    );
    check(`${tag} 页面装进视口`, info.pageFits, JSON.stringify(info.pageScreen));
    check(
      `${tag} 连线 / 基数渲染`,
      info.connLines >= testCase.diagram.connections.length &&
        info.cardVisible >= testCase.diagram.connections.filter((c) => c.cardinality).length,
      JSON.stringify({ lines: info.connLines, cards: info.cardVisible, cardTexts: info.cardTexts }),
    );
    check(
      `${tag} 独立属性椭圆有归属线`,
      info.ownerLines >= info.standaloneAttrs,
      JSON.stringify({ ownerLines: info.ownerLines, standaloneAttrs: info.standaloneAttrs }),
    );

    if (["16:9", "a4p"].includes(ratio)) {
      await page.screenshot({ path: path.join(OUT, `layout-${tag}.png`) });
    }
    if (ratio === "a4p") {
      // 「撤销布局」回退到当前用例上一轮布局，语义数据仍应保持不变
      const beforeUndo = info.positions;
      const undone = await page.evaluate(() => window.__erStore.undoLayout());
      await sleep(350);
      const afterUndo = await page.evaluate(() =>
        window.__erStore.elements.map((e) => `${e.id}:${e.position.x},${e.position.y}`).join("|"),
      );
      check(`${tag} 撤销布局回到上一版位置`, undone === true && afterUndo !== beforeUndo, `${beforeUndo} -> ${afterUndo}`);
      // 回到最后一个比例，便于截图 / 后续断言
      await page.evaluate((r) => window.__erStore.setPageRatio(r, { relayout: true }), ratio);
      await sleep(300);
    }
  }
}

// 导出 / 导入保留本地排版字段（不进入后端协议）
const persistedLayout = await page.evaluate(() => {
  const s = window.__erStore;
  // 页面内先序列化：Pinia 的响应式 Proxy 直接返回给宿主时可能被序列化成 {}
  const plain = (v) => JSON.parse(JSON.stringify(v ?? null));
  const exported = s.exportDiagram();
  const before = {
    scale: exported.elements[0]?.layout_scale,
    size: plain(exported.elements[0]?.size),
    offsets: plain(exported.elements[0]?.attr_offsets),
  };
  s.importDiagram(exported);
  return {
    before,
    after: {
      scale: s.elements[0]?.layout_scale,
      size: plain(s.elements[0]?.size),
      offsets: plain(s.elements[0]?.attr_offsets),
    },
  };
});
check(
  "导出 / 导入保留 layout_scale / size / attr_offsets",
  typeof persistedLayout.before.scale === "number" &&
    persistedLayout.before.scale === persistedLayout.after.scale &&
    JSON.stringify(persistedLayout.before.size) === JSON.stringify(persistedLayout.after.size) &&
    JSON.stringify(persistedLayout.before.offsets) === JSON.stringify(persistedLayout.after.offsets),
  JSON.stringify(persistedLayout),
);

// 后端协议报文里绝不能出现本地排版字段
await page.evaluate(() => window.__erStore.batchCheck());
await sleep(700);
const protocolReport = await page.evaluate(() => {
  const bad = [];
  for (const raw of window.__wsSent || []) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      continue;
    }
    const text = JSON.stringify(msg);
    if (/layout_scale|attr_offsets|attr_style|"size"|is_identifying|free_end/.test(text)) {
      bad.push(text.slice(0, 180));
    }
  }
  return { bad, count: (window.__wsSent || []).length };
});
check(
  "本地排版字段不进入后端报文",
  protocolReport.bad.length === 0,
  JSON.stringify(protocolReport.bad.slice(0, 2)),
);

check("无控制台错误", errors.length === 0, errors.slice(0, 5).join(" | "));

console.log("\nSUMMARY");
for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}\t${r.name}`);
const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
await browser.close();
process.exit(failed.length ? 1 : 0);

