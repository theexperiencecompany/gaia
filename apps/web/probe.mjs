import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", e => errs.push("PAGEERROR " + e.message));
page.on("console", m => { if (m.type() === "error") errs.push("CONSOLE " + m.text().slice(0,200)); });
for (const path of ["/contact", "/login", "/dev/text-animation", "/settings/preferences", "/todos"]) {
  const res = await page.goto("http://localhost:3200" + path, { waitUntil: "networkidle" }).catch(e => ({status: () => "ERR " + e.message}));
  await page.waitForTimeout(1200);
  const inputs = await page.locator("input, textarea, [role=combobox], [role=switch], [role=checkbox], [role=radiogroup]").count();
  console.log(path, res.status?.(), "url=", page.url(), "fields=", inputs, "title=", (await page.title()).slice(0,40));
}
console.log("ERRORS:", errs.slice(0,10).join("\n"));
await browser.close();
