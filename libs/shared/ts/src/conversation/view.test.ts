import { describe, expect, it } from "vitest";
import type { ConversationFrame } from "./frames";
import {
  entryFrame,
  entryUpdatedFrame,
  notice,
  reply,
  replySettled,
  retractFrame,
  stateFrame,
  textDelta,
  userMessage,
  workFinished,
  workStarted,
} from "./testing";
import {
  addPendingSend,
  applyFrame,
  beginReplay,
  type ConversationView,
  EMPTY_CONVERSATION_VIEW,
} from "./view";

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

const seqs = (view: ConversationView) =>
  view.entries.map((logged) => logged.seq);
const draftText = (view: ConversationView, attemptId: string) =>
  view.drafts.find((draft) => draft.attemptId === attemptId)?.content
    .responseText;

describe("applyFrame: entries", () => {
  it("keeps entries ordered by seq whatever order they arrive in", () => {
    const view = fold([
      entryFrame(3, notice("n3")),
      entryFrame(1, userMessage("m1")),
      entryFrame(2, notice("n2")),
    ]);
    expect(seqs(view)).toEqual([1, 2, 3]);
  });

  it("returns the same view for a re-sent entry with identical content", () => {
    const view = fold([entryFrame(1, userMessage("m1"))]);
    expect(applyFrame(view, entryFrame(1, userMessage("m1"))).view).toBe(view);
  });

  it("keeps the filled entry when its original append is replayed after an update", () => {
    const filled = reply("r1", "a1", "the answer");
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
  it("replaces the entry at its seq", () => {
    const view = fold([
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "filled")),
    ]);
    expect(view.entries).toHaveLength(1);
    expect(view.entries[0].entry).toEqual(reply("r1", "a1", "filled"));
  });

  it("reports an unknown seq and leaves the view untouched so the caller can refetch", () => {
    const view = fold([entryFrame(1, userMessage("m1"))]);
    const outcome = applyFrame(
      view,
      entryUpdatedFrame(7, reply("r1", "a1", "x")),
    );
    expect(outcome).toEqual({ status: "unknown_seq", seq: 7, view });
  });

  it("is a no-op when the same update is re-sent", () => {
    const view = fold([
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "x")),
    ]);
    expect(
      applyFrame(view, entryUpdatedFrame(2, reply("r1", "a1", "x"))).view,
    ).toEqual(view);
  });
});

describe("applyFrame: drafts", () => {
  it("accumulates deltas per attempt through the shared accumulator", () => {
    const view = fold([
      textDelta("a1", { replyId: "r1" }, "Hel"),
      textDelta("a2", { taskId: "k1" }, "work"),
      textDelta("a1", { replyId: "r1" }, "lo"),
    ]);
    expect(draftText(view, "a1")).toBe("Hello");
    expect(draftText(view, "a2")).toBe("work");
    expect(view.drafts.map((draft) => [draft.replyId, draft.taskId])).toEqual([
      ["r1", null],
      [null, "k1"],
    ]);
  });

  it("deletes the draft on retract and ignores deltas the dead attempt sends afterwards", () => {
    const view = fold([
      textDelta("a1", { replyId: "r1" }, "Hel"),
      retractFrame("a1"),
      textDelta("a1", { replyId: "r1" }, "late"),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("keeps the streamed draft when the empty Reply entry arrives", () => {
    const view = fold([
      textDelta("a1", { replyId: "r1" }, "Hello"),
      entryFrame(2, reply("r1", "a1")),
    ]);
    expect(draftText(view, "a1")).toBe("Hello");
  });

  it("drops the draft once the Reply entry is filled in place", () => {
    const view = fold([
      textDelta("a1", { replyId: "r1" }, "Hello"),
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "Hello")),
      textDelta("a1", { replyId: "r1" }, " replayed"),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("drops the draft once the reply settles", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      textDelta("a1", { replyId: "r1" }, "Hello"),
      entryFrame(2, reply("r1", "a1")),
      entryFrame(3, replySettled("r1", ["m1"], 1)),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("drops a task's draft when its work finishes", () => {
    const view = fold([
      entryFrame(2, workStarted("k1", 1)),
      textDelta("a9", { taskId: "k1" }, "card"),
      entryFrame(3, workFinished("k1")),
    ]);
    expect(view.drafts).toEqual([]);
  });

  it("beginReplay drops open drafts so a resumed stream rebuilds them once", () => {
    const live = fold([
      textDelta("a1", { replyId: "r1" }, "Hel"),
      textDelta("a1", { replyId: "r1" }, "lo"),
    ]);
    const resumed = fold(
      [
        textDelta("a1", { replyId: "r1" }, "Hel"),
        textDelta("a1", { replyId: "r1" }, "lo"),
      ],
      beginReplay(live),
    );
    expect(resumed).toEqual(live);
  });
});

describe("applyFrame: state", () => {
  it("replaces display, work phase and head", () => {
    const view = fold([stateFrame(4, "working", "running")]);
    expect([view.display, view.workPhase, view.head]).toEqual([
      "working",
      "running",
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

  it("returns the same view for an identical state", () => {
    const view = fold([stateFrame(5, "idle")]);
    expect(applyFrame(view, stateFrame(5, "idle")).view).toBe(view);
  });
});
