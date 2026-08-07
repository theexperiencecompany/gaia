const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const base = process.env.WEB_URL || 'http://localhost:3140';

  await page.goto(`${base}/c/new`, { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForTimeout(6000);

  // find the composer and type
  const textareas = page.locator('textarea, [contenteditable="true"], input[type="text"]');
  const n = await textareas.count();
  console.log('composer candidates:', n);
  const composer = textareas.last();
  if (await composer.count()) {
    await composer.click();
    await composer.fill('Run the onboarding checklist procedure, then confirm what it did.');
    await page.keyboard.press('Enter');
    console.log('sent message');
  } else {
    console.log('NO COMPOSER FOUND');
    const body = await page.evaluate(() => document.body.innerText.slice(0, 1000));
    console.log('BODY:', body.replace(/\n+/g,' | '));
  }

  // wait for the bot reply to stream in
  await page.waitForTimeout(60000);
  const body = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  console.log('AFTER:', body.replace(/\n+/g, ' | ').slice(0, 1500));
  await page.screenshot({ path: '/tmp/chat_real.png', fullPage: true });
  console.log('saved chat_real.png');
  await browser.close();
})();
