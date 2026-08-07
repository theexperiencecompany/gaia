const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const base = process.env.WEB_URL || 'http://localhost:3140';

  await page.goto(`${base}/c`, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(e => console.log('nav warn:', e.message.slice(0,100)));
  await page.waitForTimeout(8000);

  const body0 = await page.evaluate(() => document.body.innerText.slice(0, 800));
  console.log('INIT:', body0.replace(/\n+/g, ' | ').slice(0, 400));

  const textareas = page.locator('textarea, [contenteditable="true"]');
  const n = await textareas.count();
  console.log('composer candidates:', n);
  if (n > 0) {
    const composer = textareas.last();
    await composer.click();
    await composer.fill('Run the onboarding checklist procedure, then confirm what it did.');
    await page.keyboard.press('Enter');
    console.log('sent message');
  } else {
    console.log('NO COMPOSER');
  }

  await page.waitForTimeout(90000);
  const body = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  console.log('AFTER:', body.replace(/\n+/g, ' | ').slice(0, 1600));
  await page.screenshot({ path: '/tmp/chat_real.png', fullPage: true });
  console.log('saved chat_real.png');
  await browser.close();
})();
