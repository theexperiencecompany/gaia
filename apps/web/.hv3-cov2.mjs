import { chromium } from '@playwright/test';
import fs from 'node:fs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
await cdp.send('Profiler.enable');
await cdp.send('Profiler.startPreciseCoverage', { callCount: false, detailed: true });
await cdp.send('Debugger.enable');
await page.goto('http://localhost:3200/', { waitUntil: 'load' });
await page.waitForTimeout(6000);
await page.evaluate(async () => { for (let y=0;y<document.body.scrollHeight;y+=800){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,100));} window.scrollTo(0,0); });
await page.waitForTimeout(3000);
const { result } = await cdp.send('Profiler.takePreciseCoverage');
const scripts = [];
for (const s of result) {
  if (!s.url || !s.url.includes('_next/static/chunks')) continue;
  let src = '';
  try { const r = await cdp.send('Debugger.getScriptSource', { scriptId: s.scriptId }); src = r.scriptSource || ''; } catch {}
  const total = src.length;
  let used = 0;
  for (const f of s.functions) for (const r of f.ranges) used += (r.endOffset - r.startOffset);
  scripts.push({ url: s.url, total, used, unused: Math.max(0,total-used) });
}
scripts.sort((a,b)=>b.unused-a.unused);
fs.writeFileSync('/Users/aryan/Downloads/hv3review/coverage.json', JSON.stringify(scripts,null,1));
for (const o of scripts.slice(0,20)) console.log(`${(o.unused/1024).toFixed(1)}kB unused / ${(o.total/1024).toFixed(1)}kB (${(100*o.unused/o.total).toFixed(0)}%) ${o.url.split('/').pop()}`);
console.log('TOTAL unused kB', (scripts.reduce((a,b)=>a+b.unused,0)/1024).toFixed(1), 'total', (scripts.reduce((a,b)=>a+b.total,0)/1024).toFixed(1));
await browser.close();
