import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

import { captureParts } from "./capture";
import {
  type Approval,
  compareCaptures,
  type Difference,
  isApproved,
} from "./compare";
import {
  INLINE_PARTS,
  OVERLAY_PARTS,
  OVERLAYS,
  type Side,
  STATE_TARGETS,
} from "./parts";
import type { Capture, Styles } from "./types";

const FIXTURE = "/dev/primitive-parity";
const HERE = import.meta.dirname;
const SNAPSHOT = path.join(HERE, "v2-snapshot.jsonl");
const APPROVED = path.join(HERE, "approved.json");
const REPORT_DIR = path.join(HERE, "../../test-results/primitive-parity");
// v2's transitions run 250ms; reading earlier catches a colour mid-fade
const SETTLE_MS = 400;
const OVERLAY_SETTLE_MS = 800;
const DELAY_BUCKET_MS = 250;

const side = (process.env.PARITY_SIDE ?? "v3") as Side;
const screenshotDir = process.env.PARITY_SCREENSHOTS;

const css = (selector: string) => selector.replace(/^css:/, "");

async function settle(page: Page, ms = SETTLE_MS) {
  await page.mouse.move(0, 0);
  await page.waitForTimeout(ms);
}

/** Reads one cell in keyboard focus, hover and pressed, each from rest; focus first, as a pointer left behind changes what a focus does. */
async function captureStates(page: Page, id: string): Promise<Capture> {
  const kind = id.split("/")[0];
  const target = STATE_TARGETS[side][kind];
  if (!target || id.includes("disabled")) return {};
  const cell = page.locator(`[data-parity="${id}"]`);
  const parts = INLINE_PARTS[side];
  const out: Capture = {};
  if (target.focus) {
    // arrive by Tab, so both CSS and React Aria count it as keyboard focus
    await cell.locator(css(target.focus)).first().focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(SETTLE_MS);
    Object.assign(
      out,
      await captureParts(page, "data-parity", parts, "focus", id),
    );
    await page.evaluate(() =>
      (document.activeElement as HTMLElement | null)?.blur(),
    );
    await settle(page);
  }
  await cell.locator(css(target.hover)).first().hover();
  await page.waitForTimeout(SETTLE_MS);
  Object.assign(
    out,
    await captureParts(page, "data-parity", parts, "hover", id),
  );
  if (target.press) {
    await page.mouse.down();
    await page.waitForTimeout(SETTLE_MS / 2);
    Object.assign(
      out,
      await captureParts(page, "data-parity", parts, "press", id),
    );
    await page.mouse.up();
    await page.keyboard.press("Escape");
  }
  await settle(page);
  return out;
}

async function screenshot(page: Page, name: string, selector?: string) {
  if (!screenshotDir) return;
  const file = path.join(
    screenshotDir,
    side,
    `${name.replaceAll("/", "__")}.png`,
  );
  if (selector) await page.locator(selector).screenshot({ path: file });
  else await page.screenshot({ path: file });
}

/** How long a tooltip with no delay of its own takes to open on hover, to the nearest 250ms. */
async function tooltipDelay(page: Page): Promise<Capture> {
  await settle(page);
  const started = Date.now();
  await page.locator("[data-parity-delay]").hover();
  await page
    .locator('[data-parity-mark="tooltip/delay"]')
    .waitFor({ state: "visible" });
  const elapsed = Date.now() - started;
  const bucket = Math.round(elapsed / DELAY_BUCKET_MS) * DELAY_BUCKET_MS;
  return { "tooltip/delay::open::rest": { "open-delay": `${bucket}ms` } };
}

async function captureAll(page: Page): Promise<Capture> {
  await page.goto(FIXTURE, { waitUntil: "networkidle" });
  // v2's pagination cursor and tab indicator take their place once on screen
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await settle(page, OVERLAY_SETTLE_MS);
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page, OVERLAY_SETTLE_MS);
  const capture = await captureParts(
    page,
    "data-parity",
    INLINE_PARTS[side],
    "rest",
  );
  const ids = await page
    .locator("[data-parity]")
    .evaluateAll((cells) =>
      cells.map((cell) => cell.getAttribute("data-parity") ?? ""),
    );
  for (const id of ids) await screenshot(page, id, `[data-parity="${id}"]`);
  for (const id of ids) Object.assign(capture, await captureStates(page, id));
  for (const overlay of OVERLAYS) {
    await page.goto(`${FIXTURE}?overlay=${encodeURIComponent(overlay)}`, {
      waitUntil: "networkidle",
    });
    // a Select opens on press: forced open on mount, v2 sized its list before the trigger laid out
    const opener = page.locator("[data-parity-open] button").first();
    if (await opener.count()) await opener.click();
    await settle(page, OVERLAY_SETTLE_MS);
    Object.assign(
      capture,
      await captureParts(page, "data-parity-mark", OVERLAY_PARTS[side], "open"),
    );
    await screenshot(page, `overlay/${overlay}`);
    if (overlay === "tooltip-delay")
      Object.assign(capture, await tooltipDelay(page));
  }
  return capture;
}

const format = (differences: Difference[]) =>
  differences
    .map((d) => `${d.key} ${d.prop}: v2 ${d.v2} | v3 ${d.v3}`)
    .join("\n");

test("every HeroUI primitive draws as it did on v2", async ({ page }) => {
  test.setTimeout(600_000);
  if (screenshotDir) {
    mkdirSync(path.join(screenshotDir, side, "overlay"), { recursive: true });
  }
  const capture = await captureAll(page);
  const write = process.env.PARITY_WRITE;
  if (write) {
    // JSON Lines, one reading per line, so a re-capture diffs by part and state
    const lines = Object.entries(capture).map(([key, styles]) =>
      JSON.stringify({ key, styles }),
    );
    writeFileSync(write, `${lines.join("\n")}\n`);
    return;
  }
  const snapshot: Capture = Object.fromEntries(
    readFileSync(SNAPSHOT, "utf8")
      .trim()
      .split("\n")
      .map((line) => {
        const { key, styles } = JSON.parse(line) as {
          key: string;
          styles: Styles;
        };
        return [key, styles];
      }),
  );
  const approvals = JSON.parse(readFileSync(APPROVED, "utf8")) as Approval[];
  const differences = compareCaptures(snapshot, capture);
  const unapproved = differences.filter((d) => !isApproved(d, approvals));
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(
    path.join(REPORT_DIR, "differences.json"),
    `${JSON.stringify({ compared: Object.keys(snapshot).length, differences, unapproved }, null, 1)}\n`,
  );
  expect(unapproved, format(unapproved)).toEqual([]);
});
