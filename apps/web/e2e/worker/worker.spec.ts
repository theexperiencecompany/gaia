import { expect, type Page, test } from "@playwright/test";
import { MARKETING_PAGES } from "../marketing-pages";
import { type RenderedStyles, unstyledUtilities } from "./unstyled-utilities";

/**
 * The built worker's pages must hydrate, not only render: a client chunk that
 * throws or fails to load still ships a 200 with the right title.
 */
const CHAT_ROUTE = "/c/00000000-0000-0000-0000-000000000000";
const STATIC_ASSETS = "/_next/static/";
const OAUTH_LOGIN = "/oauth/login/workos";
// No page answers it, so the root not-found renders with base.css alone.
const NOT_FOUND_ROUTE = "/marketplace/does-not-exist";
const STYLED_ROUTES = [
  ...MARKETING_PAGES,
  "/connect",
  CHAT_ROUTE,
  NOT_FOUND_ROUTE,
];

function isStaticAsset(url: string): boolean {
  return new URL(url).pathname.startsWith(STATIC_ASSETS);
}

/** Only the worker under test answers: the API, analytics and fonts stay offline. */
async function stayOnWorker(page: Page): Promise<void> {
  const { baseURL } = test.info().project.use;
  if (!baseURL) throw new Error("run through playwright.worker.config.ts");
  const origin = new URL(baseURL).origin;
  await page.route(
    (url) => url.origin !== origin,
    (route) => route.abort(),
  );
}

/** Collect every uncaught error, every static asset that did not load, and every CSP violation. */
async function watchForBreakage(page: Page): Promise<string[]> {
  const problems: string[] = [];
  await stayOnWorker(page);
  page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
  // Report-only violations fire this event too, so the worker's CSP is proven before it enforces.
  await page.exposeFunction("reportCspViolation", (violation: string) =>
    problems.push(`csp: ${violation}`),
  );
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      (
        window as unknown as { reportCspViolation: (v: string) => void }
      ).reportCspViolation(`${event.effectiveDirective} ${event.blockedURI}`);
    });
  });
  page.on("requestfailed", (request) => {
    if (isStaticAsset(request.url())) {
      problems.push(`failed: ${request.url()} ${request.failure()?.errorText}`);
    }
  });
  page.on("response", (response) => {
    if (isStaticAsset(response.url()) && !response.ok()) {
      problems.push(`${response.status()}: ${response.url()}`);
    }
  });
  return problems;
}

test("the (main) app shell hydrates", async ({ page }) => {
  const problems = await watchForBreakage(page);

  await page.goto(CHAT_ROUTE, { waitUntil: "load" });

  expect(problems).toEqual([]);
  await expect(page.locator('[data-slot="sidebar-inset"]')).toBeVisible();
  await expect(page.locator("#main-content")).toBeAttached();
  // With the API offline no plan is ever read, so the paid sidebar must stay out.
  await expect(page.locator('[data-slot="sidebar"]')).toHaveCount(0);
});

test("the login page hydrates and hands off to the OAuth login", async ({
  page,
}) => {
  const problems = await watchForBreakage(page);
  // The redirect is client code, so reaching the API proves the page hydrated.
  const handoff = page.waitForRequest(
    (request) => new URL(request.url()).pathname.endsWith(OAUTH_LOGIN),
    { timeout: 10_000 },
  );

  await page.goto("/login", { waitUntil: "commit" });

  await handoff;
  expect(problems).toEqual([]);
});

/** Runs in the page: every class on an element, and the selector of every style rule loaded. */
function collectRenderedStyles(): RenderedStyles {
  const classes = new Set<string>();
  for (const element of document.querySelectorAll("[class]")) {
    for (const name of element.classList) classes.add(name);
  }
  const selectors: string[] = [];
  const walk = (rules: CSSRuleList) => {
    for (const rule of rules) {
      if (rule instanceof CSSStyleRule) selectors.push(rule.selectorText);
      if (rule instanceof CSSGroupingRule) walk(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets) {
    // Another origin's sheet is unreadable from the page and holds none of the build's utilities.
    if (sheet.href && new URL(sheet.href).origin !== location.origin) continue;
    walk(sheet.cssRules);
  }
  return { classes: [...classes], selectors };
}

for (const route of STYLED_ROUTES) {
  test(`${route} renders no Tailwind utility its stylesheets lack`, async ({
    page,
  }) => {
    await stayOnWorker(page);

    await page.goto(route, { waitUntil: "load" });
    // The not-found page is rendered by the client, so the document arrives without an element to style.
    await page.locator("body [class]").first().waitFor({ state: "attached" });
    await page.waitForLoadState("networkidle");

    const rendered = await page.evaluate(collectRenderedStyles);
    expect(await unstyledUtilities(rendered)).toEqual([]);
  });
}
