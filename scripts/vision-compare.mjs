#!/usr/bin/env node
/**
 * vision-compare.mjs — Expo MCP + Vision comparison pipeline
 *
 * Reusable script for taking screenshots (web via Playwright, native via
 * simctl/adb/expo-mcp fallback) and feeding them to a visual diff + vision LLM.
 *
 * Usage:
 *   node scripts/vision-compare.mjs --web ./screenshots/web-c.png --native ./screenshots/native-c.png --out ./screenshots/diff-c.png --threshold 0.1 --vision
 *   node scripts/vision-compare.mjs --all-routes --web-base http://localhost:3000 --platform ios --threshold 0.12 --vision
 *   node scripts/vision-compare.mjs --all-routes --strict  # CI: exit 1 on FLAG/BLOCK
 *
 * Env:
 *   OPENAI_API_KEY / ANTHROPIC_API_KEY  — for --vision
 *   WEB_BASE_URL, EXPO_DEV_URL, PLATFORM, WEB_PORT
 *
 * Deps (pnpm add -D pixelmatch pngjs sharp playwright):
 *   pixelmatch@^7.2.0, pngjs@^7.0.0, sharp@^0.33.5, playwright@^1.62.1
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync, spawnSync } from "node:child_process";

// Lazy optional deps — so --help works even if not installed
let pixelmatch, PNG, sharp;
async function loadImageDeps() {
  if (pixelmatch) return;
  try {
    const pm = await import("pixelmatch");
    pixelmatch = pm.default ?? pm;
    const pngjs = await import("pngjs");
    PNG = pngjs.PNG ?? pngjs.default?.PNG ?? pngjs.default;
    sharp = (await import("sharp")).default;
  } catch (e) {
    console.error(
      "Missing image deps. Install:\n  pnpm add -D pixelmatch pngjs sharp\nError: " + e.message
    );
    process.exit(2);
  }
}

// ── CLI args ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
function getArg(name, fallback = undefined) {
  const idx = args.indexOf(name);
  if (idx === -1) return fallback;
  const next = args[idx + 1];
  if (!next || next.startsWith("--")) return true;
  return next;
}
function hasFlag(name) { return args.includes(name); }

const HELP = `
vision-compare.mjs — Web vs Native visual parity

Flags:
  --web <path>            Existing web screenshot PNG (skips Playwright capture)
  --native <path>         Existing native screenshot PNG (skips simctl/adb capture)
  --out <path>            Diff output PNG (default: ./screenshots/diff.png)
  --threshold <0-1>       pixelmatch threshold (default: 0.1). 0.1=strict, 0.25=lenient
  --web-base <url>        Web base URL for --all-routes (default: http://localhost:3000)
  --platform <ios|android> Native platform (default: ios, env PLATFORM)
  --route <path>          Single route to capture (e.g., /c, /todos). With --web/--native ignored.
  --all-routes            Capture all routes from expo-router sitemap
  --output-dir <dir>      Output dir for --all-routes (default: ./screenshots)
  --vision                Also call vision LLM (needs OPENAI_API_KEY or ANTHROPIC_API_KEY)
  --vision-model <id>     Override vision model (default: gpt-4o or claude-sonnet-4)
  --strict                Exit 1 if any route is FLAG/BLOCK or diffRatio > threshold
  --width <px>            Normalize width (default: 390)
  --height <px>           Normalize height (default: 844)
  --help                  Show this help

Examples:
  node scripts/vision-compare.mjs --web ./web.png --native ./native.png --out ./diff.png --threshold 0.1 --vision
  node scripts/vision-compare.mjs --all-routes --web-base http://localhost:3000 --platform ios --threshold 0.12 --vision
  node scripts/vision-compare.mjs --route /c --web-base http://localhost:3000 --platform ios --vision
`.trim();

if (hasFlag("--help") || hasFlag("-h")) { console.log(HELP); process.exit(0); }

// ── Config ────────────────────────────────────────────────────────────────
const threshold = parseFloat(getArg("--threshold", "0.1"));
const webBase = getArg("--web-base", process.env.WEB_BASE_URL || "http://localhost:3000");
const platform = getArg("--platform", process.env.PLATFORM || "ios");
const width = parseInt(getArg("--width", "390"), 10);
const height = parseInt(getArg("--height", "844"), 10);
const outputDir = getArg("--output-dir", "./screenshots");
const strict = hasFlag("--strict");
const useVision = hasFlag("--vision");

// Route table — mirrors app.json scheme gaia:// + apps/mobile sitemap
const ROUTE_MAP = [
  { route: "/c", deepLink: "gaia://chat", label: "chat-home" },
  { route: "/todos", deepLink: "gaia://todos", label: "todos" },
  { route: "/settings", deepLink: "gaia://settings", label: "settings" },
  { route: "/notifications", deepLink: "gaia://notifications", label: "notifications" },
  { route: "/integrations", deepLink: "gaia://integrations", label: "integrations" },
  { route: "/calendar", deepLink: "gaia://calendar", label: "calendar", optional: true },
];
const singleRoute = getArg("--route", null);
const allRoutes = hasFlag("--all-routes");

// ── Vision prompt (shared with docs) ─────────────────────────────────────
function buildVisionPrompt({ route, diffRatio, threshold }) {
  return `You are a senior mobile QA comparing a WEB screenshot (first image) and a NATIVE iOS screenshot (second image) of the SAME route "${route}" in the Gaia app.

Context: Gaia web is Next.js (apps/web), native is Expo 55 + expo-router (apps/mobile). Both should render identical content, navigation, and seeded dev user state (dev@gaia.local) — see apps/web/e2e/harness.ts. Web runs on ${webBase}, native via Expo Go or dev build io.heygaia.gaiamobile.

Task: Compare the two images and respond in STRICT JSON only with this shape:
{"verdict":"PASS|FLAG|BLOCK","confidence":0.0-1.0,"diffPixelsApprox":"%","issues":[{"severity":"low|medium|high","type":"layout|content|color|typography|missing-element|extra-element|navigation","description":"one sentence","location":"where"}],"notes":"one sentence summary","expectedDiffsDismissed":["intentionally platform-specific diffs"]}

Rules:
- PASS = visually equivalent for the user (allow platform chrome — browser URL bar vs native tab bar, status bar, scrollbar, font smoothing).
- FLAG = noticeable parity gap to file but not blocking (spacing, font weight, icon variant).
- BLOCK = functional parity break (missing seeded data like "Sample todo 1" on /todos, missing composer placeholder "What can I do for you today?" on /c, wrong state, broken navigation).
- Ignore: browser chrome, iOS status bar, scrollbars.
- Diff ratio from pixelmatch: ${(diffRatio * 100).toFixed(2)}% (threshold ${(threshold * 100).toFixed(1)}%). The third image (if present) is the pixelmatch diff — red pixels are mismatches.
`.trim();
}

// ── Screenshot capture ───────────────────────────────────────────────────
async function captureWeb({ route, outPath }) {
  const url = `${webBase.replace(/\/$/, "")}${route}`;
  console.log(`[web] capturing ${url} → ${outPath}`);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  // Try Playwright module first, fall back to `npx playwright screenshot` CLI
  try {
    const { chromium } = await import("playwright");
    const browser = await chromium.launch();
    const ctx = await browser.newContext({
      viewport: { width, height },
      colorScheme: "dark",
      deviceScaleFactor: 2,
    });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: outPath, fullPage: false });
    await browser.close();
    console.log(`[web] ✓ via playwright module`);
    return outPath;
  } catch (e) {
    console.warn(`[web] playwright module failed (${e.message}), trying CLI...`);
    const r = spawnSync("npx", ["playwright", "screenshot", "--browser", "chromium", "--viewport-size", `${width},${height}`, url, outPath], { stdio: "inherit", timeout: 45000 });
    if (r.status !== 0) throw new Error(`playwright CLI screenshot failed for ${url}`);
    return outPath;
  }
}

function captureNative({ deepLink, outPath, plat }) {
  console.log(`[native] capturing ${plat}:${deepLink} → ${outPath}`);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  // Try deep link first
  if (plat === "ios") {
    try {
      // Open deep link
      spawnSync("xcrun", ["simctl", "openurl", "booted", deepLink], { stdio: "pipe", timeout: 10000 });
      execFileSync("sleep", ["2"]);
    } catch {}
    // Screenshot via simctl
    try {
      execFileSync("xcrun", ["simctl", "io", "booted", "screenshot", outPath], { stdio: "pipe", timeout: 15000 });
      console.log(`[native] ✓ via xcrun simctl`);
      return outPath;
    } catch (e) {
      console.warn(`[native] xcrun simctl failed: ${e.message}`);
    }
  } else if (plat === "android") {
    try {
      spawnSync("adb", ["shell", `am start -a android.intent.action.VIEW -d "${deepLink}"`], { stdio: "pipe", timeout: 10000 });
      execFileSync("sleep", ["2"]);
    } catch {}
    try {
      const buf = execFileSync("adb", ["exec-out", "screencap", "-p"], { maxBuffer: 50_000_000, timeout: 15000 });
      fs.writeFileSync(outPath, buf);
      console.log(`[native] ✓ via adb screencap`);
      return outPath;
    } catch (e) {
      console.warn(`[native] adb failed: ${e.message}`);
    }
  }
  // Expo web fallback (always works if web is running — not a true native screenshot but shows RN rendering)
  const expoWebUrl = `http://localhost:8082${deepLink.replace("gaia://", "/")}`;
  console.warn(`[native] falling back to Expo web at ${expoWebUrl} (start with: npx --prefix apps/mobile expo start --web --port 8082)`);
  try {
    spawnSync("npx", ["playwright", "screenshot", expoWebUrl, outPath], { stdio: "pipe", timeout: 20000 });
    if (fs.existsSync(outPath)) {
      console.log(`[native] ✓ via expo web fallback`);
      return outPath;
    }
  } catch {}
  throw new Error(`Native screenshot failed for ${plat}:${deepLink}. Boot a simulator (xcrun simctl boot "iPhone 15" && open -a Simulator) or start an Android emulator.`);
}

// ── Image normalization + pixelmatch ─────────────────────────────────────
async function normalizeImage(inPath, outPath) {
  await loadImageDeps();
  // Use sharp to resize to logical width×height @1x (we keep 2x capture but normalize for diff)
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  await sharp(inPath).resize(width, height, { fit: "cover", position: "top" }).png().toFile(outPath);
  return outPath;
}

async function diffImages(webPath, nativePath, outPath, thresh) {
  await loadImageDeps();
  const normDir = path.join(path.dirname(outPath), ".normalized");
  fs.mkdirSync(normDir, { recursive: true });
  const normWeb = path.join(normDir, "web-" + path.basename(webPath));
  const normNative = path.join(normDir, "native-" + path.basename(nativePath));
  await normalizeImage(webPath, normWeb);
  await normalizeImage(nativePath, normNative);

  const img1 = PNG.sync.read(fs.readFileSync(normWeb));
  const img2 = PNG.sync.read(fs.readFileSync(normNative));

  if (img1.width !== img2.width || img1.height !== img2.height) {
    throw new Error(`Normalized sizes differ: web ${img1.width}×${img1.height} vs native ${img2.width}×${img2.height}`);
  }
  const { width: w, height: h } = img1;
  const diff = new PNG({ width: w, height: h });

  const diffPixels = pixelmatch(img1.data, img2.data, diff.data, w, h, {
    threshold: thresh,
    includeAA: false,
    alpha: 0.1,
    diffColor: [255, 0, 0],
    diffColorAlt: [0, 255, 0],
  });

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, PNG.sync.write(diff));

  const totalPixels = w * h;
  const diffRatio = diffPixels / totalPixels;
  const pass = diffRatio <= thresh;

  return { diffPixels, totalPixels, diffRatio, pass, width: w, height: h };
}

// ── Vision LLM call ──────────────────────────────────────────────────────
async function callVision({ webPath, nativePath, diffPath, route, diffRatio }) {
  const prompt = buildVisionPrompt({ route, diffRatio, threshold });
  const b64 = (p) => fs.readFileSync(p).toString("base64");
  const apiKeyOpenAI = process.env.OPENAI_API_KEY;
  const apiKeyAnthropic = process.env.ANTHROPIC_API_KEY;
  const modelOverride = getArg("--vision-model", null);

  if (apiKeyAnthropic) {
    console.log(`[vision] calling Anthropic ${modelOverride || "claude-sonnet-4-20250514"} for ${route}`);
    try {
      const { default: Anthropic } = await import("@anthropic-ai/sdk").catch(() => ({ default: null }));
      if (!Anthropic) throw new Error("npm install @anthropic-ai/sdk");
      const client = new Anthropic({ apiKey: apiKeyAnthropic });
      const content = [
        { type: "text", text: prompt },
        { type: "image", source: { type: "base64", media_type: "image/png", data: b64(webPath) } },
        { type: "image", source: { type: "base64", media_type: "image/png", data: b64(nativePath) } },
      ];
      if (diffPath && fs.existsSync(diffPath)) {
        content.push({ type: "image", source: { type: "base64", media_type: "image/png", data: b64(diffPath) } });
      }
      const res = await client.messages.create({
        model: modelOverride || "claude-sonnet-4-20250514",
        max_tokens: 1200,
        messages: [{ role: "user", content }],
      });
      const text = res.content.map((c) => c.text || "").join("");
      // LLM is instructed to output strict JSON — parse it
      try { return JSON.parse(text); } catch { return { verdict: "FLAG", raw: text, notes: "non-JSON response" }; }
    } catch (e) {
      console.warn(`[vision] Anthropic failed: ${e.message}`);
    }
  }

  if (apiKeyOpenAI) {
    console.log(`[vision] calling OpenAI ${modelOverride || "gpt-4o"} for ${route}`);
    try {
      const { default: OpenAI } = await import("openai").catch(() => ({ default: null }));
      if (!OpenAI) throw new Error("npm install openai");
      const client = new OpenAI({ apiKey: apiKeyOpenAI });
      const toDataUrl = (p) => `data:image/png;base64,${b64(p)}`;
      const content = [
        { type: "text", text: prompt },
        { type: "image_url", image_url: { url: toDataUrl(webPath) } },
        { type: "image_url", image_url: { url: toDataUrl(nativePath) } },
      ];
      if (diffPath && fs.existsSync(diffPath)) {
        content.push({ type: "image_url", image_url: { url: toDataUrl(diffPath) } });
      }
      const res = await client.chat.completions.create({
        model: modelOverride || "gpt-4o",
        response_format: { type: "json_object" },
        messages: [{ role: "user", content }],
        max_tokens: 1200,
      });
      const text = res.choices[0]?.message?.content || "{}";
      return JSON.parse(text);
    } catch (e) {
      console.warn(`[vision] OpenAI failed: ${e.message}`);
    }
  }

  if (!apiKeyOpenAI && !apiKeyAnthropic) {
    // Cheap local heuristic when no API key: just echo diffRatio
    console.log(`[vision] no API key (OPENAI_API_KEY/ANTHROPIC_API_KEY unset) — heuristic verdict for ${route}`);
    return {
      verdict: diffRatio <= threshold ? "PASS" : diffRatio <= threshold * 1.5 ? "FLAG" : "BLOCK",
      confidence: 0.55,
      diffPixelsApprox: `${(diffRatio * 100).toFixed(2)}%`,
      issues: diffRatio > threshold ? [{ severity: "medium", type: "layout", description: `pixelmatch diff ${(diffRatio*100).toFixed(2)}% > threshold ${(threshold*100).toFixed(1)}%`, location: "full screen" }] : [],
      notes: "heuristic verdict (no vision API key) — set OPENAI_API_KEY or ANTHROPIC_API_KEY for LLM judgment",
      expectedDiffsDismissed: [],
    };
  }

  // Fallback if both failed
  return { verdict: "FLAG", notes: "vision call failed", diffPixelsApprox: `${(diffRatio*100).toFixed(2)}%` };
}

// ── Single comparison ────────────────────────────────────────────────────
async function compareOne({ route, deepLink, webPathIn, nativePathIn, diffPath, label }) {
  const tag = label || route.replace(/\//g, "-") || "root";
  let webPath = webPathIn;
  let nativePath = nativePathIn;

  // Capture if not provided
  if (!webPath) {
    webPath = path.join(outputDir, `web-${tag}.png`);
    // If route-based capture requested:
    await captureWeb({ route, outPath: webPath }).catch((e) => {
      console.error(`[web] capture failed for ${route}: ${e.message}`);
      webPath = null;
    });
  }
  if (!nativePath) {
    nativePath = path.join(outputDir, `native-${tag}.png`);
    try {
      captureNative({ deepLink, outPath: nativePath, plat: platform });
    } catch (e) {
      console.error(`[native] capture failed for ${route}: ${e.message}`);
      nativePath = null;
    }
  }

  if (!webPath || !nativePath || !fs.existsSync(webPath) || !fs.existsSync(nativePath)) {
    return {
      route, deepLink, label: tag,
      error: "missing screenshot",
      webPath, nativePath, diffPath,
      diffRatio: 1, pass: false,
      vision: { verdict: "BLOCK", notes: "missing screenshot" },
    };
  }

  const diffOut = diffPath || path.join(outputDir, `diff-${tag}.png`);
  const { diffPixels, totalPixels, diffRatio, pass } = await diffImages(webPath, nativePath, diffOut, threshold);

  console.log(`[diff] ${tag}: ${diffPixels}/${totalPixels} pixels (${(diffRatio*100).toFixed(2)}%) threshold ${(threshold*100).toFixed(1)}% → ${pass ? "PASS" : "FLAG"}`);

  let vision = null;
  if (useVision) {
    vision = await callVision({ webPath, nativePath, diffPath: diffOut, route, diffRatio });
    console.log(`[vision] ${tag}: ${vision.verdict} — ${vision.notes}`);
  } else {
    vision = {
      verdict: pass ? "PASS" : "FLAG",
      notes: pass ? "pixelmatch pass" : `pixelmatch diff ${(diffRatio*100).toFixed(2)}% > ${(threshold*100).toFixed(1)}%`,
    };
  }

  const block = vision.verdict === "BLOCK" || (!pass && strict);
  return {
    route, deepLink, label: tag,
    webPath, nativePath, diffPath: diffOut,
    diffPixels, totalPixels, diffRatio, threshold, pass,
    vision,
    status: block ? "BLOCK" : vision.verdict === "FLAG" || !pass ? "FLAG" : "PASS",
  };
}

// ── Report writer ───────────────────────────────────────────────────────
function writeReports(results, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const report = {
    generatedAt: new Date().toISOString(),
    webBase, platform, threshold, width, height,
    summary: {
      total: results.length,
      pass: results.filter((r) => r.status === "PASS").length,
      flag: results.filter((r) => r.status === "FLAG").length,
      block: results.filter((r) => r.status === "BLOCK").length,
      error: results.filter((r) => r.error).length,
    },
    routes: results,
  };
  const jsonPath = path.join(outDir, "report.json");
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2));
  console.log(`[report] ${jsonPath}`);

  // HTML side-by-side
  const htmlRows = results.map((r) => `
    <tr class="status-${r.status || (r.pass ? "PASS" : "FLAG")}">
      <td><code>${r.route}</code><br><small>${r.deepLink || ""}</small></td>
      <td>${r.diffRatio != null ? (r.diffRatio*100).toFixed(2)+"%" : "—"}<br><small>${r.diffPixels ?? "—"} px</small></td>
      <td><span class="badge badge-${(r.vision?.verdict || r.status || "PASS").toLowerCase()}">${r.vision?.verdict || r.status || (r.pass?"PASS":"FLAG")}</span></td>
      <td><small>${(r.vision?.notes || r.error || "").toString().slice(0,120)}</small></td>
      <td>
        ${r.webPath && fs.existsSync(r.webPath) ? `<a href="${path.basename(r.webPath)}" target="_blank"><img src="${path.basename(r.webPath)}" width="120" /></a>` : "—"}
      </td>
      <td>
        ${r.nativePath && fs.existsSync(r.nativePath) ? `<a href="${path.basename(r.nativePath)}" target="_blank"><img src="${path.basename(r.nativePath)}" width="120" /></a>` : "—"}
      </td>
      <td>
        ${r.diffPath && fs.existsSync(r.diffPath) ? `<a href="${path.basename(r.diffPath)}" target="_blank"><img src="${path.basename(r.diffPath)}" width="120" /></a>` : "—"}
      </td>
    </tr>
  `).join("\n");

  const html = `<!doctype html>
<meta charset="utf-8"><title>Gaia Visual Parity — ${new Date().toISOString()}</title>
<style>
  body{font-family:system-ui,sans-serif;margin:24px;background:#0a0a0a;color:#e5e5e5}
  h1{font-size:20px} h2{font-size:14px;color:#999}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{border:1px solid #333;padding:8px;text-align:left;vertical-align:top}
  th{background:#1a1a1a}
  tr.status-PASS{background:#0f1f0f} tr.status-FLAG{background:#2a1f0f} tr.status-BLOCK{background:#2a0f0f}
  .badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .badge-pass{background:#1a5c1a;color:#a3f3a3} .badge-flag{background:#7a5a00;color:#ffe28a} .badge-block{background:#7a0000;color:#ffb0b0}
  img{border:1px solid #333;border-radius:6px}
  small{color:#999}
</style>
<h1>Gaia Visual Parity — Web vs Native</h1>
<h2>webBase=${webBase} · platform=${platform} · threshold=${(threshold*100).toFixed(1)}% · ${report.generatedAt}</h2>
<p><strong>${report.summary.pass} PASS</strong> · ${report.summary.flag} FLAG · ${report.summary.block} BLOCK · ${report.summary.total} total · <a href="report.json">report.json</a></p>
<table><tr><th>Route</th><th>Diff</th><th>Verdict</th><th>Notes</th><th>Web</th><th>Native</th><th>Diff</th></tr>
${htmlRows}
</table>
<p><small>Generated by scripts/vision-compare.mjs · threshold=${threshold} · size=${width}×${height}</small></p>
`;
  const htmlPath = path.join(outDir, "report.html");
  fs.writeFileSync(htmlPath, html);
  console.log(`[report] ${htmlPath}`);
  return { jsonPath, htmlPath, report };
}

// ── Main ─────────────────────────────────────────────────────────────────
async function main() {
  // Single pair mode (explicit --web + --native)
  const explicitWeb = getArg("--web", null);
  const explicitNative = getArg("--native", null);
  const explicitOut = getArg("--out", null);

  if (explicitWeb && explicitNative) {
    console.log(`[mode] single-pair: web=${explicitWeb} native=${explicitNative}`);
    const out = explicitOut || path.join(outputDir, "diff.png");
    const result = await compareOne({
      route: "/manual",
      deepLink: "gaia://chat",
      webPathIn: explicitWeb,
      nativePathIn: explicitNative,
      diffPath: out,
      label: "manual",
    });
    writeReports([result], path.dirname(out));
    if (strict && result.status !== "PASS") process.exit(1);
    return;
  }

  if (explicitWeb || explicitNative) {
    console.error("Error: --web and --native must be used together for single-pair mode. Or use --route / --all-routes.");
    process.exit(2);
  }

  // Route(s) mode
  let targets;
  if (singleRoute) {
    const m = ROUTE_MAP.find((r) => r.route === singleRoute);
    targets = m ? [m] : [{ route: singleRoute, deepLink: `gaia://${singleRoute.replace(/^\//, "")}`, label: singleRoute.replace(/\//g, "-") || "root" }];
  } else if (allRoutes) {
    // Try to augment from expo-router sitemap if available
    let sitemapRoutes = [];
    try {
      // npx expo-router-sitemap is slow — try reading quickly then fall back to ROUTE_MAP
      // We shell out here:
      const out = execFileSync("npx", ["-y", "expo-router-sitemap@latest"], { cwd: "apps/mobile", timeout: 20000, encoding: "utf8", stdio: ["pipe","pipe","pipe"] });
      const matches = [...out.matchAll(/Route:\s*(\S+)/g)];
      sitemapRoutes = matches.map((m) => m[1]).filter(Boolean);
      console.log(`[sitemap] found ${sitemapRoutes.length} routes from expo-router-sitemap`);
    } catch (e) {
      console.warn(`[sitemap] expo-router-sitemap failed (${e.message}) — using hardcoded ROUTE_MAP (${ROUTE_MAP.length} routes)`);
    }
    if (sitemapRoutes.length > 0) {
      // Merge — keep ROUTE_MAP ordering/labels, add any new sitemap routes not in map
      const known = new Set(ROUTE_MAP.map((r) => r.route));
      for (const r of sitemapRoutes) {
        if (!known.has(r)) {
          ROUTE_MAP.push({ route: r, deepLink: `gaia://${r.replace(/^\//, "").replace(/\//g, "-")}`, label: r.replace(/\//g, "-") || "root", optional: true });
        }
      }
    }
    targets = ROUTE_MAP.filter((r) => !r.optional || args.includes("--include-optional"));
    if (targets.length === 0) targets = ROUTE_MAP;
    // When --include-optional is not passed, still include the core 5 even if marked optional? Filter logic above handles non-optional = always included
    // Simpler: always include non-optional, include optional only with flag — but we want at least 5 rows, so:
    if (!args.includes("--include-optional")) {
      targets = ROUTE_MAP.filter((r) => !r.optional);
    }
  } else {
    console.error("Error: specify either --web + --native, --route <path>, or --all-routes.\n" + HELP);
    process.exit(2);
  }

  console.log(`[mode] ${targets.length} route(s) — webBase=${webBase} platform=${platform} threshold=${threshold} vision=${useVision} strict=${strict}`);

  const results = [];
  for (const t of targets) {
    const r = await compareOne({
      route: t.route,
      deepLink: t.deepLink,
      webPathIn: null,
      nativePathIn: null,
      diffPath: null,
      label: t.label,
    });
    results.push(r);
  }

  const { report } = writeReports(results, outputDir);
  console.log(`\nSummary: ${report.summary.pass} PASS · ${report.summary.flag} FLAG · ${report.summary.block} BLOCK / ${report.summary.total}`);
  if (strict && (report.summary.flag > 0 || report.summary.block > 0)) {
    console.error("[strict] FAIL — non-PASS results present");
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e.stack || e.message);
  process.exit(1);
});
