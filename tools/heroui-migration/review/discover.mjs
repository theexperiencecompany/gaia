#!/usr/bin/env node
/**
 * Writes the per-route state script: every overlay and disclosure a page has,
 * found by ARIA role on the desktop "before" build.
 *
 *   node review/discover.mjs --base http://localhost:3210 [--out ~/v3review/out] [--only /c,/todos]
 *
 * A state is one action (click or hover) on an element named by role +
 * accessible name + index, which capture.mjs replays on both builds:
 *   tabs       every unselected [role=tab]
 *   popup      every aria-haspopup / aria-expanded=false trigger (Dropdown, Select,
 *              Popover, Accordion, disclosure), kept when something opened
 *   modal      any other button whose click opened a [role=dialog]
 *   tooltip    icon-only buttons and links whose hover showed a [role=tooltip]
 * Repeated triggers (one menu per todo row) keep their first instance; triggers in
 * the shared header/footer/nav/sidebar are captured once per chrome, on the first route.
 * Output: review/states.json (committed, so a rerun replays the same states).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, load, networkQuiet, newContext, OVERLAY_SELECTOR, stepLocator } from "./browser.mjs";
import { DEFAULT_OUT, VIEWPORTS, WEB_BASE } from "./config.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const BASE = arg("base", WEB_BASE.before);
const OUT = resolve(arg("out", DEFAULT_OUT));
const ONLY = arg("only")?.split(",");
/** --kinds toggle,...: run only these probes and add what they find to the existing states.json. */
const KINDS = arg("kinds")?.split(",");
const probes = (kind) => !KINDS || KINDS.includes(kind);
const STATES_FILE = join(HERE, "states.json");

const inventory = JSON.parse(readFileSync(join(OUT, "inventory.json"), "utf8"));
const seed = JSON.parse(readFileSync(join(OUT, "seed-state.json"), "utf8"));
const desktop = VIEWPORTS.find((v) => v.name === "desktop");

const ROLES = new Set(["button", "tab", "combobox", "link", "menuitem", "switch", "checkbox"]);
const CAPS = { tabs: 12, popup: 24, modal: 25, toggle: 12, tooltip: 16 };
/** DOM mutations a plain button click must cause to count as a content toggle (demo chips, replay, carousels). */
const TOGGLE_MUTATIONS = 3;
const ROUTE_TIMEOUT_MS = Number(arg("route-timeout-min", 6)) * 60_000;

/** role + accessible name of one element, from Playwright's own ARIA snapshot. */
async function roleAndName(el) {
  const snap = await el.ariaSnapshot({ timeout: 2000 }).catch(() => "");
  const m = snap.split("\n")[0].match(/^- (\w+)(?: "((?:[^"\\]|\\.)*)")?/);
  if (!m || !ROLES.has(m[1]) || !m[2]) return null;
  return { role: m[1], name: m[2].replace(/\\"/g, '"') };
}

async function nthOf(page, el, role, name) {
  const all = await page.getByRole(role, { name, exact: true }).elementHandles();
  const handle = await el.elementHandle();
  for (let i = 0; i < all.length; i++) if (await all[i].evaluate((a, b) => a === b, handle)) return i;
  return -1;
}

/** Visible elements matching `selector` that pass `keep` (cheap DOM facts), with role + accessible name. */
async function candidates(page, selector, keep = () => true) {
  const loc = page.locator(selector);
  const n = await loc.count();
  const out = [];
  for (let i = 0; i < n && out.length < 60; i++) {
    const el = loc.nth(i);
    const facts = await el
      .evaluate(
        (e) => {
          const r = e.getBoundingClientRect();
          const cs = getComputedStyle(e);
          return {
            visible: r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none",
            chrome: !!e.closest("header,footer,nav,aside,[role=navigation],[data-slot=sidebar]"),
            signature: `${e.tagName}.${e.className}|${e.parentElement?.className ?? ""}`.slice(0, 300),
            iconOnly: !(e.textContent ?? "").trim(),
          };
        },
        null,
        { timeout: 2000 },
      )
      .catch(() => null);
    if (!facts?.visible || !keep(facts)) continue;
    const rn = await roleAndName(el);
    if (rn) out.push({ el, ...rn, ...facts });
  }
  return out;
}

const overlayOpen = (page) => page.locator(OVERLAY_SELECTOR).filter({ visible: true }).count();

/** Back to the page's initial state after a probe: Escape, and a plain reload if that was not enough. */
async function reset(page, target, url) {
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(200);
  if (page.url() === url && (await overlayOpen(page)) === 0) return;
  await page.goto(BASE + target.url, { waitUntil: "load", timeout: 60_000 });
  await networkQuiet(page, 500, 8000);
}

async function discover(page, target) {
  await load(page, BASE, target);
  const url = page.url();
  const chromeGroup = target.user === "anon" ? "marketing" : "app";
  const steps = [];
  const recorded = new Set();
  const perSignature = new Map();
  /** Role + name + index of a candidate not yet recorded on this route; null to skip it. */
  const identify = async (c, kind) => {
    if (recorded.has(`${c.role}|${c.name}`)) return null;
    if (kind === "popup" && (perSignature.get(c.signature) ?? 0) >= 2) return null;
    const nth = await nthOf(page, c.el, c.role, c.name).catch(() => -1);
    return nth < 0 ? null : { role: c.role, name: c.name, nth };
  };
  const record = (c, step) => {
    recorded.add(`${c.role}|${c.name}`);
    perSignature.set(c.signature, (perSignature.get(c.signature) ?? 0) + 1);
    steps.push(c.chrome ? { ...step, chrome: chromeGroup } : step);
  };
  const count = (kind) => steps.filter((s) => s.kind.startsWith(kind)).length;

  for (const c of probes("tabs") ? await candidates(page, "[role=tab][aria-selected=false]") : []) {
    if (count("tabs") >= CAPS.tabs) break;
    const s = await identify(c, "tabs");
    if (s) record(c, { kind: "tabs", action: "click", ...s });
  }

  for (const c of !probes("popup") ? [] : await candidates(page, "[aria-haspopup]:not([aria-haspopup=false]),[aria-expanded=false]")) {
    if (count("popup") >= CAPS.popup) break;
    if (c.role === "tab") continue;
    const s = await identify(c, "popup");
    if (!s) continue;
    const loc = stepLocator(page, s);
    await loc.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    await loc.click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(450);
    const expanded = await loc.getAttribute("aria-expanded", { timeout: 1000 }).catch(() => null);
    if (((await overlayOpen(page)) > 0 || expanded === "true") && page.url() === url) {
      const role = await page.locator(OVERLAY_SELECTOR).filter({ visible: true }).first().getAttribute("role", { timeout: 1000 }).catch(() => null);
      record(c, { kind: role ? `popup:${role}` : "popup:disclosure", action: "click", ...s });
    }
    await reset(page, target, url);
  }

  const plainButtons = "button:not([aria-haspopup]):not([aria-expanded]):not([type=submit]),[role=button]:not([aria-haspopup])";
  for (const c of probes("modal") || probes("toggle") ? await candidates(page, plainButtons) : []) {
    if (count("modal") >= CAPS.modal && count("toggle") >= CAPS.toggle) break;
    const s = await identify(c, "modal");
    if (!s) continue;
    const loc = stepLocator(page, s);
    await loc.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    // Count DOM changes the click causes: a chip, toggle or replay button that swaps content is a state too.
    await page.evaluate(() => {
      window.__reviewMutations = 0;
      window.__reviewObserver = new MutationObserver((m) => { window.__reviewMutations += m.length; });
      window.__reviewObserver.observe(document.body, { subtree: true, childList: true, characterData: true });
    });
    // Autoplaying sections mutate on their own; only change beyond that baseline is the click's.
    await page.waitForTimeout(600);
    const baseline = await page.evaluate(() => { const n = window.__reviewMutations; window.__reviewMutations = 0; return n; }).catch(() => 0);
    await loc.click({ timeout: 2000, noWaitAfter: true }).catch(() => {});
    await page.waitForTimeout(600);
    for (const other of page.context().pages()) if (other !== page) await other.close();
    const sameUrl = page.url() === url;
    const dialog = sameUrl && (await page.locator("[role=dialog],[role=alertdialog]").filter({ visible: true }).count()) > 0;
    const changed = sameUrl && (await page.evaluate(() => { window.__reviewObserver.disconnect(); return window.__reviewMutations; }).catch(() => 0)) >= 2 * baseline + TOGGLE_MUTATIONS;
    if (dialog) {
      if (probes("modal")) record(c, { kind: "modal", action: "click", ...s });
    } else if (changed && probes("toggle") && !c.chrome && count("toggle") < CAPS.toggle) record(c, { kind: "toggle", action: "click", ...s });
    await reset(page, target, url);
  }

  for (const c of !probes("tooltip") ? [] : await candidates(page, "button,a[href],[role=button]", (f) => f.iconOnly)) {
    if (count("tooltip") >= CAPS.tooltip) break;
    const s = await identify(c, "tooltip");
    if (!s) continue;
    await stepLocator(page, s).hover({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(800);
    if ((await page.locator("[role=tooltip]").filter({ visible: true }).count()) > 0) record(c, { kind: "tooltip", action: "hover", ...s });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(150);
  }
  return steps;
}

const WORKERS = Number(arg("workers", 4));
const browser = await chromium.launch();
const log = { blocked: new Set(), fetched: new Set() };
const found = {};
const queue = inventory.targets.filter((t) => !ONLY || ONLY.includes(t.key));
const total = queue.length;
let done = 0;
async function worker() {
  const contexts = {};
  while (queue.length) {
    const target = queue.shift();
    contexts[target.user] ??= await newContext(browser, { vp: desktop, user: target.user, seed, cacheDir: join(OUT, "netcache"), log });
    const page = await contexts[target.user].newPage();
    try {
      // A probe that wedges the page (a click that never settles) fails its route, not the whole run.
      found[target.key] = await Promise.race([
        discover(page, target),
        new Promise((_, reject) => setTimeout(() => reject(new Error(`discovery timed out after ${ROUTE_TIMEOUT_MS / 1000}s`)), ROUTE_TIMEOUT_MS)),
      ]);
    } catch (e) {
      found[target.key] = { error: String(e.message).split("\n")[0] };
    }
    await page.close();
    const s = found[target.key];
    console.log(`${String(++done).padStart(3)}/${total} ${target.key.padEnd(48)} ${Array.isArray(s) ? `${s.length} states` : `ERROR ${s.error}`}`);
  }
  for (const c of Object.values(contexts)) await c.close();
}
await Promise.all(Array.from({ length: WORKERS }, worker));
await browser.close();

// Shared chrome (header, nav, sidebar, footer) is reviewed once per chrome, on its first route in inventory order.
const states = ONLY || KINDS ? JSON.parse(readFileSync(STATES_FILE, "utf8")) : {};
const seenChrome = new Set();
for (const t of inventory.targets) {
  let list = found[t.key] ?? states[t.key];
  // A failed partial probe must not erase the states the route already has; it is reported below.
  if (KINDS && !Array.isArray(found[t.key]) && Array.isArray(states[t.key])) list = states[t.key];
  if (KINDS && Array.isArray(found[t.key]) && Array.isArray(states[t.key])) {
    // A partial probe adds to what the route already had; a trigger already reviewed is not added twice.
    const have = new Set(states[t.key].map((s) => `${s.role}|${s.name}|${s.nth}`));
    list = [...states[t.key], ...found[t.key].filter((s) => !have.has(`${s.role}|${s.name}|${s.nth}`))];
  }
  if (!Array.isArray(list)) {
    if (list) states[t.key] = list;
    continue;
  }
  states[t.key] = list.filter((s) => {
    if (!s.chrome) return true;
    const k = `${s.chrome}|${s.role}|${s.name}`;
    if (seenChrome.has(k)) return false;
    seenChrome.add(k);
    return true;
  });
}
const ordered = Object.fromEntries(Object.keys(states).sort().map((k) => [k, states[k]]));
writeFileSync(STATES_FILE, `${JSON.stringify(ordered, null, 2)}\n`);
const totalStates = Object.values(ordered).reduce((n, s) => n + (Array.isArray(s) ? s.length : 0), 0);
console.log(`${totalStates} states over ${Object.keys(ordered).length} routes -> ${STATES_FILE}`);
const failed = Object.entries(found).filter(([, s]) => !Array.isArray(s));
if (failed.length) {
  console.error(`${failed.length} routes failed discovery: ${failed.map(([k]) => k).join(",")}`);
  process.exit(1);
}
