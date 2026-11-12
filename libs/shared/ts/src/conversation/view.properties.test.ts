import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFrame } from "./frames";
import { generateConversation, seededRandom } from "./testing";
import {
  applyFrame,
  type ConversationView,
  EMPTY_CONVERSATION_VIEW,
} from "./view";

const SEEDS = Array.from({ length: 200 }, (_, index) => index + 1);

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

const withDuplicates = (
  frames: ConversationFrame[],
  seed: number,
): ConversationFrame[] => {
  const random = seededRandom(seed * 7919);
  return frames.flatMap((frame) => (random() < 0.4 ? [frame, frame] : [frame]));
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T10:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("applyFrame properties over generated conversations", () => {
  it.each(SEEDS)(
    "seed %i: duplicated frames of every kind fold to the same view",
    (seed) => {
      const { frames } = generateConversation(seed);
      expect(fold(withDuplicates(frames, seed))).toEqual(fold(frames));
    },
  );

  it.each(SEEDS)(
    "seed %i: a reconnect replaying from any earlier frame folds to the same view",
    (seed) => {
      const { frames } = generateConversation(seed);
      const live = fold(frames);
      const start = Math.floor(
        seededRandom(seed * 104729)() * (frames.length + 1),
      );
      expect(fold(withDuplicates(frames.slice(start), seed + 1), live)).toEqual(
        live,
      );
    },
  );

  it.each(SEEDS)(
    "seed %i: every delta applies cleanly in stream order",
    (seed) => {
      const { frames } = generateConversation(seed);
      let view = EMPTY_CONVERSATION_VIEW;
      for (const frame of withDuplicates(frames, seed)) {
        const outcome = applyFrame(view, frame);
        expect(outcome.status).toBe("applied");
        view = outcome.view;
      }
    },
  );

  it.each(SEEDS)("seed %i: entries stay strictly ascending by seq", (seed) => {
    const { frames } = generateConversation(seed);
    const seqs = fold(withDuplicates(frames, seed)).entries.map(
      (logged) => logged.seq,
    );
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
    expect(new Set(seqs).size).toBe(seqs.length);
  });

  it.each(SEEDS)("seed %i: no retracted attempt keeps a draft", (seed) => {
    const { frames, retractedAttempts } = generateConversation(seed);
    const attempts = fold(frames).drafts.flatMap((draft) =>
      draft.source === "reply" ? [draft.attemptId] : [],
    );
    for (const retracted of retractedAttempts)
      expect(attempts).not.toContain(retracted);
  });
});
