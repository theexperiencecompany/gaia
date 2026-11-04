import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.addInitScript(() => {
  window.__vit = { lcp: 0, lcpEl: null, cls: 0, long: [] };
  new PerformanceObserver(l => { for (const e of l.getEntries()) { window.__vit.lcp = e.startTime; window.__vit.lcpEl = e.element ? (e.element.tagName + '.' + (e.element.className||'').toString().slice(0,40) + ' url=' + (e.url||'')) : null; } }).observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__vit.cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
  new PerformanceObserver(l => { for (const e of l.getEntries()) window.__vit.long.push({ s: Math.round(e.startTime), d: Math.round(e.duration) }); }).observe({ type: 'longtask', buffered: true });
});
await page.goto('http://localhost:3200/', { waitUntil: 'load' });
await page.waitForTimeout(8000);
const out = await page.evaluate(() => {
  const v = window.__vit;
  // fonts actually used above the fold
  const used = {};
  const vh = window.innerHeight;
  for (const el of document.querySelectorAll('h1,h2,h3,p,span,a,button,li')) {
    const r = el.getBoundingClientRect();
    if (r.top > vh || r.bottom < 0 || !el.textContent?.trim()) continue;
    const cs = getComputedStyle(el);
    const key = `${cs.fontFamily.split(',')[0].replace(/"/g,'')} ${cs.fontWeight} ${cs.fontStyle}`;
    used[key] = (used[key] || 0) + 1;
  }
  const faces = [...document.fonts].map(f => `${f.family} ${f.weight} ${f.style} ${f.status}`);
  return { vit: v, used, faces, transfer: performance.getEntriesByType('resource').reduce((a,r)=>a+r.encodedBodySize,0)/1024, nav: performance.getEntriesByType('navigation')[0].toJSON() };
});
console.log(JSON.stringify(out, null, 1));
await browser.close();
