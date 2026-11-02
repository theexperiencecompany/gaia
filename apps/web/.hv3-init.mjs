import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport:{width:1440,height:900} });
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
await cdp.send('Network.enable');
const found = [];
cdp.on('Network.requestWillBeSent', (e) => {
  const u = e.request.url;
  if (/\.(webp|png|jpg|jpeg|avif|svg|woff2?)(\?|$)/.test(u)) {
    found.push({ url: u.replace('http://localhost:3200',''), type: e.type, init: JSON.stringify(e.initiator).slice(0,400) });
  }
});
await page.goto('http://localhost:3200/', {waitUntil:'load'});
await page.waitForTimeout(4000);
await page.evaluate(async()=>{for(let y=0;y<document.body.scrollHeight;y+=900){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,80));}});
await page.waitForTimeout(2000);
for (const f of found) console.log(f.url, '|', f.type, '|', f.init.slice(0,260));
await browser.close();
