#!/usr/bin/env node
/**
 * Automated screenshot capture for UI diffing. No agent driving the browser —
 * headless Chromium renders every route and writes PNGs + a manifest.
 *
 *   node tools/heroui-migration/visual/shoot.mjs --label v2
 *   node tools/heroui-migration/visual/shoot.mjs --label v3 --base http://localhost:3001
 *   node tools/heroui-migration/visual/shoot.mjs --label v2 --only /,/pricing --workers 6
 *
 * Output: tools/heroui-migration/shots/<label>/{desktop,mobile}/<route>.png
 *         tools/heroui-migration/shots/<label>/manifest.json
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Reuse the app's already-installed Playwright instead of adding a second copy.
const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, "..", "..", "..", "apps", "web");
const { chromium } = createRequire(join(APP, "package.json"))("@playwright/test");
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";

const argv = process.argv.slice(2);
const arg = (n, d = null) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};

const LABEL = arg("label");
if (!LABEL) {
  console.error("--label is required (e.g. --label v2)");
  process.exit(1);
}
const BASE = arg("base", process.env.WEB_BASE_URL || "http://localhost:3000");
const ONLY = arg("only") ? arg("only").split(",").map((s) => s.trim()) : null;
const WORKERS = Number(arg("workers", 4));
const OUT = join(process.cwd(), "tools/heroui-migration/shots", LABEL);
const STORAGE = arg("storage-state");

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 },
];

const ROUTES_FILE = arg("routes", "tools/heroui-migration/routes.json");
const routes = JSON.parse(readFileSync(ROUTES_FILE, "utf8")).filter(
  (r) => !ONLY || ONLY.some((o) => r === o),
);

const slug = (route) => (route === "/" ? "_root" : route.replace(/^\//, "").replace(/\//g, "_")) || "_root";

async function run() {
  for (const vp of VIEWPORTS) mkdirSync(join(OUT, vp.name), { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  const queue = [...routes];
  let done = 0;

  const worker = async () => {
    const vp = VIEWPORTS[0];
    const ctxD = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, storageState: STORAGE || undefined, reducedMotion: 'reduce' });
    const ctxM = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, storageState: STORAGE || undefined, reducedMotion: 'reduce' });
    const pd = await ctxD.newPage();
    const pm = await ctxM.newPage();
    for (const p of [pd, pm]) {
      await p.route("**/*", (r) => {
        const t = r.request().resourceType();
        // block video/analytics: pure noise for visual diffs
        if (["media", "websocket", "eventsource"].includes(t)) return r.abort();
        return r.continue();
      });
    }
    while (queue.length) {
      const route = queue.shift();
      const entry = { route, shots: {}, errors: [], ms: 0 };
      const t0 = Date.now();
      for (const [name, page] of [["desktop", pd], ["mobile", pm]]) {
        try {
          await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 45_000 });
          await page.addStyleTag({
            content: "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important} [class*=sbi-],.sbi-anim,h1,h2{filter:none!important;opacity:1!important}",
          });
          // Trigger lazy images/fonts across the whole document before shooting, then settle.
          await page.evaluate(async () => {
            const step = Math.floor(window.innerHeight * 0.9);
            for (let y = 0; y < document.body.scrollHeight; y += step) {
              window.scrollTo(0, y);
              await new Promise((r) => setTimeout(r, 60));
            }
            window.scrollTo(0, 0);
            await new Promise((r) => setTimeout(r, 120));
          });
          await page.evaluate(async () => {
            const imgs = [...document.images].filter((i) => !i.complete || i.naturalWidth === 0);
            await Promise.race([
              Promise.all(imgs.map((i) => new Promise((r) => { i.onload = r; i.onerror = r; }))),
              new Promise((r) => setTimeout(r, 4000)),
            ]);
            if (document.fonts?.ready) await document.fonts.ready;
          });
          await page.waitForTimeout(350);
          const file = join(OUT, name, `${slug(route)}.png`);
          await page.screenshot({ path: file, fullPage: true });
          entry.shots[name] = { path: `shots/${LABEL}/${name}/${slug(route)}.png`, width: 0, height: 0 };
        } catch (e) {
          entry.errors.push(`${name}: ${String(e.message).split("\n")[0]}`);
        }
      }
      entry.ms = Date.now() - t0;
      results.push(entry);
      done++;
      process.stdout.write(`\r  ${done}/${routes.length}  ${route.padEnd(40)}`);
    }
    await ctxD.close();
    await ctxM.close();
  };

  await Promise.all(Array.from({ length: Math.min(WORKERS, routes.length) }, worker));
  await browser.close();

  const manifest = {
    label: LABEL,
    base: BASE,
    capturedAt: new Date().toISOString(),
    viewports: VIEWPORTS.map((v) => v.name),
    routes: results.sort((a, b) => a.route.localeCompare(b.route)),
  };
  writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  const failed = results.filter((r) => r.errors.length);
  console.log(`\n  ${results.length - failed.length}/${results.length} routes captured -> ${OUT}`);
  if (failed.length) {
    console.log(`  ${failed.length} failed:`);
    for (const f of failed.slice(0, 8)) console.log(`    ${f.route}  ${f.errors[0]}`);
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
