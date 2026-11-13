/** 干净截图：node scripts/layout-shots.mjs */
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";

const CHROME =
  process.env.CHROME_PATH ||
  path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe");
const OUT = path.resolve(".impeccable/review");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const shots = (process.env.SHOTS || "c1:16:9,c2:a4p,c3:16:9,c4:16:9,c4:a4p,c5:a4p,c6:16:9,c6:a4p").split(",");
const module = await import("./layout-cases.mjs");
const cases = module.cases;

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1", "--font-render-hinting=none"],
  defaultViewport: null,
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await page.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle0" });
await page.waitForFunction(() => window.__erStore && window.__erCanvas);

for (const spec of shots) {
  const [id, ...ratioParts] = spec.split(":");
  const ratio = ratioParts.join(":");
  const testCase = cases.find((c) => c.id === id || c.id.startsWith(`${id}-`));
  if (!testCase) continue;
  await page.evaluate((d) => window.__erStore.importDiagram(d), testCase.diagram);
  await sleep(350);
  await page.evaluate((r) => window.__erStore.setPageRatio(r, { relayout: true }), ratio);
  await sleep(700);
  // 清掉通知，避免遮挡页面
  await page.evaluate(() => {
    document.querySelectorAll(".toasts .toast").forEach((el) => el.remove());
  });
  await sleep(120);
  const clean = ratio.replace(":", "-");
  await page.screenshot({ path: path.join(OUT, `clean-${id}-${clean}.png`) });
  const meta = await page.evaluate(() => {
    const plain = (v) => JSON.parse(JSON.stringify(v));
    return {
      page: plain(window.__erStore.pageBox),
      stats: plain(window.__erStore.layoutStats),
      zoom: window.__erCanvas.getZoom(),
    };
  });
  console.log("shot", id, ratio, JSON.stringify(meta));
}
await browser.close();
