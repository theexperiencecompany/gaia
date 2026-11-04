import { chromium } from '@playwright/test';
import fs from 'node:fs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.coverage.startJSCoverage({ reportAnonymousScripts: false });
await page.goto('http://localhost:3200/', { waitUntil: 'load' });
await page.waitForTimeout(6000);
// scroll to trigger lazy sections
await page.evaluate(async () => { for (let y=0;y<document.body.scrollHeight;y+=800){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,120));} window.scrollTo(0,0); });
await page.waitForTimeout(4000);
const cov = await page.coverage.stopJSCoverage();
const out = cov.map(c => {
  const total = (c.text||"").length;
  const used = (c.ranges||[]).reduce((a,r)=>a+(r.end-r.start),0);
  return { url: c.url, total, used, unused: total-used };
}).sort((a,b)=>b.unused-a.unused);
fs.writeFileSync('/Users/aryan/Downloads/hv3review/coverage.json', JSON.stringify(out,null,1));
for (const o of out.slice(0,25)) console.log(`${(o.unused/1024).toFixed(1)}kB unused of ${(o.total/1024).toFixed(1)}kB (${(100*o.unused/o.total).toFixed(0)}%) ${o.url.split('/').pop()}`);
console.log('TOTAL unused kB', (out.reduce((a,b)=>a+b.unused,0)/1024).toFixed(1), 'total', (out.reduce((a,b)=>a+b.total,0)/1024).toFixed(1));
await browser.close();
