const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const base = process.env.WEB_URL || 'http://localhost:3140';
  await page.goto(`${base}/c`, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(8000);

  const ta = page.locator('textarea').first();
  await ta.click({ force: true });
  await ta.pressSequentially('Run the onboarding checklist procedure, then confirm what it did.', { delay: 20 });
  await page.waitForTimeout(1000);
  await page.keyboard.press('Enter');
  console.log('sent');

  await page.waitForTimeout(100000);
  const body = await page.evaluate(() => document.body.innerText.slice(0, 4000));
  console.log('AFTER:', body.replace(/\n+/g, ' | ').slice(0, 1800));
  await page.screenshot({ path: '/tmp/chat_real.png', fullPage: true });
  console.log('saved chat_real.png');
  await browser.close();
})();
