import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1000 } })).newPage();
const errs = [];
page.on("pageerror", e => errs.push("PAGEERROR " + e.message));
await page.goto("http://localhost:3200/contact", { waitUntil: "networkidle" });
await page.waitForTimeout(800);

const inputs = page.locator("input:not([type=hidden]), textarea");
console.log("count inputs/textarea =", await inputs.count());
for (let i = 0; i < await inputs.count(); i++) {
  const el = inputs.nth(i);
  console.log(i, await el.evaluate(n => n.tagName + " name=" + (n.name||"") + " aria=" + (n.getAttribute('aria-label')||"") + " labelledby=" + (n.getAttribute('aria-labelledby')||"") + " id=" + n.id + " ph=" + (n.placeholder||"")));
}
// type into title
const title = inputs.nth(1);
await title.click(); await title.fill("Hello from migration review");
console.log("title value after fill =", JSON.stringify(await title.inputValue()));
// type char by char to test controlled binding
await title.click(); await page.keyboard.type("X");
console.log("title value after keystroke =", JSON.stringify(await title.inputValue()));
const desc = page.locator("textarea").first();
await desc.click(); await desc.fill("Description body typed by reviewer");
console.log("desc value =", JSON.stringify(await desc.inputValue()));

// Select
const trigger = page.getByRole("button").filter({ hasText: /Select a request type|Feature|Support/i }).first();
console.log("trigger count", await trigger.count());
await trigger.click();
await page.waitForTimeout(500);
const options = await page.getByRole("option").allTextContents();
console.log("options:", options.map(o=>o.trim()));
if (options.length) {
  await page.getByRole("option").first().click();
  await page.waitForTimeout(400);
  console.log("trigger text after select:", (await trigger.textContent())?.trim());
}
console.log("html snippets of select:", (await page.locator("[role=combobox],button[aria-haspopup=listbox]").first().getAttribute("aria-labelledby")) );
console.log("ERRORS:", errs.join("\n"));
await browser.close();
