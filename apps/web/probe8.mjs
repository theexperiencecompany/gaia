import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport:{width:1400,height:1000} })).newPage();
const errs=[]; page.on("pageerror",e=>errs.push(e.message.slice(0,120)));

await page.goto("http://localhost:3200/blog", { waitUntil:"networkidle" });
await page.waitForTimeout(800);
const sels = page.locator("button[aria-haspopup='listbox']");
console.log("blog selects:", await sels.count());
for (let i=0;i<await sels.count();i++){
  const s=sels.nth(i);
  console.log(i, JSON.stringify((await s.textContent())?.trim()), "aria-label:", await s.getAttribute("aria-label"), "labelledby:", await s.getAttribute("aria-labelledby"));
}
if (await sels.count()) {
  await sels.first().click(); await page.waitForTimeout(400);
  const opts = page.getByRole("option");
  console.log("options:", (await opts.allTextContents()).map(t=>t.trim()).slice(0,8));

}
await browser.close();
