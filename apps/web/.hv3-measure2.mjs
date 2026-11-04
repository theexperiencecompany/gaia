import { chromium } from '@playwright/test';
const url = process.argv[2] || 'http://localhost:3200/';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const t0 = Date.now();
await page.goto(url, { waitUntil: 'load', timeout: 60000 });
const loadEnd = Date.now() - t0;
await page.waitForTimeout(5000);
const data = await page.evaluate(() => {
  const res = performance.getEntriesByType('resource').map(r => ({
    url: r.name, type: r.initiatorType, start: r.startTime, dur: r.duration,
    encoded: r.encodedBodySize, decoded: r.decodedBodySize, transfer: r.transferSize,
  }));
  const nav = performance.getEntriesByType('navigation')[0];
  return { res, nav: { dcl: nav.domContentLoadedEventEnd, load: nav.loadEventEnd, ttfb: nav.responseStart }, paints: Object.fromEntries(performance.getEntriesByType('paint').map(p=>[p.name,p.startTime])) };
});
const by = {};
for (const r of data.res) { const k = r.type; by[k] = by[k] || {n:0,enc:0}; by[k].n++; by[k].enc += r.encoded; }
console.log(JSON.stringify({ loadEnd, ...data, by }, null, 1));
await browser.close();
