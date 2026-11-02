import { chromium } from '@playwright/test';
const pages = {landing:'http://localhost:3200/', terms:'http://localhost:3200/en/terms'};
const browser = await chromium.launch();
const out = {};
for (const [k,u] of Object.entries(pages)) {
  const ctx = await browser.newContext({ viewport:{width:1440,height:900} });
  const p = await ctx.newPage();
  await p.goto(u,{waitUntil:'load'}); await p.waitForTimeout(3000);
  out[k] = await p.evaluate(()=>performance.getEntriesByType('resource').filter(r=>r.name.endsWith('.js')).map(r=>({n:r.name.split('/').pop(),kb:Math.round(r.encodedBodySize/1024),start:Math.round(r.startTime)})));
  await ctx.close();
}
await browser.close();
import fs from 'node:fs';
fs.writeFileSync('/Users/aryan/Downloads/hv3review/diff.json', JSON.stringify(out,null,1));
const base = new Set(out.terms.map(x=>x.n));
const landOnly = out.landing.filter(x=>!base.has(x.n));
console.log('terms js count',out.terms.length,'landing',out.landing.length,'landing-only',landOnly.length);
let sum=0; for (const x of landOnly){sum+=x.kb; console.log(x.kb+'kB', x.start+'ms', x.n);}
console.log('landing-only total kB', sum);
console.log('terms total kB', out.terms.reduce((a,b)=>a+b.kb,0));
