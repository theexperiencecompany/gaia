import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport:{width:1400,height:1200} })).newPage();
const errs=[]; page.on("pageerror",e=>errs.push(e.message.slice(0,150)));
await page.goto("http://localhost:3200/blog/create", { waitUntil:"networkidle" });
await page.waitForTimeout(1000);
const buttons = await page.getByRole("button").allTextContents();
console.log("buttons:", buttons.map(b=>b.trim()).filter(Boolean).slice(0,12));
const submit = page.getByRole("button", { name: /publish|create|save|submit/i }).first();
console.log("submit label:", (await submit.textContent())?.trim());
await submit.click().catch(e=>console.log("click fail", e.message.slice(0,80)));
await page.waitForTimeout(1500);
const body = await page.locator("body").innerText();
console.log("has error text:", /required|invalid|please|must/i.test(body));
const ariaInvalid = await page.locator("[aria-invalid=true]").count();
console.log("aria-invalid count:", ariaInvalid);
console.log("errors:", errs.join(";"));
// check label association
for (const ph of ["Enter blog post title","Write your blog post content in Markdown"]) {
  const el = page.getByPlaceholder(ph).first();
  if (await el.count()) {
    const info = await el.evaluate(n=>({tag:n.tagName, lab:n.getAttribute('aria-label'), lb:n.getAttribute('aria-labelledby'), inv:n.getAttribute('aria-invalid'), req:n.getAttribute('required')}));
    console.log(ph.slice(0,20), info);
  }
}
await page.screenshot({ path: "/tmp/blog-create.png", fullPage: false });
await browser.close();
