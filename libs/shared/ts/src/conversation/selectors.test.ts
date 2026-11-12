import { describe, expect, it } from "vitest";
import {
  type LiveBubble,
  loadingRow,
  quoteFor,
  visibleBubbles,
} from "./selectors";
import {
  approvalDecided,
  approvalRequested,
  entryFrame,
  entryUpdatedFrame,
  liveTask,
  notice,
  reply,
  replyDelta,
  replySettled,
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

const describeBubble = (bubble: LiveBubble) => {
  switch (bubble.kind) {
    case "reply":
      return `${bubble.key} "${bubble.text}"`;
    case "work":
      return `${bubble.key} ${bubble.status} cards=${bubble.toolData.length}`;
    default:
      return bubble.key;
  }
};
const shape = (view: ConversationView) =>
  visibleBubbles(view).map(describeBubble);

describe("visibleBubbles", () => {
  it("shows user messages, replies and notices in seq order and hides the bookkeeping kinds", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, approvalRequested("k1", "p1")),
      entryFrame(4, approvalDecided("p1")),
      entryFrame(5, workFinished("k1")),
      entryFrame(6, reply("k1", "a1", "done")),
      entryFrame(7, replySettled("k1", ["m1"], 5)),
      entryFrame(8, stopRequested("s1")),
      entryFrame(9, notice("n1")),
    ]);
    expect(shape(view)).toEqual(["user:m1", 'reply:k1 "done"', "notice:n1"]);
  });

  it("carries the user message and the reaction filled in on it", () => {
    const reacted = userMessage("m1", "thanks", { emoji: "👍", by: "jev" }, 1);
    const view = fold([
      entryFrame(1, userMessage("m1", "thanks")),
      entryUpdatedFrame(1, reacted),
    ]);
    expect(visibleBubbles(view)[0]).toMatchObject({
      kind: "user",
      seq: 1,
      message: { id: "m1", text: "thanks" },
      reaction: { emoji: "👍", by: "jev" },
    });
  });

  it("shows the live draft in place of a reply's empty saved content", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      replyDelta("a1", null, 0, "Hel"),
      entryFrame(2, reply("r1", "a1")),
      replyDelta("a1", "r1", 1, "lo"),
    ]);
    expect(visibleBubbles(view)[1]).toMatchObject({
      kind: "reply",
      seq: 2,
      text: "Hello",
      streaming: true,
    });
  });

  it("keeps showing the draft after the fill, and the saved content once the reply settles", () => {
    const filled = fold([
      entryFrame(1, userMessage("m1")),
      replyDelta("a1", null, 0, "Hello"),
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "Hello", 1)),
    ]);
    expect(visibleBubbles(filled)[1]).toMatchObject({
      text: "Hello",
      streaming: true,
    });
    const settled = fold(
      [entryFrame(3, replySettled("r1", ["m1"], 1))],
      filled,
    );
    expect(visibleBubbles(settled)[1]).toMatchObject({
      text: "Hello",
      streaming: false,
    });
  });

  it("shows a draft with no Reply entry yet after every entry and before pending sends", () => {
    let view = fold([
      entryFrame(1, userMessage("m1")),
      replyDelta("a1", null, 0, "Hi"),
    ]);
    view = addPendingSend(view, { id: "m2", text: "second" });
    expect(shape(view)).toEqual(["user:m1", 'draft:a1 "Hi"', "pending:m2"]);
    expect(visibleBubbles(view)[1]).toMatchObject({
      seq: null,
      streaming: true,
    });
  });

  it("shows one work bubble per live task from state, at the seq it started", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, workStarted("k2", 1)),
      workCardDelta("k1", 0, "Searching mail"),
      entryFrame(4, notice("n1")),
      stateFrame(4, "awaiting_approval", [
        liveTask("k1"),
        liveTask("k2", true),
      ]),
    ]);
    expect(shape(view)).toEqual([
      "user:m1",
      "work:k1 running cards=1",
      "work:k2 awaiting_approval cards=0",
      "notice:n1",
    ]);
  });

  it("keeps the work bubble's cards after the work finishes done, until the reply keyed by it settles", () => {
    const finished = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      stateFrame(2, "working", [liveTask("k1")]),
      workCardDelta("k1", 0, "Searching mail"),
      entryFrame(3, workFinished("k1")),
      stateFrame(3, "thinking"),
    ]);
    expect(shape(finished)).toEqual(["user:m1", "work:k1 done cards=1"]);
    const narrated = fold(
      [
        replyDelta("a2", null, 0, "Found it"),
        entryFrame(4, reply("k1", "a2")),
        entryUpdatedFrame(4, reply("k1", "a2", "Found it", 1)),
        entryFrame(5, replySettled("k1", ["m1"], 3)),
      ],
      finished,
    );
    expect(shape(narrated)).toEqual(["user:m1", 'reply:k1 "Found it"']);
  });

  it("shows a finished task's logged cards when its live cards were never seen here", () => {
    const card = {
      tool_name: "tool_calls_data",
      data: { tool_call_id: "c1" },
    };
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, workFinished("k1", "done", [card])),
      stateFrame(3, "thinking"),
    ]);
    expect(shape(view)).toEqual(["user:m1", "work:k1 done cards=1"]);
    const settled = fold(
      [
        entryFrame(4, reply("k1", "a2", "Found it")),
        entryFrame(5, replySettled("k1", ["m1"], 3)),
      ],
      view,
    );
    expect(shape(settled)).toEqual(["user:m1", 'reply:k1 "Found it"']);
  });

  it("renders a task handed to running work under the work it joined", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      workCardDelta("k1", 0, "Searching mail"),
      entryFrame(3, userMessage("m2")),
      entryFrame(4, workStarted("k2", 3, "k1")),
      workCardDelta("k2", 0, "Searching more mail"),
      stateFrame(4, "working", [liveTask("k1")]),
    ]);
    expect(shape(view)).toEqual([
      "user:m1",
      "work:k1 running cards=2",
      "user:m2",
    ]);
  });

  it("shows cancelled work as stopped, keeping its cards", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      workCardDelta("k1", 0, "Archiving"),
      entryFrame(3, stopRequested("s1")),
      entryFrame(4, workFinished("k1", "cancelled")),
      stateFrame(4, "idle"),
    ]);
    expect(shape(view)).toEqual(["user:m1", "work:k1 cancelled cards=1"]);
  });

  it("renders pending sends last, in send order", () => {
    let view = addPendingSend(EMPTY_CONVERSATION_VIEW, { id: "m3", text: "c" });
    view = addPendingSend(view, { id: "m2", text: "b" });
    view = fold([entryFrame(1, userMessage("m1"))], view);
    expect(shape(view)).toEqual(["user:m1", "pending:m3", "pending:m2"]);
  });
});

describe("loadingRow", () => {
  it.each([
    ["idle", false],
    ["thinking", true],
    ["working", true],
    ["awaiting_approval", true],
  ] as const)("is visible for display %s: %s", (display, visible) => {
    const view = fold([stateFrame(1, display)]);
    expect(loadingRow(view)).toMatchObject({ visible, status: display });
  });

  it("labels the row with the newest draft's tool progress", () => {
    const view = fold([
      stateFrame(2, "working", [liveTask("k1"), liveTask("k2")]),
      workCardDelta("k1", 0, "Searching mail"),
      workCardDelta("k2", 0, "Reading calendar"),
    ]);
    expect(loadingRow(view)).toEqual({
      visible: true,
      status: "working",
      detail: "Reading calendar",
    });
  });

  it("shows no detail while idle even if a draft carries progress", () => {
    const view = fold([workCardDelta("k1", 0, "Searching mail")]);
    expect(loadingRow(view)).toEqual({
      visible: false,
      status: "idle",
      detail: null,
    });
  });
});

describe("quoteFor", () => {
  it.each([
    ["the server's quote target", "m1", "m1"],
    ["no quote when the server set none", null, null],
  ])("returns %s", (_, target, expected) => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, reply("r1", "a1", "x")),
      entryFrame(3, replySettled("r1", ["m1"], 1, target)),
    ]);
    expect(quoteFor(view, "r1")).toBe(expected);
  });

  it("returns the target the reply opened with before it settles", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, reply("r1", "a1", "x", 0, "m1")),
    ]);
    expect(quoteFor(view, "r1")).toBe("m1");
  });

  it("lets the settled target replace the one the reply opened with", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, reply("r1", "a1", "x", 0, "m1")),
      entryFrame(3, replySettled("r1", ["m1"], 1, null)),
    ]);
    expect(quoteFor(view, "r1")).toBeNull();
  });
});
