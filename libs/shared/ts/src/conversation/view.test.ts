import { describe, expect, it } from "vitest";
import {
  entryFrame,
  entryUpdatedFrame,
  liveTask,
  notice,
  reply,
  replyDelta,
  replySettled,
  retractFrame,
  stateFrame,
  userMessage,
  workCardDelta,
  workFinished,
  workStarted,
} from "./testing";
import type { ConversationFrame, ConversationView, StreamDraft } from "./types";
import { addPendingSend, applyFrame, EMPTY_CONVERSATION_VIEW } from "./view";

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

const seqs = (view: ConversationView) =>
  view.entries.map((logged) => logged.seq);
const replyDraft = (view: ConversationView, attemptId: string) =>
  view.drafts.find(
    (draft): draft is Extract<StreamDraft, { source: "reply" }> =>
      draft.source === "reply" && draft.attemptId === attemptId,
  );
const workDraft = (view: ConversationView, taskId: string) =>
  view.drafts.find(
    (draft) => draft.source === "work" && draft.taskId === taskId,
  );

describe("applyFrame: entries", () => {
  it("keeps entries ordered by seq whatever order they arrive in", () => {
    const view = fold([
      entryFrame(3, notice("n3")),
      entryFrame(1, userMessage("m1")),
      entryFrame(2, notice("n2")),
    ]);
    expect(seqs(view)).toEqual([1, 2, 3]);
  });

  it("returns the same view for a re-sent entry", () => {
    const view = fold([entryFrame(1, userMessage("m1"))]);
    expect(applyFrame(view, entryFrame(1, userMessage("m1"))).view).toBe(view);
  });

  it("keeps the filled entry when its original append is replayed after an update", () => {
    const filled = reply("r1", "a1", "the answer", 1);
    const view = fold([
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, filled),
    ]);
    const replayed = applyFrame(view, entryFrame(2, reply("r1", "a1"))).view;
    expect(replayed.entries[0].entry).toEqual(filled);
  });

  it("removes the optimistic send whose id the entry carries, and only that one", () => {
    let view = addPendingSend(EMPTY_CONVERSATION_VIEW, {
      id: "m1",
      text: "one",
    });
    view = addPendingSend(view, { id: "m2", text: "two" });
    view = applyFrame(view, entryFrame(1, userMessage("m1"))).view;
    expect(view.pending).toEqual([{ id: "m2", text: "two" }]);
  });

  it("does not add an optimistic send the log already holds", () => {
    const view = fold([entryFrame(1, userMessage("m1"))]);
    expect(addPendingSend(view, { id: "m1", text: "one" }).pending).toEqual([]);
  });

  it("keeps optimistic sends in send order and ignores a repeated send", () => {
    let view = addPendingSend(EMPTY_CONVERSATION_VIEW, { id: "m2", text: "b" });
    view = addPendingSend(view, { id: "m1", text: "a" });
    view = addPendingSend(view, { id: "m2", text: "b" });
    expect(view.pending.map((send) => send.id)).toEqual(["m2", "m1"]);
  });
});

describe("applyFrame: entry_updated", () => {
  it("replaces the entry at its seq when the revision is newer, keeping when it was appended", () => {
    const view = fold([
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "filled", 1)),
    ]);
    expect(view.entries).toEqual([
      {
        seq: 2,
        at: "2026-11-12T10:00:00+00:00",
        entry: reply("r1", "a1", "filled", 1),
      },
    ]);
  });

  it.each([
    ["an older", 1],
    ["the same", 2],
  ])("ignores an update with %s revision", (_, revision) => {
    const view = fold([
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "second", 2)),
    ]);
    expect(
      applyFrame(
        view,
        entryUpdatedFrame(2, reply("r1", "a1", "stale", revision)),
      ).view,
    ).toBe(view);
  });

  it("carries a reaction filled in place onto the user message", () => {
    const reacted = userMessage(
      "m1",
      "thanks",
      { emoji: "👍", by: "chat_model" },
      1,
    );
    const view = fold([
      entryFrame(1, userMessage("m1", "thanks")),
      entryUpdatedFrame(1, reacted),
    ]);
    expect(view.entries[0].entry).toEqual(reacted);
  });

  it("reports an unknown seq and leaves the view untouched so the caller can refetch", () => {
    const view = fold([entryFrame(1, userMessage("m1"))]);
    const outcome = applyFrame(
      view,
      entryUpdatedFrame(7, reply("r1", "a1", "x", 1)),
    );
    expect(outcome).toEqual({ status: "unknown_seq", seq: 7, view });
  });
});

describe("applyFrame: reply drafts", () => {
  it("accumulates an attempt's deltas through the shared accumulator", () => {
    const view = fold([
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a2", null, 0, "other"),
      replyDelta("a1", "r1", 1, "lo"),
    ]);
    expect(replyDraft(view, "a1")).toMatchObject({
      replyId: "r1",
      nextIndex: 2,
      content: { responseText: "Hello" },
    });
    expect(replyDraft(view, "a2")?.content.responseText).toBe("other");
  });

  it("ignores a delta whose index it already applied", () => {
    const once = fold([
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a1", null, 1, "lo"),
    ]);
    const twice = fold([
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a1", null, 1, "lo"),
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a1", null, 1, "lo"),
    ]);
    expect(twice).toEqual(once);
  });

  it("reports a skipped index instead of folding text out of order", () => {
    const view = fold([replyDelta("a1", null, 0, "Hel")]);
    expect(applyFrame(view, replyDelta("a1", null, 2, "!"))).toEqual({
      status: "index_gap",
      expected: 1,
      view,
    });
  });

  it("deletes the draft on retract and ignores deltas the dead attempt sends afterwards", () => {
    const view = fold([
      replyDelta("a1", null, 0, "Hel"),
      retractFrame("a1"),
      replyDelta("a1", null, 0, "Hel"),
      replyDelta("a1", null, 1, "late"),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("keeps the draft through the Reply entry and its in-place fill", () => {
    const view = fold([
      replyDelta("a1", null, 0, "Hello"),
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "Hello", 1)),
    ]);
    expect(replyDraft(view, "a1")?.content.responseText).toBe("Hello");
  });

  it("drops the draft when the reply settles, and ignores its replayed deltas afterwards", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      replyDelta("a1", null, 0, "Hello"),
      entryFrame(2, reply("r1", "a1")),
      entryFrame(3, replySettled("r1", ["m1"], 1)),
      replyDelta("a1", null, 0, "Hello"),
    ]);
    expect(view.drafts).toEqual([]);
  });
});

describe("applyFrame: work drafts", () => {
  it("accumulates a task's cards and ignores an index it already applied", () => {
    const view = fold([
      workCardDelta("k1", 0, "Searching"),
      workCardDelta("k1", 0, "Searching"),
      workCardDelta("k1", 1, "Reading"),
    ]);
    expect(workDraft(view, "k1")).toMatchObject({ nextIndex: 2 });
  });

  it("keeps the cards when the work finishes done", () => {
    const view = fold([
      entryFrame(2, workStarted("k1", 1)),
      workCardDelta("k1", 0, "card"),
      entryFrame(3, workFinished("k1")),
    ]);
    expect(workDraft(view, "k1")).toBeDefined();
  });

  it("keeps the cards when the work is cancelled, so the bubble can show it stopped", () => {
    const view = fold([
      workCardDelta("k1", 0, "card"),
      entryFrame(3, workFinished("k1", "cancelled")),
    ]);
    expect(workDraft(view, "k1")).toBeDefined();
  });

  it("drops the cards once the reply keyed by the task settles, and ignores their replay", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      workCardDelta("k1", 0, "card"),
      entryFrame(3, workFinished("k1")),
      entryFrame(4, reply("k1", "a9", "done")),
      entryFrame(5, replySettled("k1", ["m1"], 3)),
      workCardDelta("k1", 0, "card"),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("reports a skipped work index", () => {
    expect(
      applyFrame(EMPTY_CONVERSATION_VIEW, workCardDelta("k1", 1, "x")).status,
    ).toBe("index_gap");
  });
});

describe("applyFrame: state", () => {
  it("replaces display, live work and head", () => {
    const view = fold([
      stateFrame(4, "awaiting_approval", [liveTask("k1", true)]),
    ]);
    expect([view.display, view.work, view.head]).toEqual([
      "awaiting_approval",
      [liveTask("k1", true)],
      4,
    ]);
  });

  it("ignores a state older than the one applied, as a replay re-sends it", () => {
    const view = fold([stateFrame(5, "idle"), stateFrame(3, "thinking")]);
    expect([view.display, view.head]).toEqual(["idle", 5]);
  });

  it("applies a new display at the same head, since comms changes phase without an entry", () => {
    const view = fold([stateFrame(5, "idle"), stateFrame(5, "thinking")]);
    expect(view.display).toBe("thinking");
  });
});
