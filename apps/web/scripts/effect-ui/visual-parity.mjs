/**
 * Visual parity gate: render the React route and the Effect UI route with the
 * same seeded data and compare the content region pixel by pixel.
 *
 * Usage (from apps/web):
 *   WEB_PORT=3740 API_PORT=8740 node scripts/effect-ui/visual-parity.mjs
 *
 * The first run writes `.context/proofs/effect-ui-visual/<name>-{react,effect,diff}.png`.
 * Exit code 1 when the diff ratio exceeds MAX_DIFF_RATIO (default 0.002 = 0.2%).
 */
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";
import sharp from "sharp";

const WEB_PORT = process.env.WEB_PORT ?? "3000";
const API_PORT = process.env.API_PORT ?? "8000";
const BASE_URL = `http://localhost:${WEB_PORT}`;
const API = `http://localhost:${API_PORT}/api/v1`;
const OUT = path.resolve(
  process.env.PROOF_DIR ?? "../../.context/proofs/effect-ui-visual",
);
const MAX_DIFF_RATIO = Number(process.env.MAX_DIFF_RATIO ?? "0.002");
const DEV_USER = process.env.DEV_USER ?? "dev@gaia.local";

const ROUTES = [
  {
    name: "todos",
    react: "/todos",
    effect: "/todos?effect=1",
    selector:
      "div.w-full.flex-1.overflow-y-auto.px-4 > div.flex.w-full.justify-center",
    waitFor: "[data-index]",
  },
  {
    name: "notifications",
    react: "/notifications",
    effect: "/notifications?effect=1",
    selector: "div.flex.h-full.w-full.flex-col.overflow-hidden.bg-primary-bg",
    waitFor: "text=No unread notifications",
  },
  {
    name: "pins",
    react: "/pins",
    effect: "/pins?effect=1",
    selector: "div.flex.h-full.flex-col.justify-between",
    waitFor: "input[placeholder='Enter a message to filter pins']",
  },
  {
    name: "settings-account",
    react: "/settings/account",
    effect: "/settings/account?effect=1",
    selector: "div.flex-1.overflow-y-auto > div.flex.w-full.justify-center.p-6",
    waitFor: 'section[aria-label="Profile"]',
  },
];

const json = (url, init) =>
  fetch(url, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });

async function seed() {
  await json(`${API}/dev/users/${encodeURIComponent(DEV_USER)}`, {
    method: "DELETE",
  }).catch(() => undefined);
  const mint = await json(`${API}/dev/users`, {
    method: "POST",
    body: JSON.stringify({ email: DEV_USER, name: "Dev User" }),
  });
  if (!mint.ok) throw new Error(`mint failed: ${mint.status} ${await mint.text()}`);
  const seeded = await json(`${API}/dev/seed`, {
    method: "POST",
    body: JSON.stringify({
      email: DEV_USER,
      todos: 5,
      conversations: 2,
      pro: true,
    }),
  });
  if (!seeded.ok) throw new Error(`seed failed: ${seeded.status} ${await seeded.text()}`);
}

async function capture(browser, url, selector, waitFor) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
    colorScheme: "dark",
    timezoneId: "UTC",
  });
  const page = await context.newPage();
  await page.goto(`${BASE_URL}${url}`, { waitUntil: "networkidle" });
  await page.locator(waitFor).first().waitFor({ state: "visible" });
  await page.evaluate(() => document.fonts.ready);
  // API order is not deterministic. Normalize row order by title so this gate
  // measures styling, not Mongo's return order.
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll("[data-index]")];
    const parent = rows[0]?.parentElement;
    if (!parent) return;
    rows.sort((a, b) => (a.textContent ?? "").localeCompare(b.textContent ?? ""));
    rows.forEach((row, index) => {
      parent.appendChild(row);
      row.style.transform = `translateY(${16 + index * 42}px)`;
    });
  });
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`no bounding box for ${selector} at ${url}`);
  const png = await page.screenshot({
    clip: {
      x: Math.floor(box.x),
      y: Math.floor(box.y),
      width: Math.ceil(box.width),
      height: Math.ceil(box.height),
    },
  });
  await context.close();
  return png;
}

async function compare(aPng, bPng) {
  const a = await sharp(aPng).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const b = await sharp(bPng).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  if (a.info.width !== b.info.width || a.info.height !== b.info.height) {
    return {
      ratio: 1,
      note: `size mismatch ${a.info.width}x${a.info.height} vs ${b.info.width}x${b.info.height}`,
    };
  }
  let different = 0;
  const diff = Buffer.alloc(a.data.length);
  for (let i = 0; i < a.data.length; i += 4) {
    const delta =
      Math.abs(a.data[i] - b.data[i]) +
      Math.abs(a.data[i + 1] - b.data[i + 1]) +
      Math.abs(a.data[i + 2] - b.data[i + 2]);
    if (delta > 24) {
      different++;
      diff[i] = 255;
      diff[i + 1] = 0;
      diff[i + 2] = 0;
      diff[i + 3] = 255;
    } else {
      diff[i] = a.data[i];
      diff[i + 1] = a.data[i + 1];
      diff[i + 2] = a.data[i + 2];
      diff[i + 3] = 80;
    }
  }
  const pixels = a.info.width * a.info.height;
  return {
    ratio: different / pixels,
    different,
    pixels,
    diff,
    width: a.info.width,
    height: a.info.height,
  };
}

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
let failed = false;
for (const route of ROUTES) {
  await seed();
  const react = await capture(browser, route.react, route.selector, route.waitFor);
  await seed();
  const effect = await capture(browser, route.effect, route.selector, route.waitFor);
  const result = await compare(react, effect);

  await writeFile(path.join(OUT, `${route.name}-react.png`), react);
  await writeFile(path.join(OUT, `${route.name}-effect.png`), effect);
  if (result.diff) {
    await sharp(result.diff, {
      raw: { width: result.width, height: result.height, channels: 4 },
    })
      .png()
      .toFile(path.join(OUT, `${route.name}-diff.png`));
  }

  const percent = (result.ratio * 100).toFixed(3);
  console.log(
    `${route.name}: ${percent}% different${
      result.note ? ` (${result.note})` : ""
    }${
      result.different !== undefined
        ? ` — ${result.different}/${result.pixels} pixels`
        : ""
    }`,
  );
  if (result.ratio > MAX_DIFF_RATIO) failed = true;
}
await browser.close();

if (failed) {
  console.error(`visual parity failed: > ${(MAX_DIFF_RATIO * 100).toFixed(2)}%`);
  process.exit(1);
}
console.log("visual parity passed");
