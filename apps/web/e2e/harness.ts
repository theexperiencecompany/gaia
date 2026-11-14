/**
 * Shared plumbing for the Playwright e2e suite.
 *
 * Everything here rides the dev harness: the API's dev auth bypass means every
 * page load is already authenticated, and the dev router
 * (`/api/v1/dev/*`, only mounted when `ENV=development` + `DEV_AUTH_BYPASS_EMAIL`
 * is set) lets us mint + seed a deterministic user with no WorkOS login.
 *
 * Ports honor `WEB_PORT` / `API_PORT` so per-worktree ports from `.env.worktree`
 * (see `mise run wt:env`) work without edits.
 */

import { expect, type Locator, type Page } from "@playwright/test";

const WEB_PORT = process.env.WEB_PORT ?? "3000";
const API_PORT = process.env.API_PORT ?? "8000";

/**
 * The seeded dev user, matching `mise seed` / `mise dev --sim` defaults. Ports
 * are per-worktree but Mongo is shared, so two worktrees running e2e against the
 * same `DEV_USER` clobber each other's data — run one worktree at a time, or set
 * a distinct `DEV_USER` here AND matching `DEV_AUTH_BYPASS_EMAIL` on its API.
 */
export const DEV_USER = process.env.DEV_USER ?? "dev@gaia.local";

/** Fail loud on malformed seed counts instead of sending NaN/negatives to the API. */
function seedCount(name: string, fallback: number, min: number): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min) {
    throw new Error(`${name} must be an integer >= ${min}, got "${raw}"`);
  }
  return value;
}

// SEED_TODOS >= 1: the smoke spec asserts on the first seeded todo.
export const SEED_TODOS = seedCount("SEED_TODOS", 5, 1);
export const SEED_CONVERSATIONS = seedCount("SEED_CONVERSATIONS", 2, 0);

export const WEB_BASE_URL = `http://localhost:${WEB_PORT}`;
export const API_BASE_URL = `http://localhost:${API_PORT}/api/v1`;

/**
 * Title of the first seeded todo. The dev seeder creates "Sample todo 1..N"
 * (see `apps/api/app/services/dev_service.py`) — this is the assertion anchor.
 */
export const FIRST_SEEDED_TODO = "Sample todo 1";

/**
 * The scripted chat test only runs against the deterministic sim stack
 * (`mise dev --sim`), where the LLM is replaced by a directive-parsing stub.
 * Set `E2E_SIM=1` to enable it; otherwise it is skipped with a clear reason.
 */
export const SIM_ENABLED = ["1", "true", "yes"].includes(
  (process.env.E2E_SIM ?? "").toLowerCase(),
);

/** Reply text the stub emits for a `[[say:Done!]]` directive. */
export const SCRIPTED_REPLY = "Done!";
/** Chat message whose directives the LLM stub executes verbatim. */
export const SCRIPTED_CHAT_MESSAGE = `[[say:${SCRIPTED_REPLY}]]`;

const NOT_CONFIGURED_HINT =
  "Start the dev stack (`mise dev --sim` or `mise dev`) with " +
  "DEV_AUTH_BYPASS_EMAIL set in apps/api/.env — the dev router only mounts " +
  "when ENV=development and the bypass is configured.";

async function devRequest(
  path: string,
  init: RequestInit & { tolerate404?: boolean } = {},
): Promise<unknown> {
  const { tolerate404, ...requestInit } = init;
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      ...requestInit,
      headers: { "content-type": "application/json", ...requestInit.headers },
    });
  } catch (cause) {
    throw new Error(
      `Cannot reach the dev API at ${url}. Is it running on port ${API_PORT}? ` +
        `${NOT_CONFIGURED_HINT}\nUnderlying error: ${String(cause)}`,
    );
  }

  if (response.status === 404 && !tolerate404) {
    throw new Error(
      `The dev API returned 404 for ${path}. The dev router is not mounted. ` +
        NOT_CONFIGURED_HINT,
    );
  }

  if (response.status === 404 && tolerate404) {
    return null;
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `Dev API ${path} failed (${response.status} ${response.statusText}): ${body}`,
    );
  }

  return response.json();
}

/** Remove the dev user + owned data so each run starts from a clean slate. */
export async function resetDevUser(): Promise<void> {
  await devRequest(`/dev/users/${encodeURIComponent(DEV_USER)}`, {
    method: "DELETE",
    tolerate404: true,
  });
}

/** Idempotently mint the dev user via the real signup path. */
export async function mintDevUser(): Promise<void> {
  await devRequest("/dev/users", {
    method: "POST",
    body: JSON.stringify({ email: DEV_USER }),
  });
}

/**
 * Seed deterministic todos + conversations for the dev user. The dev seeder
 * also marks onboarding complete, so specs land on the app shell rather than
 * being bounced to `/onboarding` by the onboarding guard, and grants Pro, so
 * the paywall does not cover the app.
 */
export async function seedDevData(): Promise<void> {
  await devRequest("/dev/seed", {
    method: "POST",
    body: JSON.stringify({
      email: DEV_USER,
      todos: SEED_TODOS,
      conversations: SEED_CONVERSATIONS,
      pro: true,
    }),
  });
}

// ---------------------------------------------------------------------------
// Driving and observing a conversation the way a user sees it
// ---------------------------------------------------------------------------

export const COMPOSER_PLACEHOLDER = "What can I do for you today?";

/** How often {@link watchConversation} and {@link sendWhen} read the page. */
const SAMPLE_INTERVAL_MS = 100;

export function composer(page: Page): Locator {
  return page.getByPlaceholder(COMPOSER_PLACEHOLDER, { exact: false });
}

/** Type a message into the composer and send it. */
export async function sendMessage(page: Page, text: string): Promise<void> {
  const box = composer(page);
  await box.fill(text);
  await box.press("Enter");
}

/** Send `text` the moment `condition` holds, failing if it never does within `timeoutMs`. */
export async function sendWhen(
  page: Page,
  text: string,
  condition: () => Promise<boolean>,
  timeoutMs = 60_000,
): Promise<void> {
  await expect
    .poll(condition, { timeout: timeoutMs, intervals: [SAMPLE_INTERVAL_MS] })
    .toBe(true);
  await sendMessage(page, text);
}

/** The "GAIA is thinking..." row under the conversation, with its tool prefix. */
export function loadingRow(page: Page): Locator {
  return page.getByTestId("chat-loading-row");
}

export interface BubbleSnapshot {
  messageId: string;
  role: "user" | "bot";
  text: string;
}

/** Every rendered bubble, in DOM order; empty bot messages render nothing and are skipped. */
export function listBubbles(page: Page): Promise<BubbleSnapshot[]> {
  return page.evaluate(() =>
    [
      ...document.querySelectorAll<HTMLElement>(
        '[data-slot="message-scroller-item"]',
      ),
    ].flatMap((item): BubbleSnapshot[] => {
      const user = item.querySelector<HTMLElement>(
        ".chat_bubble_container.user",
      );
      const bubble =
        user ?? item.querySelector<HTMLElement>(".chatbubblebot_parent");
      if (!bubble) return [];
      return [
        {
          messageId: item.dataset.messageId ?? "",
          role: user ? "user" : "bot",
          text: bubble.innerText.trim(),
        },
      ];
    }),
  );
}

/** The text bubbles of each bot message, in DOM order: what one reply split into. */
export function botBubbleParts(page: Page): Promise<string[][]> {
  return page.evaluate(() =>
    [
      ...document.querySelectorAll<HTMLElement>(
        '[data-slot="message-scroller-item"] .chatbubblebot_parent',
      ),
    ].map((message) =>
      [...message.querySelectorAll<HTMLElement>(".imessage-bubble")].map(
        (bubble) => bubble.innerText.trim(),
      ),
    ),
  );
}

/** The reaction badge GAIA left on a user bubble ("" when it has none). */
export async function bubbleReactions(
  page: Page,
  messageId: string,
): Promise<string> {
  const badge = page
    .locator(`[id="${messageId}"]`)
    .getByRole("group", { name: "Reactions" });
  return (await badge.count()) === 0
    ? ""
    : ((await badge.textContent()) ?? "").trim();
}

/** One reading of the page: the loading row's text (null when hidden) and how much conversation is on screen. */
export interface ConversationSample {
  /** Milliseconds since the watch started. */
  t: number;
  loading: string | null;
  contentLength: number;
}

export interface ConversationWatch {
  /** Epoch ms the samples' `t` counts from. */
  startedAt: number;
  /** Stop sampling and return every sample; rethrows if a reading failed. */
  stop: () => Promise<ConversationSample[]>;
}

/** Sample the loading row and the conversation's size every {@link SAMPLE_INTERVAL_MS} until stopped. */
export function watchConversation(page: Page): ConversationWatch {
  const samples: ConversationSample[] = [];
  const started = Date.now();
  let running = true;
  const loop = (async () => {
    while (running) {
      const reading = await page.evaluate(() => {
        const row = document.querySelector('[data-testid="chat-loading-row"]');
        const content = document.querySelector(
          '[data-slot="message-scroller-content"]',
        );
        return {
          loading: row ? (row.textContent ?? "").trim() : null,
          contentLength: content?.textContent?.length ?? 0,
        };
      });
      samples.push({ t: Date.now() - started, ...reading });
      await page.waitForTimeout(SAMPLE_INTERVAL_MS);
    }
  })();
  return {
    startedAt: started,
    stop: async () => {
      running = false;
      await loop;
      return samples;
    },
  };
}

/**
 * The longest time the conversation kept changing while no loading row was
 * shown: within each stretch of hidden-row samples, the time from its first
 * change to its last. A reply landing once is one interval; text or cards
 * still growing with nothing telling the user GAIA is busy is blind work.
 */
export function longestBlindWorkMs(samples: ConversationSample[]): number {
  let longest = 0;
  let firstChange: number | null = null;
  for (let i = 1; i < samples.length; i += 1) {
    const [before, now] = [samples[i - 1], samples[i]];
    if (now.loading !== null || before.loading !== null) {
      firstChange = null;
      continue;
    }
    if (now.contentLength === before.contentLength) continue;
    firstChange ??= before.t;
    longest = Math.max(longest, now.t - firstChange);
  }
  return longest;
}

/** Samples inside [fromMs, toMs] that showed no loading row. */
export function loadingGaps(
  samples: ConversationSample[],
  fromMs: number,
  toMs: number,
): ConversationSample[] {
  return samples.filter(
    (s) => s.t >= fromMs && s.t <= toMs && s.loading === null,
  );
}
