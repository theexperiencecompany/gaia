import { expect, type Page, test } from "@playwright/test";
import {
  loadingGaps,
  loadingRow,
  longestBlindWorkMs,
  SIM_ENABLED,
  sendMessage,
  watchConversation,
} from "./harness";
import {
  askBefore,
  backdateApproval,
  conversationIdOf,
  serverScreen,
} from "./screen-fixtures";
import {
  botLinesReading,
  currentScreen,
  expectReloadMatches,
  expectScreenOnlyGrew,
  recordScreen,
  type ScreenItem,
  settledScreen,
  timeline,
  toolSections,
} from "./screen-timeline";

/**
 * The server owns the conversation screen and pushes patches; the web renders
 * them. Each flow scripts the model (sim stub), records the rendered items at
 * every DOM change, and asserts the screen only grew — nothing reordered,
 * vanished or doubled — and that a reload shows exactly what was live.
 */

const TURN_MS = 90_000;
/** The worker's conversation sweep runs every minute; an expiry lands within two. */
const SWEEP_MS = 150_000;
const CONVERSATION_URL = /\/c\/[0-9a-f-]{36}/;
const BREAK = "<NEW_MESSAGE_BREAK>";
const HOLD_MS = 15_000;

const roles = (items: ScreenItem[]) => items.map((i) => i.role);
const todo = (title: string) => `[[tool:create_todo {"title":"${title}"}]]`;
/** Work that holds the executor between its two todos: the window a mid-work action lands in. */
const heldWork = (prefix: string, reply: string) =>
  `work ${todo(`${prefix}-1`)} [[wait:${HOLD_MS}]] ${todo(`${prefix}-2`)} [[say:${reply}]]`;

async function openNewChat(page: Page): Promise<void> {
  await recordScreen(page);
  await page.goto("/c");
}

async function sendAndOpen(page: Page, text: string): Promise<void> {
  await sendMessage(page, text);
  await expect(page).toHaveURL(CONVERSATION_URL, { timeout: TURN_MS });
}

async function untilBotLine(
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
async function finish(page: Page, lastLine: string): Promise<ScreenItem[]> {
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
function expectUserOrder(items: ScreenItem[], sent: string[]): void {
  expect(items[0].role).toBe("user");
  const users = items.filter((i) => i.role === "user").map((i) => i.text);
  expect(users).toEqual(sent.map((text) => expect.stringContaining(text)));
}

// The flows share one dev user and flip its approval preferences: one at a time, in order.
test.describe.configure({ mode: "default" });

test.describe("screen over time — chat", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore([]));

  test("a single reply lands under its question", async ({ page }) => {
    await openNewChat(page);
    await sendAndOpen(page, "hi [[say:Hello there.]]");
    const live = await finish(page, "Hello there.");
    expect(roles(live)).toEqual(["user", "bot"]);
    expect(live[1].text).toBe("Hello there.");
  });

  test("a second turn's reply lands under the second question, not above it", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "one [[say:Answer one.]]");
    await settledScreen(page, "Answer one.", TURN_MS);
    await sendMessage(page, "two [[say:Answer two.]]");
    const live = await finish(page, "Answer two.");
    expectUserOrder(live, ["one", "two"]);
    const second = live.findIndex(
      (i) => i.role === "user" && i.text.startsWith("two"),
    );
    const answer = live.findIndex(
      (i) => i.role === "bot" && i.text.includes("Answer two."),
    );
    expect(answer).toBeGreaterThan(second);
  });

  test("a retracted preamble is replaced in place by the reply", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `[[pace:40]] [[narrate:Let me check that.]] ${todo("pa-1")} [[say:Checked it.]]`,
    );
    const live = await finish(page, "Checked it.");
    expect(
      botLinesReading(live, "Let me check that."),
      "the preamble is gone",
    ).toBe(0);
    expect(toolSections(live)).toBe(1);
  });

  test("a multi-bubble reply streams its parts in order under its question", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `three parts [[pace:40]] [[say:Part one.${BREAK}Part two.${BREAK}Part three.]]`,
    );
    const live = await finish(page, "Part three.");
    expect(live[0].role).toBe("user");
    const lines = live.slice(1).flatMap((i) => i.text.split("\n"));
    expect(lines.filter((l) => l.startsWith("Part "))).toEqual([
      "Part one.",
      "Part two.",
      "Part three.",
    ]);
  });

  test("a reply with tools shows one section with one card per call, each with its output", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `two todos ${todo("rt-1")} ${todo("rt-2")} [[say:Both added.]]`,
    );
    const live = await finish(page, "Both added.");
    expect(toolSections(live), "one tool section for one piece of work").toBe(
      1,
    );
    // A todo card renders the todo the call returned: it opens that todo.
    for (const title of ["rt-1", "rt-2"]) {
      expect(botLinesReading(live, title)).toBe(1);
      await expect(page.getByRole("button", { name: title })).toHaveCount(1);
    }
    await page.getByRole("button", { name: "rt-2" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "rt-2" }),
      "the card carries the created todo",
    ).toBeVisible();
  });

  // A burst may be answered once or per message; either way every reply sits under the message it answers.
  test("three messages sent in a burst keep their order, each above its reply", async ({
    page,
  }) => {
    await openNewChat(page);
    const words = ["first", "second", "third"];
    const replies = ["Reply one.", "Reply two.", "Reply three."];
    await sendAndOpen(page, `${words[0]} [[say:${replies[0]}]]`);
    await sendMessage(page, `${words[1]} [[say:${replies[1]}]]`);
    await sendMessage(page, `${words[2]} [[say:${replies[2]}]]`);
    const live = await finish(page, replies[2]);
    expectUserOrder(live, words);
    words.forEach((word, n) => {
      const asked = live.findIndex(
        (i) => i.role === "user" && i.text.startsWith(word),
      );
      const answered = live.findIndex(
        (i) => i.role === "bot" && i.text.split("\n").includes(replies[n]),
      );
      if (answered >= 0) {
        expect(
          answered,
          `"${replies[n]}" sits under "${word}"`,
        ).toBeGreaterThan(asked);
      }
    });
  });

  test("a side question during running work is answered while the work keeps its one section", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, heldWork("sq", "Work done."));
    await untilBotLine(page, "sq-1");
    await sendMessage(page, "quick question [[say:Side answer.]]");
    await untilBotLine(page, "Side answer.");
    const live = await finish(page, "Work done.");
    expectUserOrder(live, ["work", "quick question"]);
    expect(toolSections(live), "the work is one section").toBe(1);
    expect(botLinesReading(live, "sq-1")).toBe(1);
    expect(botLinesReading(live, "sq-2")).toBe(1);
  });

  test("stopping mid-work shows Stopped and nothing on screen vanishes", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, heldWork("st", "Never said."));
    await untilBotLine(page, "st-1");
    // The front door acknowledges with the scripted text at hand-off; nothing may follow the stop.
    const acknowledged = botLinesReading(
      await currentScreen(page),
      "Never said.",
    );
    await page.getByRole("button", { name: "Stop generation" }).click();
    await expect(page.getByText("Stopped").first()).toBeVisible({
      timeout: TURN_MS,
    });
    await expect(loadingRow(page)).toHaveCount(0, { timeout: TURN_MS });
    const live = await settledScreen(page, "st-1", TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(
      botLinesReading(live, "st-2"),
      "the stopped work did not continue",
    ).toBe(0);
    expect(
      botLinesReading(live, "Never said."),
      "no reply after the stop",
    ).toBe(acknowledged);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("a reload mid-reply resumes the same items in the same order", async ({
    page,
  }) => {
    await openNewChat(page);
    const words = Array.from({ length: 40 }, (_, i) => `w${i}`).join(" ");
    await sendAndOpen(page, `stream it [[pace:150]] [[say:${words} end.]]`);
    await expect
      .poll(async () => (await currentScreen(page)).length, {
        timeout: TURN_MS,
      })
      .toBeGreaterThan(1);
    const before = await currentScreen(page);
    await expectScreenOnlyGrew(page);
    await page.reload();
    const live = await settledScreen(page, `${words} end.`, TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(live.map((i) => i.id).slice(0, before.length)).toEqual(
      before.map((i) => i.id),
    );
    expect(roles(live)).toEqual(["user", "bot"]);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("two tabs on one chat show the same items in the same order, live", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();
    await openNewChat(first);
    await sendAndOpen(first, "hello [[say:First turn.]]");
    await settledScreen(first, "First turn.", TURN_MS);
    await recordScreen(second);
    await second.goto(first.url());
    await settledScreen(second, "First turn.", TURN_MS);

    await sendMessage(first, `more ${todo("tt-1")} [[say:Second turn.]]`);
    const onFirst = await settledScreen(first, "Second turn.", TURN_MS);
    await expect
      .poll(async () => currentScreen(second), { timeout: TURN_MS })
      .toEqual(onFirst);
    await expectScreenOnlyGrew(first);
    await expectScreenOnlyGrew(second);
  });

  test("a failed reply keeps its streamed text and cards in place", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(
      page,
      `${todo("ff-1")} [[say:Partial progress.]] [[fail:provider dropped the stream]]`,
    );
    await expect(page.getByText("Response was cut short")).toBeVisible({
      timeout: TURN_MS,
    });
    const live = await finish(page, "Partial progress.");
    expect(botLinesReading(live, "ff-1")).toBe(1);
  });

  test("Retry on a failed reply resends that reply's message, not an earlier one", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "one [[say:First fine.]]");
    await settledScreen(page, "First fine.", TURN_MS);
    await sendMessage(
      page,
      "two [[say:Second partial.]] [[fail:provider dropped the stream]]",
    );
    const failed = page.getByRole("button", { name: "Retry" });
    await expect(failed).toBeVisible({ timeout: TURN_MS });
    const before = await currentScreen(page);
    const attemptsBefore = botLinesReading(before, "Second partial.");
    await failed.click();
    await expect
      .poll(
        async () =>
          botLinesReading(await currentScreen(page), "Second partial."),
        {
          timeout: TURN_MS,
          message: "the retry re-ran the failed message",
        },
      )
      .toBeGreaterThan(attemptsBefore);
    const live = await settledScreen(page, "Second partial.", TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(
      botLinesReading(live, "First fine."),
      "the earlier message was not resent",
    ).toBe(1);
    expect(live.filter((i) => i.role === "user").map((i) => i.text)).toEqual(
      before.filter((i) => i.role === "user").map((i) => i.text),
    );
  });

  test("the loading line stays up for the whole time work streams", async ({
    page,
  }) => {
    await openNewChat(page);
    const watch = watchConversation(page);
    await sendAndOpen(page, heldWork("ld", "Loaded."));
    await untilBotLine(page, "ld-1");
    const firstCard = Date.now();
    await untilBotLine(page, "ld-2");
    const lastCard = Date.now();
    await settledScreen(page, "Loaded.", TURN_MS);
    const samples = await watch.stop();
    expect(
      loadingGaps(
        samples,
        firstCard - watch.startedAt,
        lastCard - watch.startedAt,
      ),
      "no moment of running work without the loading line",
    ).toEqual([]);
    expect(
      longestBlindWorkMs(samples),
      "nothing grows while the line is hidden",
    ).toBeLessThan(1_000);
  });

  test("a pending send becomes the server's user item in place, without moving", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "first [[say:Got the first.]]");
    await settledScreen(page, "Got the first.", TURN_MS);
    await sendMessage(page, "second [[say:Got the second.]]");
    await settledScreen(page, "Got the second.", TURN_MS);
    const frames = await timeline(page);
    const positions = frames.flatMap((frame) => {
      const at = frame.items.findIndex(
        (i) => i.role === "user" && i.text.startsWith("second"),
      );
      return at < 0 ? [] : [`${at}:${frame.items[at].id}`];
    });
    expect(positions.length, "the send showed at once").toBeGreaterThan(0);
    expect(
      new Set(positions),
      "one id at one position, pending to delivered",
    ).toEqual(new Set([positions[0]]));
    const live = await finish(page, "Got the second.");
    expect(
      positions[0].split(":")[1],
      "the server item kept the pending send's id",
    ).toBe(
      live.find((i) => i.role === "user" && i.text.startsWith("second"))?.id,
    );
  });

  test("a reply, then work, then a reply render in the server's order", async ({
    page,
  }) => {
    await openNewChat(page);
    await sendAndOpen(page, "say hi [[say:Hi first.]]");
    await settledScreen(page, "Hi first.", TURN_MS);
    await sendMessage(page, `now work ${todo("ord-1")} [[say:Work reply.]]`);
    await settledScreen(page, "ord-1", TURN_MS);
    await sendMessage(page, "and again [[say:Last reply.]]");
    const live = await finish(page, "Last reply.");
    const kinds = live.map((i) => i.kind);
    const work = kinds.indexOf("work");
    expect(work, "the work is on screen").toBeGreaterThan(0);
    expect(kinds.slice(0, work)).toContain("reply");
    expect(kinds.slice(work + 1)).toContain("reply");
  });
});

test.describe("screen over time — approvals", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the sim stack (`mise dev --sim`, E2E_SIM=1).",
  );
  test.setTimeout(5 * TURN_MS);
  test.beforeEach(async () => askBefore(["create_todo"]));
  test.afterEach(async () => askBefore([]));

  async function askForApproval(page: Page, title: string, reply: string) {
    await openNewChat(page);
    await sendAndOpen(page, `${todo(title)} [[say:${reply}]]`);
    const card = page.getByText("Needs approval").first();
    await expect(card).toBeVisible({ timeout: TURN_MS });
    await expectScreenOnlyGrew(page);
  }

  test("approving runs the call in the same work section", async ({ page }) => {
    await askForApproval(page, "ap-1", "Approved and added.");
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const live = await finish(page, "Approved and added.");
    expect(
      toolSections(live),
      "the approved call joins its work, not a new section",
    ).toBe(1);
    expect(botLinesReading(live, "Needs approval"), "the card resolved").toBe(
      0,
    );
  });

  test("denying leaves the call unrun and the card resolved", async ({
    page,
  }) => {
    await askForApproval(page, "dn-1", "Not added.");
    await page.getByRole("button", { name: "Deny", exact: true }).click();
    await expect(page.getByText("Needs approval")).toHaveCount(0, {
      timeout: TURN_MS,
    });
    const live = await settledScreen(page, "Not added.", TURN_MS);
    await expectScreenOnlyGrew(page);
    expect(toolSections(live)).toBeLessThanOrEqual(1);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("an approval nobody answers expires on screen without a reload", async ({
    page,
  }) => {
    test.setTimeout(SWEEP_MS + 3 * TURN_MS);
    await askForApproval(page, "ex-1", "Expired.");
    backdateApproval(conversationIdOf(page.url()));
    await expect(page.getByText("Needs approval")).toHaveCount(0, {
      timeout: SWEEP_MS,
    });
    await expect(page.getByText("Expired").first()).toBeVisible();
    const live = await settledScreen(page, "Expired.", TURN_MS);
    await expectScreenOnlyGrew(page);
    await expectReloadMatches(page, live, TURN_MS);
  });

  test("a decision in one tab resolves the card in the other", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();
    await askForApproval(first, "tw-1", "Decided elsewhere.");
    await recordScreen(second);
    await second.goto(first.url());
    await expect(second.getByText("Needs approval").first()).toBeVisible({
      timeout: TURN_MS,
    });
    await first.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(second.getByText("Needs approval")).toHaveCount(0, {
      timeout: TURN_MS,
    });
    const onFirst = await settledScreen(first, "Decided elsewhere.", TURN_MS);
    await expect
      .poll(async () => currentScreen(second), { timeout: TURN_MS })
      .toEqual(onFirst);
    await expectScreenOnlyGrew(first);
    await expectScreenOnlyGrew(second);
  });
});
