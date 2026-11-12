import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadingRow, quoteFor, visibleBubbles } from "./selectors";
import {
  approvalDecided,
  approvalRequested,
  entryFrame,
  entryUpdatedFrame,
  liveTask,
  reply,
  replyDelta,
  replySettled,
  retractFrame,
  stateFrame,
  stopRequested,
  userMessage,
  workCardDelta,
  workFinished,
  workStarted,
} from "./testing";
import type { ConversationFrame, ConversationView } from "./types";
import { addPendingSend, applyFrame, EMPTY_CONVERSATION_VIEW } from "./view";

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
        return `${bubble.key} ${bubble.status} cards=${bubble.toolData.length}`;
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
  it("second message before commit: the restarted attempt answers both and the first leaves no trace", () => {
    const view = fold([
      entryFrame(1, userMessage("m1", "$600")),
      stateFrame(1, "thinking"),
      replyDelta("a1", null, 0, "Booking for $600"),
      entryFrame(2, userMessage("m2", "make it $900")),
      retractFrame("a1"),
      replyDelta("a2", null, 0, "Booking for $900"),
      entryFrame(3, reply("r1", "a2")),
      entryUpdatedFrame(3, reply("r1", "a2", "Booking for $900", 1)),
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
      replyDelta("a1", null, 0, "First "),
      entryFrame(2, reply("r1", "a1")),
      entryFrame(3, userMessage("m2")),
      replyDelta("a1", "r1", 1, "answer"),
      entryUpdatedFrame(2, reply("r1", "a1", "First answer", 1)),
      entryFrame(4, replySettled("r1", ["m1"], 1)),
      stateFrame(4, "thinking"),
      replyDelta("a2", null, 0, "Second"),
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
      stateFrame(2, "working", [liveTask("k1")]),
      workCardDelta("k1", 0, "Archiving"),
      entryFrame(3, userMessage("m2", "what time is it?")),
      stateFrame(3, "thinking", [liveTask("k1")]),
    ]);
    expect(loadingRow(working).status).toBe("thinking");
    const answered = fold(
      [
        replyDelta("a2", null, 0, "It is 10am"),
        entryFrame(4, reply("r2", "a2")),
        entryUpdatedFrame(4, reply("r2", "a2", "It is 10am", 1)),
        entryFrame(5, replySettled("r2", ["m2"], 3)),
        stateFrame(5, "working", [liveTask("k1")]),
      ],
      working,
    );
    expect(screen(answered)).toEqual([
      "user:m1",
      "work:k1 running cards=1",
      "user:m2",
      'reply:r2 "It is 10am"',
    ]);
    expect(loadingRow(answered)).toMatchObject({
      visible: true,
      status: "working",
    });
  });

  it("addition during work: the work keeps its cards and its result becomes one reply keyed by the task", () => {
    const view = fold([
      entryFrame(1, userMessage("m1", "email Ana")),
      entryFrame(2, workStarted("k1", 1)),
      stateFrame(2, "working", [liveTask("k1")]),
      workCardDelta("k1", 0, "Drafting"),
      entryFrame(3, userMessage("m2", "cc Bob too")),
      replyDelta("a2", null, 0, "Added Bob"),
      entryFrame(4, reply("r2", "a2", "Added Bob")),
      entryFrame(5, replySettled("r2", ["m2"], 3)),
      entryFrame(6, workFinished("k1")),
      stateFrame(6, "thinking"),
    ]);
    expect(screen(view)).toEqual([
      "user:m1",
      "work:k1 done cards=1",
      "user:m2",
      'reply:r2 "Added Bob"',
    ]);
    const narrated = fold(
      [
        replyDelta("a3", null, 0, "Sent to Ana and Bob"),
        entryFrame(7, reply("k1", "a3")),
        entryUpdatedFrame(7, reply("k1", "a3", "Sent to Ana and Bob", 1)),
        entryFrame(8, replySettled("k1", ["m1", "m2"], 6)),
        stateFrame(8, "idle"),
      ],
      view,
    );
    expect(screen(narrated)).toEqual([
      "user:m1",
      "user:m2",
      'reply:r2 "Added Bob"',
      'reply:k1 "Sent to Ana and Bob"',
    ]);
  });

  it("approval requested then decided: the row and the work bubble wait on the user, then work resumes", () => {
    const asking = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, approvalRequested("k1", "p1")),
      stateFrame(3, "awaiting_approval", [liveTask("k1", true)]),
    ]);
    expect(loadingRow(asking)).toMatchObject({
      visible: true,
      status: "awaiting_approval",
    });
    expect(screen(asking)).toEqual([
      "user:m1",
      "work:k1 awaiting_approval cards=0",
    ]);
    const decided = fold(
      [
        entryFrame(4, approvalDecided("p1")),
        stateFrame(4, "working", [liveTask("k1")]),
      ],
      asking,
    );
    expect(loadingRow(decided).status).toBe("working");
    expect(screen(decided)).toEqual(["user:m1", "work:k1 running cards=0"]);
  });

  it("stop while thinking: the uncommitted attempt is retracted and the row clears", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      stateFrame(1, "thinking"),
      replyDelta("a1", null, 0, "Let me"),
      entryFrame(2, stopRequested("s1")),
      retractFrame("a1"),
      stateFrame(2, "idle"),
    ]);
    expect(screen(view)).toEqual(["user:m1"]);
    expect(loadingRow(view).visible).toBe(false);
  });

  it("stop while working: the cancelled work shows as stopped with its cards and the row clears", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      stateFrame(2, "working", [liveTask("k1")]),
      workCardDelta("k1", 0, "Archiving"),
      entryFrame(3, stopRequested("s1")),
      entryFrame(4, workFinished("k1", "cancelled")),
      stateFrame(4, "idle"),
    ]);
    expect(screen(view)).toEqual(["user:m1", "work:k1 cancelled cards=1"]);
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
      replyDelta("a1", null, 0, "Gone"),
      retractFrame("a1"),
    ];
    const replayed: ConversationFrame[] = [
      replyDelta("a2", null, 0, "Hel"),
      entryFrame(2, reply("r1", "a2")),
      replyDelta("a2", "r1", 1, "lo"),
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

  it("late result: the reply narrating old work quotes the request that started it", () => {
    const view = fold([
      entryFrame(1, userMessage("m1", "book a table")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, userMessage("m2", "how's the weather?")),
      entryFrame(4, reply("r2", "a2", "Sunny")),
      entryFrame(5, replySettled("r2", ["m2"], 3, null)),
      entryFrame(6, workFinished("k1")),
      entryFrame(7, reply("k1", "a3", "Table booked for 8pm")),
      entryFrame(8, replySettled("k1", ["m1"], 6, "m1")),
    ]);
    expect(quoteFor(view, "k1")).toBe("m1");
    expect(quoteFor(view, "r2")).toBeNull();
  });
});
