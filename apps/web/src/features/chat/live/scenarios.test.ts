import type { ConversationFrame, ConversationView } from "@shared/conversation";
import {
  addPendingSend,
  applyFrame,
  EMPTY_CONVERSATION_VIEW,
} from "@shared/conversation";
import {
  approvalDecided,
  approvalRequested,
  entryFrame,
  entryUpdatedFrame,
  reply,
  replySettled,
  retractFrame,
  stateFrame,
  stopRequested,
  textDelta,
  toolCardDelta,
  userMessage,
  workFinished,
  workStarted,
} from "@shared/conversation/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadingRow, visibleBubbles } from "./selectors";

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

const screen = (view: ConversationView) =>
  visibleBubbles(view).map((bubble) => {
    switch (bubble.kind) {
      case "reply":
        return `${bubble.key} "${bubble.text}"`;
      case "work":
        return `${bubble.key} cards=${bubble.toolData.length}`;
      default:
        return bubble.key;
    }
  });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T10:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("verification scenarios as frame sequences", () => {
  it("second message before commit: the restarted attempt answers both and the first one leaves no trace", () => {
    const view = fold([
      entryFrame(1, userMessage("m1", "$600")),
      stateFrame(1, "thinking"),
      textDelta("a1", { replyId: "r1" }, "Booking for $600"),
      entryFrame(2, userMessage("m2", "make it $900")),
      retractFrame("a1"),
      textDelta("a2", { replyId: "r1" }, "Booking for $900"),
      entryFrame(3, reply("r1", "a2")),
      entryUpdatedFrame(3, reply("r1", "a2", "Booking for $900")),
      entryFrame(4, replySettled("r1", ["m1", "m2"], 2)),
      stateFrame(4, "idle"),
    ]);
    expect(screen(view)).toEqual([
      "user:m1",
      "user:m2",
      'reply:r1 "Booking for $900"',
    ]);
    expect(loadingRow(view).visible).toBe(false);
  });

  it("second message mid-text: the committed reply finishes above the new message, which gets its own reply", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      textDelta("a1", { replyId: "r1" }, "First "),
      entryFrame(2, reply("r1", "a1")),
      entryFrame(3, userMessage("m2")),
      textDelta("a1", { replyId: "r1" }, "answer"),
      entryUpdatedFrame(2, reply("r1", "a1", "First answer")),
      entryFrame(4, replySettled("r1", ["m1"], 1)),
      stateFrame(4, "thinking"),
      textDelta("a2", { replyId: "r2" }, "Second"),
      entryFrame(5, reply("r2", "a2")),
    ]);
    expect(screen(view)).toEqual([
      "user:m1",
      'reply:r1 "First answer"',
      "user:m2",
      'reply:r2 "Second"',
    ]);
  });

  it("side question during work: the work bubble stays while a reply appears, display thinking then working", () => {
    const working = fold([
      entryFrame(1, userMessage("m1", "clean my inbox")),
      entryFrame(2, workStarted("k1", 1)),
      stateFrame(2, "working", "running"),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Archiving"),
      entryFrame(3, userMessage("m2", "what time is it?")),
      stateFrame(3, "thinking", "running"),
    ]);
    expect(loadingRow(working).status).toBe("thinking");
    const answered = fold(
      [
        textDelta("a2", { replyId: "r2" }, "It is 10am"),
        entryFrame(4, reply("r2", "a2")),
        entryUpdatedFrame(4, reply("r2", "a2", "It is 10am")),
        entryFrame(5, replySettled("r2", ["m2"], 3)),
        stateFrame(5, "working", "running"),
      ],
      working,
    );
    expect(screen(answered)).toEqual([
      "user:m1",
      "work:k1 cards=1",
      "user:m2",
      'reply:r2 "It is 10am"',
    ]);
    expect(loadingRow(answered)).toMatchObject({
      visible: true,
      status: "working",
    });
  });

  it("addition during work: the work keeps running and its result is one reply keyed by the task", () => {
    const view = fold([
      entryFrame(1, userMessage("m1", "email Ana")),
      entryFrame(2, workStarted("k1", 1)),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Drafting"),
      entryFrame(3, userMessage("m2", "cc Bob too")),
      textDelta("a2", { replyId: "r2" }, "Added Bob"),
      entryFrame(4, reply("r2", "a2", "Added Bob")),
      entryFrame(5, replySettled("r2", ["m2"], 3)),
      entryFrame(6, workFinished("k1")),
      textDelta("a3", { replyId: "k1" }, "Sent to Ana and Bob"),
      entryFrame(7, reply("k1", "a3")),
      entryUpdatedFrame(7, reply("k1", "a3", "Sent to Ana and Bob")),
      entryFrame(8, replySettled("k1", ["m1", "m2"], 6)),
      stateFrame(8, "idle"),
    ]);
    expect(screen(view)).toEqual([
      "user:m1",
      "user:m2",
      'reply:r2 "Added Bob"',
      'reply:k1 "Sent to Ana and Bob"',
    ]);
  });

  it("approval requested then decided: the row waits on the user, then work resumes", () => {
    const asking = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, approvalRequested("k1", "p1")),
      stateFrame(3, "awaiting_approval", "awaiting_approval"),
    ]);
    expect(loadingRow(asking)).toMatchObject({
      visible: true,
      status: "awaiting_approval",
    });
    expect(screen(asking)).toEqual(["user:m1", "work:k1 cards=0"]);
    const decided = fold(
      [
        entryFrame(4, approvalDecided("p1")),
        stateFrame(4, "working", "running"),
      ],
      asking,
    );
    expect(loadingRow(decided).status).toBe("working");
  });

  it("stop while thinking: the uncommitted attempt is retracted and the row clears", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      stateFrame(1, "thinking"),
      textDelta("a1", { replyId: "r1" }, "Let me"),
      entryFrame(2, stopRequested("s1")),
      retractFrame("a1"),
      stateFrame(2, "idle"),
    ]);
    expect(screen(view)).toEqual(["user:m1"]);
    expect(loadingRow(view).visible).toBe(false);
  });

  it("stop while working: the cancelled work's bubble goes and the row clears", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Archiving"),
      stateFrame(2, "working", "running"),
      entryFrame(3, stopRequested("s1")),
      stateFrame(3, "idle"),
      entryFrame(4, workFinished("k1", "cancelled")),
    ]);
    expect(screen(view)).toEqual(["user:m1"]);
    expect(loadingRow(view).visible).toBe(false);
  });

  it("two devices: the other device's message lands by seq while this device's send stays pending", () => {
    let view = addPendingSend(EMPTY_CONVERSATION_VIEW, {
      id: "mine",
      text: "from laptop",
    });
    view = fold([entryFrame(1, userMessage("theirs", "from phone"))], view);
    expect(screen(view)).toEqual(["user:theirs", "pending:mine"]);
    view = fold([entryFrame(2, userMessage("mine", "from laptop"))], view);
    expect(screen(view)).toEqual(["user:theirs", "user:mine"]);
  });

  it("ten-message burst: every send stays in order and one reply answers them all", () => {
    const ids = Array.from({ length: 10 }, (_, index) => `m${index + 1}`);
    let view = ids.reduce(
      (current, id) => addPendingSend(current, { id, text: id }),
      EMPTY_CONVERSATION_VIEW,
    );
    view = fold(
      [
        ...ids.map((id, index) => entryFrame(index + 1, userMessage(id))),
        entryFrame(11, reply("r1", "a1", "All noted")),
        entryFrame(12, replySettled("r1", ids, 10)),
      ],
      view,
    );
    expect(view.pending).toEqual([]);
    expect(screen(view)).toEqual([
      ...ids.map((id) => `user:${id}`),
      'reply:r1 "All noted"',
    ]);
  });

  it("reload mid-reply: a fresh view fed the snapshot then the replayed frames shows what the live view shows", () => {
    const history: ConversationFrame[] = [
      entryFrame(1, userMessage("m1")),
      stateFrame(1, "thinking"),
      textDelta("a1", { replyId: "r1" }, "Gone"),
      retractFrame("a1"),
    ];
    const replayed: ConversationFrame[] = [
      textDelta("a2", { replyId: "r1" }, "Hel"),
      entryFrame(2, reply("r1", "a2")),
      textDelta("a2", { replyId: "r1" }, "lo"),
    ];
    const live = fold([...history, ...replayed]);
    const snapshot = live.entries.map((logged) =>
      entryFrame(logged.seq, logged.entry),
    );
    const reloaded = fold([
      ...snapshot,
      stateFrame(live.head, live.display),
      ...replayed,
    ]);
    expect(visibleBubbles(reloaded)).toEqual(visibleBubbles(live));
    expect(loadingRow(reloaded)).toEqual(loadingRow(live));
    expect(screen(reloaded)).toEqual(["user:m1", 'reply:r1 "Hello"']);
  });
});
