import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadingRow, visibleBubbles } from "./selectors";
import { attemptMarker, generateConversation, seededRandom } from "./testing";
import type { ConversationView } from "./types";
import { addPendingSend, applyFrame, EMPTY_CONVERSATION_VIEW } from "./view";

const SEEDS = Array.from({ length: 200 }, (_, index) => index + 1);

// Every prefix of a generated conversation, with repeated frames and sends pending at random points.
function* prefixViews(seed: number): Generator<ConversationView> {
  const { frames } = generateConversation(seed);
  const random = seededRandom(seed * 31);
  let view = EMPTY_CONVERSATION_VIEW;
  for (const [index, frame] of frames.entries()) {
    if (random() < 0.1)
      view = addPendingSend(view, { id: `local-${index}`, text: "hi" });
    view = applyFrame(view, frame).view;
    // Streams re-send frames after a reconnect; the screen must not change for it.
    if (random() < 0.3) view = applyFrame(view, frame).view;
    yield view;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T10:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("selector properties over generated conversations", () => {
  it.each(SEEDS)(
    "seed %i: bubbles are ordered by seq, unsaved drafts next, pending sends last",
    (seed) => {
      const rank = { logged: 0, unopened: 1, pending: 2 };
      for (const view of prefixViews(seed)) {
        const bubbles = visibleBubbles(view);
        const ranks = bubbles.map((bubble) =>
          bubble.kind === "pending"
            ? rank.pending
            : bubble.seq === null
              ? rank.unopened
              : rank.logged,
        );
        expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
        const seqs = bubbles.flatMap((bubble) =>
          bubble.kind !== "pending" && bubble.seq !== null ? [bubble.seq] : [],
        );
        expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
      }
    },
  );

  it.each(SEEDS)("seed %i: no bubble appears twice", (seed) => {
    for (const view of prefixViews(seed)) {
      const keys = visibleBubbles(view).map((bubble) => bubble.key);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it.each(SEEDS)(
    "seed %i: the loading row shows exactly when display is not idle",
    (seed) => {
      for (const view of prefixViews(seed)) {
        expect(loadingRow(view).visible).toBe(view.display !== "idle");
      }
    },
  );

  it.each(SEEDS)(
    "seed %i: nothing a retracted attempt streamed stays on screen",
    (seed) => {
      const { frames, retractedAttempts } = generateConversation(seed);
      let view = EMPTY_CONVERSATION_VIEW;
      const retracted = new Set<string>();
      for (const frame of frames) {
        view = applyFrame(view, frame).view;
        if (frame.kind === "retract") retracted.add(frame.attempt_id);
        const text = visibleBubbles(view)
          .map((bubble) => (bubble.kind === "reply" ? bubble.text : ""))
          .join("");
        for (const attemptId of retracted)
          expect(text).not.toContain(attemptMarker(attemptId));
      }
      expect([...retracted].sort()).toEqual([...retractedAttempts].sort());
    },
  );
});
