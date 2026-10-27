import { expect, type Page, type Route, test } from "@playwright/test";

/**
 * Hosted GAIA end-to-end: auth handoff, onboarding, checkout and chat with
 * every backend call mocked at the browser boundary. Needs only the Next dev
 * server — no API, database, containers or secrets.
 */

const API_PREFIX = "/api/v1";
const DODO_ORIGIN = "https://test.checkout.dodopayments.com";
const DODO_CHECKOUT_URL = `${DODO_ORIGIN}/session/cks_e2e000000000000000000`;

const USER_ID = "64b7f0e2c2a4e2a1b3c4d5e6";
const USER_EMAIL = "ada@hosted-e2e.test";
const CHAT_CONVERSATION_ID = "conv_hosted_e2e";
const CHAT_PROMPT = "Hello from the hosted e2e";
const CHAT_REPLY = "Hosted chat reply: hello!";

const PLAN_PRO_MONTHLY = {
  id: "plan_pro_monthly",
  dodo_product_id: "pdt_pro_monthly",
  name: "Pro",
  plan_type: "pro",
  description: "GAIA Pro, billed monthly.",
  amount: 30,
  currency: "USD",
  duration: "monthly",
  max_users: 1,
  features: ["Unlimited chat", "All integrations"],
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as const;

const PLAN_PRO_YEARLY = {
  ...PLAN_PRO_MONTHLY,
  id: "plan_pro_yearly",
  dodo_product_id: "pdt_pro_yearly",
  duration: "yearly",
  amount: 300,
} as const;

/** Mutable per-test backend state; the route handler is the only writer. */
interface MockBackend {
  paid: boolean;
  onboardingCompleted: boolean;
  checkoutRequest: Record<string, unknown> | null;
  onboardingRequest: Record<string, unknown> | null;
  preferencesRequest: Record<string, unknown> | null;
  chatRequest: Record<string, unknown> | null;
  chatRequestCount: number;
}

function createBackend(overrides: Partial<MockBackend> = {}): MockBackend {
  return {
    paid: false,
    onboardingCompleted: false,
    checkoutRequest: null,
    onboardingRequest: null,
    preferencesRequest: null,
    chatRequest: null,
    chatRequestCount: 0,
    ...overrides,
  };
}

function userPayload(backend: MockBackend) {
  return {
    message: "User info fetched successfully",
    user_id: USER_ID,
    auth_provider: "workos",
    onboarding: {
      completed: backend.onboardingCompleted,
      completed_at: backend.onboardingCompleted ? "2026-01-02T00:00:00Z" : null,
      phase: backend.onboardingCompleted ? "complete" : "personalization",
      preferences: backend.onboardingCompleted
        ? { profession: "founder", needs: ["inbox"], other_need: null }
        : {},
      first_message_conversation_id: null,
      // A null seed id lands the user on `/c` instead of a seeded thread.
      getting_started_conversation_id: null,
    },
    email: USER_EMAIL,
    name: "Ada Lovelace",
    picture: null,
    timezone: "UTC",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    role: null,
  };
}

function subscriptionStatus(backend: MockBackend) {
  return {
    user_id: USER_ID,
    current_plan: backend.paid ? PLAN_PRO_MONTHLY : null,
    subscription: backend.paid
      ? { status: "active", subscription_id: "sub_hosted_e2e" }
      : null,
    is_subscribed: backend.paid,
    days_remaining: backend.paid ? 30 : null,
    can_upgrade: !backend.paid,
    can_downgrade: backend.paid,
    has_ever_subscribed: backend.paid,
    has_subscription: backend.paid,
    plan_type: backend.paid ? "pro" : "free",
    status: backend.paid ? "active" : null,
  };
}

function sseBody() {
  const frames = [
    // Flat identity frame; omit conversation_id so an open conversation binds
    // synchronously (route.fulfill sends the whole body in one chunk).
    {
      conversation_description: "Hosted e2e chat",
      user_message_id: "msg_user_hosted_e2e",
      user_message_content: CHAT_PROMPT,
      bot_message_id: "msg_bot_hosted_e2e",
      stream_id: "stream_hosted_e2e",
    },
    { response: CHAT_REPLY },
    { main_response_complete: true },
  ];

  return `${frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("")}data: [DONE]\n\n`;
}

let mockWebOrigin = "";

function corsHeaders(): Record<string, string> {
  if (!mockWebOrigin) return {};
  return {
    "access-control-allow-origin": mockWebOrigin,
    "access-control-allow-credentials": "true",
    vary: "origin",
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: { "cache-control": "no-store", ...corsHeaders() },
    body: JSON.stringify(body),
  });
}

function redirect(route: Route, location: string, cookie?: string) {
  return route.fulfill({
    status: 302,
    headers: {
      ...corsHeaders(),
      location,
      ...(cookie ? { "set-cookie": cookie } : {}),
    },
  });
}

function postBody(route: Route): Record<string, unknown> {
  try {
    return (route.request().postDataJSON() ?? {}) as Record<string, unknown>;
  } catch {
    return {};
  }
}

const CHECKOUT_RESPONSE = {
  subscription_id: "cks_e2e000000000000000000",
  payment_link: DODO_CHECKOUT_URL,
  status: "created",
};

type ApiHandler = (route: Route, backend: MockBackend) => Promise<void>;

/** Exact `METHOD /api/v1/path` handlers; anything absent falls through below. */
const API_ROUTES: Record<string, ApiHandler> = {
  // --- Auth handoff -------------------------------------------------------
  [`GET ${API_PREFIX}/oauth/login/workos`]: (route) => {
    // Mock AuthKit, served from the API origin so /login's external handoff
    // really navigates here; the link returns to the callback with a code.
    const callback = `${API_PREFIX}/oauth/workos/callback?code=e2e-code&state=e2e-state`;
    return route.fulfill({
      status: 200,
      contentType: "text/html",
      headers: corsHeaders(),
      body: `<!doctype html><html><body style="font-family:sans-serif;padding:32px">
        <h1>Mock AuthKit</h1>
        <p>Sign in to GAIA (hosted e2e).</p>
        <a href="${callback}">Continue</a>
      </body></html>`,
    });
  },
  // The real callback exchanges the code, sets the session cookie and sends
  // the browser to FRONTEND_URL/redirect. Both halves are local here; the
  // target must be absolute because the callback is served from the API origin.
  [`GET ${API_PREFIX}/oauth/workos/callback`]: (route) =>
    redirect(
      route,
      `${mockWebOrigin}/redirect`,
      "wos_session=e2e-session; Path=/; HttpOnly; SameSite=Lax",
    ),

  // --- Current user + onboarding -----------------------------------------
  [`GET ${API_PREFIX}/user/me`]: (route, backend) =>
    json(route, userPayload(backend)),
  [`PATCH ${API_PREFIX}/onboarding/preferences`]: (route, backend) => {
    backend.preferencesRequest = postBody(route);
    return json(route, {
      success: true,
      message: "Preferences updated successfully",
      user: {},
    });
  },
  [`POST ${API_PREFIX}/onboarding`]: (route, backend) => {
    backend.onboardingRequest = postBody(route);
    backend.onboardingCompleted = true;
    return json(route, {
      success: true,
      message: "Onboarding completed successfully",
      user: {},
    });
  },
  [`POST ${API_PREFIX}/platform-links/code`]: (route) =>
    json(route, {
      code: "E2E123",
      first_message: "Hey GAIA",
      handoff_text: "Hey GAIA #E2E123",
      links: {
        telegram: "https://t.me/gaia_e2e_bot?start=E2E123",
        whatsapp: "https://wa.me/15550000000?text=Hey%20GAIA%20%23E2E123",
      },
    }),

  // --- Pricing + checkout -------------------------------------------------
  [`GET ${API_PREFIX}/payments/plans`]: (route) =>
    json(route, [PLAN_PRO_MONTHLY, PLAN_PRO_YEARLY]),
  [`GET ${API_PREFIX}/payments/subscription-status`]: (route, backend) =>
    json(route, subscriptionStatus(backend)),
  [`GET ${API_PREFIX}/payments/discount-codes`]: (route) =>
    json(route, { founder_letter: null }),
  [`POST ${API_PREFIX}/payments/checkout-session`]: (route, backend) => {
    backend.checkoutRequest = postBody(route);
    return json(route, CHECKOUT_RESPONSE);
  },
  [`POST ${API_PREFIX}/payments/subscriptions`]: (route, backend) => {
    backend.checkoutRequest = postBody(route);
    return json(route, CHECKOUT_RESPONSE);
  },
  [`POST ${API_PREFIX}/payments/verify-payment`]: (route, backend) =>
    json(route, {
      payment_completed: backend.paid,
      message: backend.paid ? "Payment received" : "Payment pending",
    }),

  // --- Chat ---------------------------------------------------------------
  [`POST ${API_PREFIX}/chat-stream`]: (route, backend) => {
    backend.chatRequest = postBody(route);
    backend.chatRequestCount += 1;
    return route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
      },
      body: sseBody(),
    });
  },
  [`GET ${API_PREFIX}/conversations`]: (route) =>
    json(route, {
      conversations: [],
      total: 0,
      page: 1,
      limit: 20,
      total_pages: 0,
    }),
  [`POST ${API_PREFIX}/conversations/batch-sync`]: (route) =>
    json(route, { conversations: [] }),

  // --- App-shell background reads ----------------------------------------
  [`GET ${API_PREFIX}/notifications`]: (route) =>
    json(route, { notifications: [], unread_count: 0, total: 0 }),
  [`GET ${API_PREFIX}/user/first-steps`]: (route) =>
    json(route, { steps: [], collapsed: false }),
  [`GET ${API_PREFIX}/integrations/me/snapshot`]: (route) =>
    json(route, { integrations: [] }),
  [`GET ${API_PREFIX}/integrations/status`]: (route) =>
    json(route, { statuses: {} }),
  [`GET ${API_PREFIX}/desktop/releases/latest`]: (route) =>
    json(route, {
      assets: [],
      html_url: "https://github.com/theexperiencecompany/gaia/releases",
      name: "E2E",
      published_at: null,
      tag: "desktop-v0.0.0-e2e",
    }),
};

/** Answer one `/api/v1/*` request from the in-memory backend. */
async function handleApi(route: Route, url: URL, backend: MockBackend) {
  const method = route.request().method();
  const key = `${method} ${url.pathname}`;

  if (method === "OPTIONS") {
    return route.fulfill({
      status: 204,
      headers: {
        ...corsHeaders(),
        "access-control-allow-headers":
          route.request().headers()["access-control-request-headers"] ?? "*",
        "access-control-allow-methods": "*",
        "access-control-max-age": "600",
      },
    });
  }

  const handler = API_ROUTES[key];
  if (handler) return handler(route, backend);

  // Everything else the shell background-loads is optional to this journey;
  // an empty success keeps those queries out of their error branches.
  return method === "GET"
    ? json(route, {})
    : json(route, { success: true, message: "ok" });
}

/**
 * The API base is normally same-origin, but mise's `apps/web/mise.toml`
 * exports `http://localhost:8000/api/v1/` into the dev server, so accept any
 * loopback host. Requests still never leave the machine: they are fulfilled
 * here with CORS headers.
 */
function isLoopbackApi(url: URL): boolean {
  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  return loopback && url.pathname.startsWith(`${API_PREFIX}/`);
}

/**
 * Install the hosted backend double. The first route is the only one that runs:
 * local app traffic continues, `/api/v1/*` is answered above, the Dodo overlay
 * is served locally, and every other origin is aborted.
 */
async function installHostedMocks(page: Page, backend: MockBackend) {
  const { baseURL } = test.info().project.use;
  if (!baseURL) {
    throw new Error("hosted e2e requires a baseURL");
  }
  const webOrigin = new URL(baseURL).origin;
  mockWebOrigin = webOrigin;

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());

    if (isLoopbackApi(url)) {
      return handleApi(route, url, backend);
    }

    if (url.origin === webOrigin) {
      return route.continue();
    }

    if (url.origin === DODO_ORIGIN) {
      // The embedded Dodo overlay. The SDK appends this as an iframe; the
      // button posts the same `checkout.redirect` event the real sheet sends.
      return route.fulfill({
        status: 200,
        contentType: "text/html",
        body: `<!doctype html><html><body style="font-family:sans-serif;padding:24px">
          <h1>Mock Dodo checkout</h1>
          <p>Test mode · ${DODO_CHECKOUT_URL}</p>
          <button id="pay" onclick="window.parent.postMessage({event_type:'checkout.redirect',data:{}}, '*')">Complete payment</button>
        </body></html>`,
      });
    }

    // No real network: PostHog, Sentry, Google, WorkOS CDN, Dodo SDK assets…
    return route.abort();
  });
}

/** Hosts the hosted app must never contact during this lane. */
const FORBIDDEN_HOST_PATTERNS = [
  /^api\.heygaia\.io$/,
  /(^|\.)workos\.com$/,
  /(^|\.)workoscdn\.com$/,
  /(^|\.)authkit\.com$/,
  /(^|\.)posthog\.com$/,
  /(^|\.)sentry\.io$/,
  /(^|\.)dodopayments\.com$/,
  /(^|\.)googleapis\.com$/,
  /(^|\.)gstatic\.com$/,
  /(^|\.)google-analytics\.com$/,
  /(^|\.)googletagmanager\.com$/,
];

function isForbiddenRequest(url: URL): boolean {
  if (url.origin === DODO_ORIGIN) return false; // served locally by the mock
  return FORBIDDEN_HOST_PATTERNS.some((pattern) => pattern.test(url.hostname));
}

/** Watch for uncaught page errors and requests to vendors this lane forbids. */
function watchPage(page: Page) {
  const pageErrors: string[] = [];
  const forbiddenRequests: string[] = [];

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (isForbiddenRequest(url)) forbiddenRequests.push(request.url());
  });

  return { pageErrors, forbiddenRequests };
}

/** Skip the cinematic intro and the session-resumed event on every document. */
async function seedBrowserState(page: Page) {
  await page.addInitScript((userId) => {
    try {
      localStorage.setItem(`gaia.onboarding.introSeen.${userId}`, "1");
      sessionStorage.setItem("gaia_session_resumed_tracked", "true");
    } catch {
      // about:blank and opaque origins have no storage; real pages do.
    }
  }, USER_ID);
}

const COMPOSER_PLACEHOLDER = /What can I do for you today/;

test.describe("hosted GAIA", () => {
  test("signs in, completes onboarding through a mocked checkout, and chats", async ({
    page,
  }) => {
    const backend = createBackend();
    const { pageErrors, forbiddenRequests } = watchPage(page);
    await seedBrowserState(page);
    await installHostedMocks(page, backend);

    // Landing → login. The marketing page is server-rendered; its only job in
    // this journey is to prove the hosted build serves it before auth starts.
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Get a workday back every week" }),
    ).toBeVisible();

    // /login → WorkOS start (mock AuthKit on the API origin) → callback with a
    // code → /redirect → the onboarding guard.
    await page.goto("/login");
    await page.waitForURL(/\/oauth\/login\/workos/, { timeout: 20_000 });
    await expect(
      page.getByRole("heading", { name: "Mock AuthKit" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Continue" }).click();
    await page.waitForURL(/\/onboarding$/, { timeout: 20_000 });

    // Q1: profession.
    await page.getByRole("button", { name: "Founder / CEO" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    // Q2: needs. The PATCH is the early persistence write, not completion.
    const preferencesSaved = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/onboarding/preferences") &&
        response.request().method() === "PATCH",
    );
    await page.getByRole("button", { name: "Inbox out of control" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await preferencesSaved;
    expect(backend.preferencesRequest).toMatchObject({
      profession: "founder",
      needs: ["inbox"],
    });

    // Payment: the monthly/yearly cards come from the mocked catalogue. The
    // sidebar promo sits behind the onboarding overlay and shares the label;
    // the card's CTA is the last visible "Subscribe".
    const subscribe = page
      .locator("button:visible")
      .filter({ hasText: /^Subscribe$/ })
      .last();
    await expect(subscribe).toBeVisible({ timeout: 15_000 });
    await subscribe.click();

    // The mocked Dodo sheet opens as the SDK's overlay iframe.
    const dodoFrame = page.locator("#dodo-checkout-iframe");
    await expect(dodoFrame).toBeVisible();
    await expect(
      page
        .frameLocator("#dodo-checkout-iframe")
        .getByRole("heading", { name: "Mock Dodo checkout" }),
    ).toBeVisible();
    expect(backend.checkoutRequest).toMatchObject({
      billing_cycle: "monthly",
      source: "onboarding",
    });

    // Paying flips the backend's subscription to Pro; the checkout store's
    // confirmation poll is what advances the wizard.
    backend.paid = true;
    await page
      .frameLocator("#dodo-checkout-iframe")
      .getByRole("button", { name: "Complete payment" })
      .click();

    await expect(page.getByRole("button", { name: "Let's go" })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "Let's go" }).click();

    // Platform pick (hosted always offers Telegram/WhatsApp/iMessage); skip
    // submits the completion request.
    await page.getByRole("button", { name: "Skip", exact: true }).click();
    await expect(page).toHaveURL(/\/c(\/|\?|$)/, { timeout: 20_000 });
    expect(backend.onboardingRequest).toMatchObject({
      profession: "founder",
      needs: ["inbox"],
    });

    // Open a conversation route so the stream's identity frame can bind its
    // ids synchronously (the body is fulfilled in one chunk; see sseBody).
    await page.goto(`/c/${CHAT_CONVERSATION_ID}`);
    const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER);
    await expect(composer).toBeVisible({ timeout: 15_000 });
    await composer.fill(CHAT_PROMPT);
    await composer.press("Enter");

    await expect(page.getByText(CHAT_PROMPT, { exact: true })).toBeVisible();
    await expect(page.getByText(CHAT_REPLY, { exact: true })).toBeVisible({
      timeout: 10_000,
    });
    expect(backend.chatRequest).toMatchObject({ message: CHAT_PROMPT });
    expect(backend.chatRequestCount).toBe(1);

    expect(pageErrors).toEqual([]);
    expect(forbiddenRequests).toEqual([]);
  });

  test("opens the upgrade sheet and mints a mocked Dodo session", async ({
    page,
  }) => {
    const backend = createBackend({ paid: false, onboardingCompleted: true });
    const { pageErrors, forbiddenRequests } = watchPage(page);
    await seedBrowserState(page);
    await installHostedMocks(page, backend);

    await page.goto("/c");
    await expect(page.getByPlaceholder(COMPOSER_PLACEHOLDER)).toBeVisible();

    // The sidebar promo is the voluntary upgrade entry point.
    await page
      .locator('[data-slot="sidebar"]')
      .getByRole("button", { name: "Subscribe", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Level Up")).toBeVisible();

    await dialog
      .getByRole("button", { name: "Subscribe", exact: true })
      .click();

    await expect(page.locator("#dodo-checkout-iframe")).toBeVisible();
    await expect(
      page
        .frameLocator("#dodo-checkout-iframe")
        .getByRole("heading", { name: "Mock Dodo checkout" }),
    ).toBeVisible();
    expect(backend.checkoutRequest).toMatchObject({
      billing_cycle: "monthly",
      source: "pricing_card",
    });

    expect(pageErrors).toEqual([]);
    expect(forbiddenRequests).toEqual([]);
  });
});
