import { expect, type Page, test } from "@playwright/test";

/**
 * The built worker's pages must hydrate, not only render: a client chunk that
 * throws or fails to load still ships a 200 with the right title.
 */
const CHAT_ROUTE = "/c/00000000-0000-0000-0000-000000000000";
const STATIC_ASSETS = "/_next/static/";
const OAUTH_LOGIN = "/oauth/login/workos";

function isStaticAsset(url: string): boolean {
  return new URL(url).pathname.startsWith(STATIC_ASSETS);
}

/** Collect every uncaught error and every static asset that did not load. */
async function watchForBreakage(page: Page): Promise<string[]> {
  const problems: string[] = [];
  const { baseURL } = test.info().project.use;
  if (!baseURL) throw new Error("run through playwright.worker.config.ts");
  const origin = new URL(baseURL).origin;
  // Only the worker under test answers: the API, analytics and fonts stay offline.
  await page.route(
    (url) => url.origin !== origin,
    (route) => route.abort(),
  );
  page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
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
  await expect(page.locator('[data-slot="sidebar"]')).toBeAttached();
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
