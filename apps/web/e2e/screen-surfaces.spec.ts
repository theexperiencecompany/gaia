import { expect, type Page, type Request, test } from "@playwright/test";
import { API_BASE_URL, DEV_USER, SIM_ENABLED, sendMessage } from "./harness";
import {
  askBefore,
  conversationIdOf,
  seedInAppNotification,
} from "./screen-fixtures";
import {
  currentScreen,
  expectScreenOnlyGrew,
  recordScreen,
  type ScreenItem,
  settledScreen,
} from "./screen-timeline";

/**
 * Every surface that shows a conversation item outside the chat (pins, search,
 * the conversation list, notifications, a todo's workflow) shows the same
 * thing the chat does, and updates live from the server's push, not a poll.
 */

const TURN_MS = 90_000;
const CONVERSATION_URL = /\/c\/[0-9a-f-]{36}/;

/** A word no other conversation contains, so search and pins match exactly one item. */
const marker = (name: string) => `${name}${Date.now().toString(36)}`;

async function chatTurn(
  page: Page,
  text: string,
  lastLine: string,
): Promise<ScreenItem[]> {
  await recordScreen(page);
  await page.goto("/c");
  await sendMessage(page, text);
  await expect(page).toHaveURL(CONVERSATION_URL, { timeout: TURN_MS });
  const live = await settledScreen(page, lastLine, TURN_MS);
  await expectScreenOnlyGrew(page);
  return live;
}

const replyTo = (live: ScreenItem[], line: string): ScreenItem => {
  const reply = live.find(
    (i) => i.kind === "reply" && i.text.split("\n").includes(line),
  );
  if (!reply)
    throw new Error(`no reply reading "${line}" in ${JSON.stringify(live)}`);
  return reply;
};

/** The unread count the header's notification bell shows (0 when its badge is hidden). */
function unreadBadge(page: Page): Promise<number> {
  return page.evaluate(() => {
    const bell = document.querySelector('button[aria-label="Notifications"]');
    const badge = bell?.parentElement?.querySelector<HTMLElement>(
      '[data-slot="badge"]',
    );
    if (!badge || badge.dataset.invisible === "true") return 0;
    return Number(badge.innerText.trim()) || 0;
  });
}

test.describe.configure({ mode: "default" });

test.describe("screen surfaces", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(4 * TURN_MS);
  test.beforeEach(async () => askBefore([]));

  test("a pinned reply on the pins page reads exactly as the chat item", async ({
    page,
  }) => {
    const word = marker("pinme");
    const live = await chatTurn(
      page,
      `pin this [[say:${word} is pinned.]]`,
      `${word} is pinned.`,
    );
    const reply = replyTo(live, `${word} is pinned.`);
    const conversationId = conversationIdOf(page.url());
    const pinned = await fetch(
      `${API_BASE_URL}/conversations/${conversationId}/messages/${reply.id}/pin`,
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ pinned: true }),
      },
    );
    expect(pinned.ok, await pinned.text()).toBe(true);

    await page.goto("/pins");
    const card = page.getByRole("link").filter({ hasText: word });
    await expect(card).toHaveCount(1, { timeout: TURN_MS });
    await expect(card).toContainText(reply.text);
    await card.click();
    await expect(page).toHaveURL(new RegExp(`/c/${conversationId}`));
    await expect
      .poll(
        async () =>
          (await currentScreen(page)).find((i) => i.id === reply.id)?.text,
        {
          timeout: TURN_MS,
        },
      )
      .toBe(reply.text);
  });

  test("a search hit is the chat item it names", async ({ page }) => {
    const word = marker("findme");
    const live = await chatTurn(
      page,
      `remember ${word} [[say:Noted.]]`,
      "Noted.",
    );
    const asked = live.find((i) => i.kind === "user");
    if (!asked) throw new Error("no user item");
    const conversationId = conversationIdOf(page.url());

    const response = await fetch(`${API_BASE_URL}/search?query=${word}`);
    expect(response.ok).toBe(true);
    const { messages } = (await response.json()) as {
      messages: { conversation_id: string; item: { id: string } }[];
    };
    expect(messages.map((m) => [m.conversation_id, m.item.id])).toEqual([
      [conversationId, asked.id],
    ]);

    await page.goto("/c");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByPlaceholder("Search or run a command...").fill(word);
    const hit = page.getByRole("option").filter({ hasText: word });
    await expect(hit).toHaveCount(1, { timeout: TURN_MS });
    await hit.click();
    await expect(page).toHaveURL(new RegExp(`/c/${conversationId}`));
    await expect
      .poll(
        async () =>
          (await currentScreen(page)).find((i) => i.id === asked.id)?.text,
        {
          timeout: TURN_MS,
        },
      )
      .toBe(asked.text);
  });

  test("the conversation list shows a new message without polling", async ({
    page,
  }) => {
    const listReads: Request[] = [];
    page.on("request", (request) => {
      if (
        /\/api\/v1\/conversations(\?|$)/.test(request.url()) &&
        request.method() === "GET"
      ) {
        listReads.push(request);
      }
    });
    const word = marker("listed");
    await recordScreen(page);
    await page.goto("/c");
    await expect(
      page.getByRole("link", { name: "Create new chat" }),
    ).toBeVisible({
      timeout: TURN_MS,
    });
    await sendMessage(page, `${word} [[say:Listed.]]`);
    await expect(page).toHaveURL(CONVERSATION_URL, { timeout: TURN_MS });
    const conversationId = conversationIdOf(page.url());
    const row = page.locator(`a[href$="/c/${conversationId}"]`);
    await expect(
      row.first(),
      "the new conversation joins the list",
    ).toBeVisible({
      timeout: TURN_MS,
    });
    await settledScreen(page, "Listed.", TURN_MS);
    // An idle page that re-reads the list is polling; hold still long enough to see one.
    const readsWhenIdle = listReads.length;
    await page.waitForTimeout(20_000);
    expect(listReads.length - readsWhenIdle, "an idle list does not poll").toBe(
      0,
    );
  });

  test("reading a notification in one tab clears it in the other", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();
    seedInAppNotification(DEV_USER, marker("notify"));
    await first.goto("/c");
    await second.goto("/c");
    await expect
      .poll(() => unreadBadge(first), { timeout: TURN_MS })
      .toBeGreaterThan(0);
    await expect
      .poll(() => unreadBadge(second), { timeout: TURN_MS })
      .toBeGreaterThan(0);

    await first.getByRole("button", { name: "Notifications" }).click();
    await first.getByRole("button", { name: "Mark all as read" }).click();
    await expect.poll(() => unreadBadge(first), { timeout: TURN_MS }).toBe(0);
    await expect
      .poll(() => unreadBadge(second), {
        timeout: TURN_MS,
        message: "the other tab clears live",
      })
      .toBe(0);
  });

  test("a todo created in chat gets its workflow on the todo's page", async ({
    page,
  }) => {
    const title = marker("wf");
    await chatTurn(
      page,
      `[[tool:create_todo {"title":"${title}"}]] [[say:Todo made.]]`,
      "Todo made.",
    );
    await page.goto("/todos");
    await page.getByRole("button", { name: `Open todo ${title}` }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: title }),
    ).toBeVisible({
      timeout: TURN_MS,
    });
    await expect(page.getByText("Suggested Workflow")).toBeVisible({
      timeout: TURN_MS,
    });
    await expect(page.getByText("Generating...")).toHaveCount(0, {
      timeout: TURN_MS,
    });
    await expect(
      page.getByRole("button", { name: "Regenerate" }),
      "a workflow appeared for the todo",
    ).toBeVisible({ timeout: TURN_MS });
  });
});
