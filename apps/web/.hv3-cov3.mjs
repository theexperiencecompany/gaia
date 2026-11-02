import { chromium } from '@playwright/test';
import fs from 'node:fs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
await cdp.send('Profiler.enable');
await cdp.send('Debugger.enable');
await cdp.send('Profiler.startPreciseCoverage', { callCount: false, detailed: true });
await page.goto('http://localhost:3200/', { waitUntil: 'load' });
await page.waitForTimeout(6000);
await page.evaluate(async () => { for (let y=0;y<document.body.scrollHeight;y+=800){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,100));} window.scrollTo(0,0); });
await page.waitForTimeout(3000);
const { result } = await cdp.send('Profiler.takePreciseCoverage');
const out = [];
for (const s of result) {
  if (!s.url || !s.url.includes('_next/static/chunks')) continue;
  let src = '';
  try { src = (await cdp.send('Debugger.getScriptSource', { scriptId: s.scriptId })).scriptSource || ''; } catch {}
  const total = src.length;
  const segs = [];
  let sample=null;
  for (const f of s.functions) for (const r of f.ranges) { if(!sample) sample=r; if (r.count > 0) segs.push([r.startOffset, Math.min(r.endOffset, total)]); }
  if (s.url.includes('1ls6f')) console.log('DEBUG', total, s.functions.length, JSON.stringify(sample), segs.length);
  segs.sort((a,b)=>a[0]-b[0]);
  let used = 0, curS = -1, curE = -1;
  for (const [a,b] of segs) { if (b<=curE) continue; if (a>curE) { if (curE>curS&&curS>=0) used += curE-curS; curS=a; curE=b; } else curE=Math.max(curE,b); }
  if (curE>curS&&curS>=0) used += curE-curS;
  out.push({ url: s.url, total, used, unused: Math.max(0,total-used) });
}
out.sort((a,b)=>b.unused-a.unused);
fs.writeFileSync('/Users/aryan/Downloads/hv3review/coverage.json', JSON.stringify(out,null,1));
for (const o of out.slice(0,20)) console.log(`${(o.unused/1024).toFixed(1)}kB unused / ${(o.total/1024).toFixed(1)}kB (${(100*o.unused/o.total).toFixed(0)}%) ${o.url.split('/').pop()}`);
console.log('TOTAL unused kB', (out.reduce((a,b)=>a+b.unused,0)/1024).toFixed(1), 'total', (out.reduce((a,b)=>a+b.total,0)/1024).toFixed(1));
await browser.close();
