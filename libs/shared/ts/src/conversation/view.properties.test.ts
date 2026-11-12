import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFrame } from "./frames";
import { generateConversation, seededRandom } from "./testing";
import {
  applyFrame,
  beginReplay,
  type ConversationView,
  EMPTY_CONVERSATION_VIEW,
} from "./view";

const SEEDS = Array.from({ length: 200 }, (_, index) => index + 1);

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

// Deltas carry no position on the wire, so only the other four frame kinds can be told apart from a repeat.
const withDuplicates = (
  frames: ConversationFrame[],
  seed: number,
): ConversationFrame[] => {
  const random = seededRandom(seed * 7919);
  return frames.flatMap((frame) =>
    frame.kind !== "delta" && random() < 0.4 ? [frame, frame] : [frame],
  );
};

// A resumed stream restarts no later than the first delta of any attempt still open.
const replayStart = (
  frames: ConversationFrame[],
  live: ConversationView,
  seed: number,
) => {
  const open = new Set(live.drafts.map((draft) => draft.attemptId));
  const firstOpenDelta = frames.findIndex(
    (frame) => frame.kind === "delta" && open.has(frame.attempt_id),
  );
  const limit = firstOpenDelta === -1 ? frames.length : firstOpenDelta;
  return Math.floor(seededRandom(seed * 104729)() * (limit + 1));
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T10:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("applyFrame properties over generated conversations", () => {
  it.each(SEEDS)("seed %i: duplicated frames fold to the same view", (seed) => {
    const { frames } = generateConversation(seed);
    expect(fold(withDuplicates(frames, seed))).toEqual(fold(frames));
  });

  it.each(SEEDS)(
    "seed %i: a reconnect replaying a suffix folds to the same view",
    (seed) => {
      const { frames } = generateConversation(seed);
      const live = fold(frames);
      const start = replayStart(frames, live, seed);
      expect(fold(frames.slice(start), beginReplay(live))).toEqual(live);
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
    const attempts = fold(frames).drafts.map((draft) => draft.attemptId);
    for (const retracted of retractedAttempts)
      expect(attempts).not.toContain(retracted);
  });
});
