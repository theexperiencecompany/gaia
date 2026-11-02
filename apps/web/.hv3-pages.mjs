import { chromium } from '@playwright/test';
const urls = ['http://localhost:3200/','http://localhost:3200/en/pricing','http://localhost:3200/en/privacy','http://localhost:3200/en/terms','http://localhost:3200/en/about','http://localhost:3200/en/blog'];
const browser = await chromium.launch();
for (const u of urls) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  if (u.endsWith('/')) {
    // seed locale cookie? plain / works
  }
  let resp;
  try { resp = await page.goto(u, { waitUntil: 'load', timeout: 45000 }); } catch (e) { console.log(u, 'ERR', e.message.split('\n')[0]); await ctx.close(); continue; }
  await page.waitForTimeout(2500);
  const d = await page.evaluate(() => {
    const rs = performance.getEntriesByType('resource');
    const js = rs.filter(r => r.name.endsWith('.js'));
    const svgPaths = new Set();
    document.querySelectorAll('svg path').forEach(p => { const d = p.getAttribute('d') || ''; if (d.length > 40) svgPaths.add(d.slice(0,60)); });
    return {
      jsKB: js.reduce((a,r)=>a+r.encodedBodySize,0)/1024,
      njs: js.length,
      cssKB: rs.filter(r=>r.name.endsWith('.css')).reduce((a,r)=>a+r.encodedBodySize,0)/1024,
      imgKB: rs.filter(r=>r.initiatorType==='img').reduce((a,r)=>a+r.encodedBodySize,0)/1024,
      iconsChunk: js.some(r=>r.name.includes('1ls6f738yrrcz')),
      distinctSvg: svgPaths.size,
      svgCount: document.querySelectorAll('svg').length,
      total: rs.reduce((a,r)=>a+r.encodedBodySize,0)/1024,
    };
  });
  console.log(u.padEnd(45), JSON.stringify(d));
  await ctx.close();
}
await browser.close();
