import { expect, type Page, test } from "@playwright/test";
import {
  type BubbleSnapshot,
  firstShownAt,
  listBubbles,
  loadingGaps,
  loadingRow,
  SIM_ENABLED,
  sendMessage,
  sendWhen,
  watchConversation,
} from "./harness";

/**
 * Messages sent while GAIA is still busy with the previous one, pinned as the
 * sim stack behaves today. The scripted model holds the executor between its
 * two todos ([[wait:...]]), which is the window the second message lands in.
 */

const WORK_HOLD_MS = 20_000;
/** A busy laptop stretches every model call; a turn's budget covers the cold case. */
const TURN_TIMEOUT_MS = 90_000;
const CONVERSATION_URL = /\/c\/[0-9a-f-]{36}/;

const workScript = (prefix: string, reply: string): string =>
  `stock up [[tool:create_todo {"title":"${prefix}-1"}]] [[wait:${WORK_HOLD_MS}]] ` +
  `[[tool:create_todo {"title":"${prefix}-2"}]] [[say:${reply}]]`;

const botBubbles = (bubbles: BubbleSnapshot[]) =>
  bubbles.filter((b) => b.role === "bot");

/** Lines of the bot bubbles that read exactly `text` (a tool card title or a reply). */
const linesReading = (bubbles: BubbleSnapshot[], text: string): number =>
  botBubbles(bubbles)
    .flatMap((b) => b.text.split("\n"))
    .filter((line) => line.trim() === text).length;

/** Send the work script from a fresh chat; resolves to a check for "the first todo's card is up". */
async function startWork(page: Page, script: string, firstCard: string) {
  await sendMessage(page, script);
  await expect(page).toHaveURL(CONVERSATION_URL, { timeout: TURN_TIMEOUT_MS });
  const workRunning = async () =>
    linesReading(await listBubbles(page), firstCard) === 1;
  return workRunning;
}

/**
 * Wait until the newest bubble reads exactly `lastReply` (a reply with no cards
 * above it), the loading row is gone, and the bubbles stop changing.
 */
async function settled(
  page: Page,
  lastReply: string,
): Promise<BubbleSnapshot[]> {
  await expect
    .poll(async () => (await listBubbles(page)).at(-1)?.text, {
      timeout: TURN_TIMEOUT_MS,
    })
    .toBe(lastReply);
  await expect(loadingRow(page)).toHaveCount(0, { timeout: TURN_TIMEOUT_MS });
  let previous = JSON.stringify(await listBubbles(page));
  await expect
    .poll(
      async () => {
        const now = JSON.stringify(await listBubbles(page));
        const same = now === previous;
        previous = now;
        return same;
      },
      { timeout: TURN_TIMEOUT_MS, intervals: [3_000] },
    )
    .toBe(true);
  return listBubbles(page);
}

test.describe("conversation runtime — messages during work", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
  );
  test.setTimeout(4 * TURN_TIMEOUT_MS);

  test("a side question during running work is answered while the work continues", async ({
    page,
  }) => {
    await page.goto("/c");
    const watch = watchConversation(page, ["sa-2"]);
    const workRunning = await startWork(
      page,
      workScript("sa", "Background work finished."),
      "sa-1",
    );
    await sendWhen(
      page,
      "what time is it? [[say:Side answer.]]",
      workRunning,
      TURN_TIMEOUT_MS,
    );
    const sideAsked = Date.now();

    await expect
      .poll(async () => linesReading(await listBubbles(page), "Side answer."), {
        timeout: TURN_TIMEOUT_MS,
      })
      .toBe(1);
    const answered = await listBubbles(page);
    expect(linesReading(answered, "sa-2"), "work still running").toBe(0);
    await expect(loadingRow(page)).toBeVisible();

    await expect
      .poll(async () => linesReading(await listBubbles(page), "sa-2"), {
        timeout: TURN_TIMEOUT_MS,
      })
      .toBe(1);
    const final = await settled(page, "Background work finished.");
    const samples = await watch.stop();

    expect(
      loadingGaps(
        samples,
        sideAsked - watch.startedAt,
        firstShownAt(samples, "sa-2") - 1,
      ),
      "the loading row stays up for the whole run",
    ).toEqual([]);
    expect(linesReading(final, "sa-1"), "the work ran once").toBe(1);
    expect(final.map((b) => b.role)).toEqual([
      "user",
      "bot",
      "user",
      "bot",
      "bot",
    ]);
    expect(final[3].text).toContain("Side answer.");
    expect(final[4].text).toBe("Background work finished.");
  });

  test("an addition during running work reaches that work, and one result comes back", async ({
    page,
  }) => {
    await page.goto("/c");
    const workRunning = await startWork(
      page,
      workScript("sb", "Pantry stocked."),
      "sb-1",
    );
    await sendWhen(
      page,
      'also add oat milk [[tool:create_todo {"title":"sb-oat"}]] [[say:Oat milk too.]]',
      workRunning,
      TURN_TIMEOUT_MS,
    );

    const final = await settled(page, "Oat milk too.");
    expect(linesReading(final, "sb-oat"), "the addition ran once").toBe(1);
    expect(final.map((b) => b.role)).toEqual([
      "user",
      "bot",
      "user",
      "bot",
      "bot",
    ]);
    const workBubble = final[1].text.split("\n");
    expect(workBubble, "the addition ran inside the running work").toEqual(
      expect.arrayContaining(["sb-1", "sb-2", "sb-oat"]),
    );
    expect(final[4].text, "one result, covering the addition").toBe(
      "Oat milk too.",
    );
  });
});

test.describe("conversation runtime — two devices", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
  );
  test.setTimeout(3 * TURN_TIMEOUT_MS);

  // Without the reload the second browser misses the first one's message and
  // streamed reply and shows only the result pushed afterwards: plan PR 6's
  // one stream per conversation is what makes it live.
  test("a second browser open on the conversation shows the same bubbles in the same order once it reloads after a turn", async ({
    browser,
  }) => {
    const first = await (await browser.newContext()).newPage();
    const second = await (await browser.newContext()).newPage();

    await first.goto("/c");
    await sendMessage(first, "hello [[say:First turn.]]");
    await expect(first).toHaveURL(CONVERSATION_URL, {
      timeout: TURN_TIMEOUT_MS,
    });
    await settled(first, "First turn.");

    await second.goto(first.url());
    await expect
      .poll(async () => (await listBubbles(second)).length, {
        timeout: TURN_TIMEOUT_MS,
      })
      .toBe(2);

    await sendMessage(
      first,
      '[[tool:create_todo {"title":"sd-1"}]] [[say:Second turn.]]',
    );
    const onFirst = await settled(first, "Second turn.");

    await second.reload();
    await expect
      .poll(async () => listBubbles(second), { timeout: TURN_TIMEOUT_MS })
      .toEqual(onFirst);
  });
});
