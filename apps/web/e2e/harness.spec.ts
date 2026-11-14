import { expect, test } from "@playwright/test";
import {
  bubbleReactions,
  type ConversationSample,
  firstShownAt,
  listBubbles,
  loadingGaps,
  longestBlindWorkMs,
} from "./harness";

/** The observation helpers against hand-built samples and a hand-built page, no app. */

const sample = (
  t: number,
  loading: string | null,
  contentLength: number,
  shown: string[] = [],
): ConversationSample => ({ t, loading, contentLength, shown });

test.describe("harness — blind work", () => {
  test("content still growing with no loading row is measured first change to last", () => {
    const samples = [
      sample(0, "Working on it", 10),
      sample(100, null, 10),
      sample(200, null, 20),
      sample(300, null, 20),
      sample(400, null, 30),
      sample(500, null, 30),
    ];
    expect(longestBlindWorkMs(samples)).toBe(300);
  });

  test("a reply that lands once as the loading row goes is one interval", () => {
    const samples = [
      sample(0, "Working on it", 10),
      sample(100, null, 40),
      sample(200, null, 40),
    ];
    expect(longestBlindWorkMs(samples)).toBe(0);
    expect(
      longestBlindWorkMs([sample(0, null, 10), sample(100, null, 40)]),
    ).toBe(100);
  });

  test("a loading row in between starts a new stretch", () => {
    const samples = [
      sample(0, null, 10),
      sample(100, null, 20),
      sample(200, "Working on it", 30),
      sample(300, null, 30),
      sample(400, null, 40),
    ];
    expect(longestBlindWorkMs(samples)).toBe(100);
  });

  test("loading gaps are the hidden-row samples inside the window", () => {
    const samples = [
      sample(0, null, 0),
      sample(100, "Working on it", 0),
      sample(200, null, 0),
      sample(300, "Working on it", 0),
      sample(400, null, 0),
    ];
    expect(loadingGaps(samples, 100, 300)).toEqual([sample(200, null, 0)]);
  });

  test("a line is first shown at the reading it appeared in", () => {
    const samples = [
      sample(0, "Working on it", 0),
      sample(100, "Working on it", 5, ["ld-1"]),
      sample(200, null, 9, ["ld-1", "ld-2"]),
    ];
    expect(firstShownAt(samples, "ld-1")).toBe(100);
    expect(firstShownAt(samples, "ld-2")).toBe(200);
    expect(() => firstShownAt(samples, "ld-3")).toThrow("ld-3");
  });
});

test.describe("harness — reading bubbles", () => {
  test("lists bubbles in DOM order with id and role, skipping empty rows", async ({
    page,
  }) => {
    await page.setContent(`
      <div data-slot="message-scroller-content">
        <div data-slot="message-scroller-item" data-message-id="u1">
          <div class="chat_bubble_container user">
            <div id="u1" class="relative">
              <div role="group" aria-label="Reactions"><span>👍</span></div>
              hello
            </div>
          </div>
        </div>
        <div data-slot="message-scroller-item" data-message-id="b0"></div>
        <div data-slot="message-scroller-item" data-message-id="b1">
          <div class="chatbubblebot_parent">Hi there</div>
        </div>
      </div>`);

    expect(await listBubbles(page)).toEqual([
      { messageId: "u1", role: "user", text: "👍\nhello" },
      { messageId: "b1", role: "bot", text: "Hi there" },
    ]);
    expect(await bubbleReactions(page, "u1")).toBe("👍");
    expect(await bubbleReactions(page, "b1")).toBe("");
  });
});
