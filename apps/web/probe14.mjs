import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
await page.goto("http://localhost:3200/blog/create", { waitUntil:"networkidle" });
await page.waitForTimeout(1200);
for (const ph of ["Enter blog post title","Enter category (e.g., AI Technology, Product Update)","Write your blog post content in Markdown..."]) {
  const el = page.getByPlaceholder(ph).first();
  console.log(ph.slice(0,25), await el.evaluate(n=>({ required:n.required, valid:n.checkValidity(), msg:n.validationMessage, ariaReq:n.getAttribute("aria-required"), inv:n.getAttribute("aria-invalid") })));
}
// submit then check if submit event fired (form submit counter)
await page.evaluate(() => { window.__submitted = 0; document.querySelector("form")?.addEventListener("submit", () => window.__submitted++); });
await page.getByRole("button", { name: "Create Blog Post" }).click();
await page.waitForTimeout(1200);
console.log("submit events:", await page.evaluate(() => window.__submitted));
console.log("focused:", await page.evaluate(()=>document.activeElement?.getAttribute("placeholder")));
console.log("title invalid after:", await page.getByPlaceholder("Enter blog post title").getAttribute("aria-invalid"));
await browser.close();
