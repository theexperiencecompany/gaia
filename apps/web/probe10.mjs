import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("framenavigated", f => { if (f === page.mainFrame()) console.log("NAV", f.url().slice(0,120)); });
await page.goto("http://localhost:3200/login", { waitUntil:"domcontentloaded" }).catch(e=>console.log("goto err", e.message.slice(0,60)));
await page.waitForTimeout(4000);
console.log("final:", page.url().slice(0,150));
await browser.close();
