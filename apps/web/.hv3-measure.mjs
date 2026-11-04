import { chromium } from '@playwright/test';

const url = process.argv[2] || 'http://localhost:3200/';
const browser = await chromium.launch({ args: ['--no-sandbox'] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const rec = [];
const responses = [];
page.on('response', async (r) => {
  const req = r.request();
  const t = Date.now() - t0;
  let size = 0;
  try {
    const h = await r.allHeaders();
    size = Number(h['x-encoded-content-length'] || h['content-length'] || 0);
  } catch {}
  responses.push({ url: r.url(), status: r.status(), type: req.resourceType(), size, t, fromSW: r.fromServiceWorker() });
});
const t0 = Date.now();
await page.goto(url, { waitUntil: 'load', timeout: 60000 });
const loadEnd = Date.now() - t0;
await page.waitForTimeout(4000);
const idle = Date.now() - t0;
// metrics
const paint = await page.evaluate(() => {
  const nav = performance.getEntriesByType('navigation')[0];
  const paints = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, p.startTime]));
  const lcp = window.__lcp || null;
  return { domContentLoaded: nav?.domContentLoadedEventEnd, loadEvent: nav?.loadEventEnd, paints };
});
const totals = {};
for (const r of responses) {
  const k = r.type;
  totals[k] = totals[k] || { n: 0, size: 0 };
  totals[k].n++; totals[k].size += r.size;
}
console.log(JSON.stringify({ loadEnd, idle, paint, totals, responses: responses.sort((a,b)=>b.size-a.size) }, null, 1));
await browser.close();
