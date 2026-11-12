/**
 * The deterministic browser every capture and discovery run shares: fixed clock,
 * zone, locale, seeded Math.random, no motion, mutations blocked, third-party
 * bytes replayed from a disk cache, and one settle routine.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { API_BASE, CLOCK_OFFSET_MS, LOCALE, ONBOARDING_USER, TIMEZONE } from "./config.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(join(HERE, "..", "package.json"))("playwright");
export { chromium };

const API_ORIGIN = new URL(API_BASE).origin;
/** POSTs the app makes to read, not write. Every other mutation is blocked so captures never change the seed. */
const READ_ONLY_POSTS = [/\/conversations\/batch-sync$/, /\/calendar\/events\/query$/];
const THIRD_PARTY_BLOCK = /(posthog|google-analytics|googletagmanager|doubleclick|rybbit|sentry|clarity\.ms|fastlane|hotjar|intercom|crisp\.chat)/;
const ANON_USER = "anonymous@review.invalid";
const THIRD_PARTY_KEEP = new Set(["image", "font", "stylesheet", "script"]);

/** Applied before any page script: every CSS animation lands on its end frame, nothing transitions. */
const FREEZE_CSS = `*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;animation-iteration-count:1!important;transition-duration:0s!important;transition-delay:0s!important;caret-color:transparent!important;scroll-behavior:auto!important}`;

function initScript({ css }) {
  // mulberry32: the app's random choices (greetings, placeholders, ids in markup) repeat run to run.
  let s = 0x5eed;
  Math.random = () => {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const add = () => {
    const el = document.createElement("style");
    el.setAttribute("data-review-freeze", "");
    el.textContent = css;
    (document.head || document.documentElement).appendChild(el);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add, { once: true });
  else add();
}

export function captureTime(seed) {
  return new Date(new Date(seed.seededAt).getTime() + CLOCK_OFFSET_MS);
}

/**
 * One browser context per (viewport, user). `log` collects what the guard
 * blocked and what the network cache missed, so the manifest can show it.
 */
export async function newContext(browser, { vp, user, seed, cacheDir, log }) {
  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.deviceScaleFactor,
    isMobile: vp.isMobile,
    hasTouch: vp.hasTouch,
    locale: LOCALE,
    timezoneId: TIMEZONE,
    colorScheme: "dark",
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  await ctx.clock.setFixedTime(captureTime(seed));
  await ctx.addInitScript(initScript, { css: FREEZE_CSS });
  const devUser = user === "anon" ? ANON_USER : user === "onboarding" ? ONBOARDING_USER : null;
  mkdirSync(cacheDir, { recursive: true });

  await ctx.route("**/*", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const type = req.resourceType();
    if (type === "media" || type === "eventsource") return route.abort();
    if (url.origin === API_ORIGIN) {
      const method = req.method();
      if (!["GET", "HEAD", "OPTIONS"].includes(method) && !READ_ONLY_POSTS.some((re) => re.test(url.pathname))) {
        log.blocked.add(`${method} ${url.pathname}`);
        return route.abort("blockedbyclient");
      }
      if (!devUser || method === "OPTIONS") return route.continue();
      return route.continue({ headers: { ...req.headers(), "x-dev-user": devUser } });
    }
    if (url.hostname === "localhost" || url.hostname === "127.0.0.1") return route.continue();
    if (THIRD_PARTY_BLOCK.test(url.hostname)) return route.abort();
    // Third-party pixels (images, fonts, styles, scripts) are kept and replayed; third-party documents,
    // iframes and API calls are not part of this app's rendering and only add network variance.
    if (req.method() !== "GET" || !THIRD_PARTY_KEEP.has(type)) return route.abort();
    return replayThirdParty(route, cacheDir, log);
  });
  return ctx;
}

/** Third-party GETs are fetched once and replayed from disk, so both builds and both runs see the same bytes. */
async function replayThirdParty(route, cacheDir, log) {
  const url = route.request().url();
  const key = createHash("sha256").update(url).digest("hex").slice(0, 32);
  const meta = join(cacheDir, `${key}.json`);
  const body = join(cacheDir, `${key}.bin`);
  if (existsSync(meta)) {
    const m = JSON.parse(readFileSync(meta, "utf8"));
    if (m.failed) return route.abort();
    return route.fulfill({ status: m.status, headers: m.headers, body: readFileSync(body) });
  }
  try {
    const res = await route.fetch({ timeout: 15_000 });
    const headers = res.headers();
    delete headers["content-encoding"];
    delete headers["content-length"];
    writeFileSync(body, await res.body());
    writeFileSync(meta, JSON.stringify({ url, status: res.status(), headers }));
    log.fetched.add(url);
    return route.fulfill({ status: res.status(), headers, body: readFileSync(body) });
  } catch (e) {
    // A host that cannot be reached is recorded as unreachable, so every later run fails it identically.
    writeFileSync(meta, JSON.stringify({ url, failed: String(e.message).split("\n")[0] }));
    log.fetched.add(`${url} (unreachable)`);
    return route.abort();
  }
}

/** Resolve when no request has been in flight for `quietMs`; false if `capMs` passed first. */
export async function networkQuiet(page, quietMs = 700, capMs = 20_000) {
  let inflight = 0;
  let last = Date.now();
  const on = () => { inflight++; last = Date.now(); };
  const off = () => { inflight = Math.max(0, inflight - 1); last = Date.now(); };
  page.on("request", on);
  page.on("requestfinished", off);
  page.on("requestfailed", off);
  const t0 = Date.now();
  try {
    while (Date.now() - t0 < capMs) {
      if (inflight === 0 && Date.now() - last >= quietMs) return true;
      await new Promise((r) => setTimeout(r, 100));
    }
    return false;
  } finally {
    page.off("request", on);
    page.off("requestfinished", off);
    page.off("requestfailed", off);
  }
}

/** Scroll the document and the largest inner scroller end to end, so lazy content loads, then return to top. */
async function scrollToLoad(page) {
  await page.evaluate(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const scrollers = [document.scrollingElement];
    let best = null;
    for (const el of document.querySelectorAll("*")) {
      const cs = getComputedStyle(el);
      if (!/(auto|scroll)/.test(cs.overflowY) || el.scrollHeight - el.clientHeight < 80) continue;
      if (!best || el.clientHeight * el.clientWidth > best.clientHeight * best.clientWidth) best = el;
    }
    if (best) scrollers.push(best);
    for (const sc of scrollers) {
      for (let y = 0; y < sc.scrollHeight; y += Math.max(200, Math.floor(sc.clientHeight * 0.8))) {
        sc.scrollTop = y;
        await sleep(80);
      }
      sc.scrollTop = sc.scrollHeight;
      await sleep(150);
    }
    // Chats open at their newest message; every other scroller at its top.
    for (const sc of scrollers) sc.scrollTop = sc === best && document.location.pathname.startsWith("/c/") ? sc.scrollHeight : 0;
    await sleep(150);
  });
}

async function imagesAndFonts(page) {
  await page.evaluate(async () => {
    const pending = [...document.images].filter((i) => !i.complete);
    await Promise.race([
      Promise.all(pending.map((i) => new Promise((r) => { i.onload = r; i.onerror = r; }))),
      new Promise((r) => setTimeout(r, 8000)),
    ]);
    await document.fonts.ready;
  });
}

/**
 * Jump every running Web Animation to its end state. The CSS freeze covers CSS animations,
 * but JS libraries (framer-motion's blur/fade reveals) drive WAAPI animations it cannot reach,
 * and with the clock pinned those stop mid-frame. Infinite ones (spinners) cannot finish and stay put.
 */
export async function finishAnimations(page) {
  await page.evaluate(() => {
    for (const a of document.getAnimations()) {
      if (a.effect?.getComputedTiming().endTime === Number.POSITIVE_INFINITY) continue;
      a.finish();
    }
  });
  await page.waitForTimeout(100);
}

/** Navigate and settle. Returns facts the manifest records; a non-2xx page or a server error throws. */
export async function load(page, base, target, { wholePage = true } = {}) {
  const res = await page.goto(base + target.url, { waitUntil: "load", timeout: 60_000 });
  const status = res?.status() ?? 0;
  if (status >= 400) throw new Error(`HTTP ${status} for ${target.url}`);
  const quiet = await networkQuiet(page);
  await imagesAndFonts(page);
  let quiet2 = true;
  // A state shot is one viewport around its trigger, so only the full-page shot needs lazy content loaded.
  if (wholePage) {
    await scrollToLoad(page);
    quiet2 = await networkQuiet(page, 500, 10_000);
    await imagesAndFonts(page);
  }
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await finishAnimations(page);
  return { status, finalUrl: new URL(page.url()).pathname + new URL(page.url()).search, networkBusy: !(quiet && quiet2) };
}

/** The locator a state step names, by ARIA role + accessible name, so it pairs across v2 and v3 markup. */
export function stepLocator(page, step) {
  return page.getByRole(step.role, { name: step.name, exact: true }).nth(step.nth);
}

export const OVERLAY_SELECTOR = "[role=dialog],[role=alertdialog],[role=menu],[role=listbox],[role=tooltip]";
