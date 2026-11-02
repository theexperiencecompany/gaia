import { chromium } from "@playwright/test";
const browser = await chromium.launch();
for (const p of ["/login","/signup","/blog/create","/features","/support"]) {
  const page = await (await browser.newContext()).newPage();
  const errs=[]; page.on("pageerror",e=>errs.push(e.message.slice(0,100)));
  try {
    const r = await page.goto("http://localhost:3200"+p, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForTimeout(2500);
    const n = await page.locator("input:not([type=hidden]),textarea,[role=combobox]").count();
    console.log(p, r?.status(), "url:", page.url(), "fields:", n, "err:", errs.join(";").slice(0,80));
  } catch(e){ console.log(p, "FAIL", e.message.slice(0,100)); }
  await page.close();
}
await browser.close();
