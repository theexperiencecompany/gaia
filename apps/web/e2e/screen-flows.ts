/**
 * The steps every screen flow is built from: open a recorded chat, send a
 * scripted message, wait for a line, and finish by asserting the timeline only
 * grew, the server's order, and that a reload shows the same screen.
 */

import { expect, type Page } from "@playwright/test";
import { sendMessage } from "./harness";
import { conversationIdOf, serverScreen } from "./screen-fixtures";
import {
  botLinesReading,
  currentScreen,
  expectReloadMatches,
  expectScreenOnlyGrew,
  recordScreen,
  type ScreenItem,
  settledScreen,
} from "./screen-timeline";

export const TURN_MS = 90_000;
/** The worker's conversation sweep runs every minute; an expiry lands within two. */
export const SWEEP_MS = 150_000;
const CONVERSATION_URL = /\/c\/[0-9a-f-]{36}/;
export const BREAK = "<NEW_MESSAGE_BREAK>";
export const HOLD_MS = 15_000;

export const roles = (items: ScreenItem[]) => items.map((i) => i.role);
export const todo = (title: string) =>
  `[[tool:create_todo {"title":"${title}"}]]`;
/** Work that holds the executor between its two todos: the window a mid-work action lands in. */
export const heldWork = (prefix: string, reply: string) =>
  `work ${todo(`${prefix}-1`)} [[wait:${HOLD_MS}]] ${todo(`${prefix}-2`)} [[say:${reply}]]`;

export async function openNewChat(page: Page): Promise<void> {
  await recordScreen(page);
  await page.goto("/c");
}

export async function sendAndOpen(page: Page, text: string): Promise<void> {
  await sendMessage(page, text);
  await expect(page).toHaveURL(CONVERSATION_URL, { timeout: TURN_MS });
}

export async function untilBotLine(
  page: Page,
  line: string,
  count = 1,
): Promise<void> {
  await expect
    .poll(async () => botLinesReading(await currentScreen(page), line), {
      timeout: TURN_MS,
    })
    .toBeGreaterThanOrEqual(count);
}

/** Settle on `lastLine`, assert the live timeline only grew, reload, and assert the same screen comes back. */
export async function finish(
  page: Page,
  lastLine: string,
): Promise<ScreenItem[]> {
  const live = await settledScreen(page, lastLine, TURN_MS);
  await expectScreenOnlyGrew(page);
  await expectServerOrder(page, live);
  await expectReloadMatches(page, live, TURN_MS);
  return live;
}

/** The rendered items are the server's screen items, in the server's seq order. */
async function expectServerOrder(
  page: Page,
  live: ScreenItem[],
): Promise<void> {
  const server = await serverScreen(conversationIdOf(page.url()));
  const shown = new Set(live.map((i) => i.id));
  expect(
    live.map((i) => `${i.kind}:${i.id}`),
    "the web renders the server's items in the server's order",
  ).toEqual(
    server.filter((i) => shown.has(i.id)).map((i) => `${i.kind}:${i.id}`),
  );
}

/** Every user item sits above the replies to it: the first item is the user's, and user items keep send order. */
export function expectUserOrder(items: ScreenItem[], sent: string[]): void {
  expect(items[0].role).toBe("user");
  const users = items.filter((i) => i.role === "user").map((i) => i.text);
  expect(users).toEqual(sent.map((text) => expect.stringContaining(text)));
}

/** Open the todo list, where the user sees which calls ran, and assert each title is listed or not. */
export async function expectTodos(
  page: Page,
  listed: string[],
  absent: string[] = [],
): Promise<void> {
  await page.goto("/todos");
  for (const title of listed) {
    await expect(
      page.getByText(title, { exact: true }),
      `"${title}" was created`,
    ).toBeVisible({ timeout: TURN_MS });
  }
  for (const title of absent) {
    await expect(
      page.getByText(title, { exact: true }),
      `"${title}" was never created`,
    ).toHaveCount(0);
  }
}
