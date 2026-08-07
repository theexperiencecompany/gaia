const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const base = process.env.WEB_URL || 'http://localhost:3140';
  await page.goto(`${base}/c`, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(10000);

  const info = await page.evaluate(() => {
    const t = document.body.innerText.slice(0, 1200);
    const tas = [...document.querySelectorAll('textarea, [contenteditable="true"]')].map(e => ({
      tag: e.tagName, cls: (e.className||'').toString().slice(0,60), visible: !!(e.offsetWidth||e.offsetHeight)
    }));
    return { text: t.replace(/\n+/g, ' | '), textareas: tas };
  });
  console.log('TEXT:', info.text.slice(0, 700));
  console.log('TEXTAREAS:', JSON.stringify(info.textareas));
  await page.screenshot({ path: '/tmp/chat_state.png', fullPage: true });
  await browser.close();
})();
