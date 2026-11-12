#!/usr/bin/env node
/**
 * Captures one build: every inventory target at both viewports, the full page
 * plus every state in review/states.json.
 *
 *   node review/capture.mjs --label before --run 1 [--base URL] [--out DIR] [--only keys] [--workers 4]
 *
 * Output: <out>/shots/<label>/run<N>/<viewport>/<file>.png and
 *         <out>/shots/<label>/run<N>/manifest.json
 * Run it twice per build: compare.mjs treats pixels that differ between two runs
 * of the same build as noise and masks them before diffing the builds.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, finishAnimations, load, newContext, stepLocator } from "./browser.mjs";
import { DEFAULT_OUT, fileOf, MAX_PAGE_HEIGHT, stateId, VIEWPORTS, WEB_BASE } from "./config.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const LABEL = arg("label");
if (!["before", "after"].includes(LABEL)) throw new Error("--label before|after is required");
const RUN = Number(arg("run", 1));
const BASE = arg("base", WEB_BASE[LABEL]);
const OUT = resolve(arg("out", DEFAULT_OUT));
const ONLY = arg("only")?.split(",");
const WORKERS = Number(arg("workers", 4));
const DIR = join(OUT, "shots", LABEL, `run${RUN}`);

const inventory = JSON.parse(readFileSync(join(OUT, "inventory.json"), "utf8"));
const seed = JSON.parse(readFileSync(join(OUT, "seed-state.json"), "utf8"));
const states = JSON.parse(readFileSync(join(HERE, "states.json"), "utf8"));

const jobs = [];
for (const target of inventory.targets.filter((t) => !ONLY || ONLY.includes(t.key))) {
  const list = states[target.key];
  if (!Array.isArray(list)) throw new Error(`states.json has no state list for ${target.key}: run discover.mjs`);
  for (const vp of VIEWPORTS) jobs.push({ target, vp, steps: list });
}

async function shootBase(page, job, entry) {
  const facts = await load(page, BASE, job.target);
  Object.assign(entry, facts);
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  const file = join(DIR, job.vp.name, fileOf(job.target.key, "base"));
  await page.screenshot({
    path: file,
    fullPage: height <= MAX_PAGE_HEIGHT,
    clip: height > MAX_PAGE_HEIGHT ? { x: 0, y: 0, width: job.vp.width, height: MAX_PAGE_HEIGHT } : undefined,
    animations: "disabled",
    caret: "hide",
  });
  entry.file = `${job.vp.name}/${fileOf(job.target.key, "base")}`;
  entry.truncated = height > MAX_PAGE_HEIGHT;
}

async function shootState(page, job, step, entry) {
  await load(page, BASE, job.target);
  const loc = stepLocator(page, step);
  if ((await loc.count()) === 0) {
    entry.missing = true;
    return;
  }
  if (!(await loc.isVisible())) {
    entry.hidden = true;
    return;
  }
  await loc.scrollIntoViewIfNeeded();
  if (step.action === "hover") await loc.hover();
  else await loc.click();
  await page.waitForTimeout(step.action === "hover" ? 900 : 600);
  await finishAnimations(page);
  const file = join(DIR, job.vp.name, fileOf(job.target.key, stateId(step)));
  await page.screenshot({ path: file, animations: "disabled", caret: "hide" });
  entry.file = `${job.vp.name}/${fileOf(job.target.key, stateId(step))}`;
}

for (const vp of VIEWPORTS) mkdirSync(join(DIR, vp.name), { recursive: true });
const browser = await chromium.launch();
const log = { blocked: new Set(), fetched: new Set() };
const results = [];
let done = 0;
const total = jobs.reduce((n, j) => n + 1 + j.steps.length, 0);

async function worker() {
  const contexts = {};
  while (jobs.length) {
    const job = jobs.shift();
    const ctxKey = `${job.vp.name}|${job.target.user}`;
    contexts[ctxKey] ??= await newContext(browser, { vp: job.vp, user: job.target.user, seed, cacheDir: join(OUT, "netcache"), log });
    const page = await contexts[ctxKey].newPage();
    for (const step of [null, ...job.steps]) {
      const entry = { key: job.target.key, vp: job.vp.name, state: stateId(step), kind: step?.kind ?? "page", stateLabel: step ? `${step.action} ${step.role} "${step.name}"${step.nth ? ` #${step.nth + 1}` : ""}` : "full page" };
      try {
        if (step) await shootState(page, job, step, entry);
        else await shootBase(page, job, entry);
      } catch (e) {
        entry.error = String(e.message).split("\n")[0];
      }
      results.push(entry);
      done++;
      if (done % 25 === 0 || done === total) process.stdout.write(`\r  ${LABEL} run${RUN}: ${done}/${total}`);
    }
    await page.close();
  }
  for (const c of Object.values(contexts)) await c.close();
}

await Promise.all(Array.from({ length: WORKERS }, worker));
await browser.close();
results.sort((a, b) => `${a.key}|${a.vp}|${a.state}`.localeCompare(`${b.key}|${b.vp}|${b.state}`));
const manifest = {
  label: LABEL,
  run: RUN,
  base: BASE,
  capturedAt: new Date().toISOString(),
  seededAt: seed.seededAt,
  blockedMutations: [...log.blocked].sort(),
  thirdPartyFetched: [...log.fetched].sort(),
  shots: results,
};
writeFileSync(join(DIR, "manifest.json"), JSON.stringify(manifest, null, 1));
const errors = results.filter((r) => r.error);
console.log(`\n  ${results.filter((r) => r.file).length} shots, ${errors.length} errors, ${results.filter((r) => r.missing).length} missing triggers -> ${DIR}`);
for (const e of errors.slice(0, 15)) console.log(`    ${e.key} [${e.vp}] ${e.state}: ${e.error}`);
