import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1000 } })).newPage();
const errs = [];
page.on("pageerror", e => errs.push("PAGEERROR " + e.message));
await page.goto("http://localhost:3200/contact", { waitUntil: "networkidle" });
await page.waitForTimeout(800);

// mark the DOM node to detect remount
const title = page.getByPlaceholder("Brief description of your request");
console.log("title count", await title.count());
await title.evaluate(n => { n.dataset.marker = "original"; });
await title.click();
await page.keyboard.type("Hello migration");
console.log("after type value=", JSON.stringify(await title.inputValue()));
console.log("marker survived? ", await title.evaluate(n => n.dataset.marker));
console.log("count now", await title.count());

const desc = page.getByPlaceholder("Please provide detailed information about your request...");
await desc.click();
await page.keyboard.type("Body text");
console.log("desc value=", JSON.stringify(await desc.inputValue()));
console.log("title still =", JSON.stringify(await title.inputValue()));

const trigger = page.locator("button[aria-haspopup='listbox']").first();
console.log("trigger count", await trigger.count(), "text:", (await trigger.textContent())?.trim());
await trigger.click();
await page.waitForTimeout(600);
const opts = page.getByRole("option");
console.log("options:", (await opts.allTextContents()).map(s=>s.trim()));
if (await opts.count()) {
  await opts.nth(1).click();
  await page.waitForTimeout(600);
  console.log("trigger text after:", (await trigger.textContent())?.trim());
  console.log("title preserved after select:", JSON.stringify(await title.inputValue()));
}
console.log("ERRORS:", errs.join("\n"));
await browser.close();
