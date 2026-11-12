import { expect, type Page, test } from "@playwright/test";
import { botBubbleParts, SIM_ENABLED, sendMessage } from "./harness";

/**
 * One reply split into bubbles, watched while it streams word by word and read
 * again after a reload: the bubbles appear in order, a bubble never changes once
 * the next has started, a retraction is replaced in place, and the saved message
 * renders as the same bubbles the stream showed.
 */

const BREAK = "<NEW_MESSAGE_BREAK>";
const TURN_TIMEOUT_MS = 90_000;
const CONVERSATION_URL = /\/c\/[0-9a-f-]{36}/;
const SAMPLE_INTERVAL_MS = 100;

const R2 = [
  "Morning! Here is a quick rundown of what your day looks like.",
  "You have three meetings today, and the first one starts at ten sharp.",
  "Do you want me to push the standup to the afternoon so you get a break?",
];
const PREAMBLE = [
  "Sure thing, give me a moment.",
  "Let me look into your calendar for that one.",
];
const R5_REPLY = "All set, I added it to your todo list for today.";

/** Samples the first bot message's bubbles until it reads `last` and holds still. */
async function watchFirstReply(page: Page, last: string): Promise<string[][]> {
  const frames: string[][] = [];
  await expect
    .poll(
      async () => {
        const reply = (await botBubbleParts(page))[0] ?? [];
        if (JSON.stringify(reply) !== JSON.stringify(frames.at(-1))) {
          frames.push(reply);
        }
        return reply.at(-1);
      },
      { timeout: TURN_TIMEOUT_MS, intervals: [SAMPLE_INTERVAL_MS] },
    )
    .toBe(last);
  return frames;
}

/** Fails if a bubble the user saw changed after a later one appeared, or vanished. */
function expectBubblesOnlyGrow(frames: string[][]): void {
  for (const [i, frame] of frames.entries()) {
    const next = frames[i + 1];
    if (!next) continue;
    for (const [j, bubble] of frame.entries()) {
      const later = next[j];
      expect(later, `bubble ${j} vanished after frame ${i}`).toBeDefined();
      if (j < frame.length - 1) {
        expect(later, `sealed bubble ${j} changed`).toBe(bubble);
      } else {
        expect(later?.startsWith(bubble), `bubble ${j} shrank`).toBe(true);
      }
    }
  }
}

test.describe("bubble splitting", () => {
  test.skip(
    !SIM_ENABLED,
    "Requires the deterministic sim stack. Run `mise dev --sim` and set E2E_SIM=1.",
  );
  test.setTimeout(3 * TURN_TIMEOUT_MS);

  test("R2: three bubbles stream in order and survive a reload unchanged", async ({
    page,
  }) => {
    await page.goto("/c");
    await sendMessage(page, `[[pace:60]] [[say:${R2.join(BREAK)}]]`);
    await expect(page).toHaveURL(CONVERSATION_URL, {
      timeout: TURN_TIMEOUT_MS,
    });

    const frames = await watchFirstReply(page, R2[2]);

    expect(frames.at(-1)).toEqual(R2);
    expect(frames.length, "the reply streamed in steps").toBeGreaterThan(3);
    expectBubblesOnlyGrow(frames);

    await page.reload();
    await expect
      .poll(async () => (await botBubbleParts(page))[0], {
        timeout: TURN_TIMEOUT_MS,
      })
      .toEqual(R2);
  });

  test("R5: a retracted preamble is replaced in place, and stays gone after a reload", async ({
    page,
  }) => {
    await page.goto("/c");
    await sendMessage(
      page,
      `[[pace:60]] [[narrate:${PREAMBLE.join(BREAK)}]] ` +
        `[[tool:create_todo {"title": "web-bubble-r5"}]] [[say:${R5_REPLY}]]`,
    );
    await expect(page).toHaveURL(CONVERSATION_URL, {
      timeout: TURN_TIMEOUT_MS,
    });

    const frames = await watchFirstReply(page, R5_REPLY);

    expect(
      frames.some((frame) => frame[0]?.startsWith("Sure thing")),
      "the preamble was on screen before it was retracted",
    ).toBe(true);
    expect(frames.at(-1)).toEqual([R5_REPLY]);

    await page.reload();
    await expect
      .poll(async () => (await botBubbleParts(page))[0], {
        timeout: TURN_TIMEOUT_MS,
      })
      .toEqual([R5_REPLY]);
  });
});
