import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
await page.goto("http://localhost:3200/contact", { waitUntil:"domcontentloaded" });
await page.waitForTimeout(3000);
const btn = page.locator("button[aria-haspopup='listbox']").first();
console.log(await btn.evaluate(n => ({ text: n.textContent.trim(), labelledby: n.getAttribute('aria-labelledby'), label: n.getAttribute('aria-label'), id: n.id, name: n.getAttribute('name') })));
const lb = await page.locator("label").allTextContents();
console.log("labels:", lb);
// accessible name via aria snapshot
console.log(await page.locator("form").first().ariaSnapshot().catch(()=>"n/a"));
await browser.close();
