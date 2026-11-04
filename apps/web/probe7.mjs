import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport:{width:1280,height:1000} })).newPage();
const errs=[]; page.on("pageerror",e=>errs.push(e.message.slice(0,150)));
page.on("console", m=>{ if(m.type()==="error" && m.text().includes("301")) errs.push("REACT301"); });
await page.goto("http://localhost:3200/features", { waitUntil:"networkidle" });
await page.waitForTimeout(600);
const f = page.locator("input").first();
console.log("features field ph:", await f.getAttribute("placeholder"), "aria:", await f.getAttribute("aria-label"), "labelledby:", await f.getAttribute("aria-labelledby"));
await f.click(); await page.keyboard.type("calendar");
console.log("value after type:", JSON.stringify(await f.inputValue()));
await page.waitForTimeout(400);
console.log("still there:", await page.locator("input").first().count(), "errs:", errs.join(","));
await page.goto("http://localhost:3200/blog/create", { waitUntil:"networkidle" });
await page.waitForTimeout(1000);
const inputs = page.locator("input:not([type=hidden]),textarea");
const n = await inputs.count();
console.log("blog fields:", n);
for (let i=0;i<n;i++){ const e=inputs.nth(i); console.log(i, await e.evaluate(x=>x.tagName+" ph="+(x.placeholder||"").slice(0,40)+" name="+(x.name||"")+" aria="+(x.getAttribute("aria-label")||"")+" labelledby="+(x.getAttribute("aria-labelledby")||""))); }
const t = page.locator("input").first();
if (await t.count()) { await t.click(); await page.keyboard.type("My migration post"); console.log("title:", JSON.stringify(await t.inputValue())); }
const ta = page.locator("textarea").first();
if (await ta.count()) { await ta.click(); await page.keyboard.type("Body copy"); console.log("ta:", JSON.stringify(await ta.inputValue())); }
await page.waitForTimeout(500);
console.log("errs:", errs.join(","), "boundary:", (await page.locator("body").innerText()).includes("Something went wrong"));
await browser.close();
