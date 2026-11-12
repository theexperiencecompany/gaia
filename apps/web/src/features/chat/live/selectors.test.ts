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
  notice,
  reply,
  replySettled,
  stateFrame,
  stopRequested,
  textDelta,
  toolCardDelta,
  userMessage,
  workFinished,
  workStarted,
} from "@shared/conversation/testing";
import { describe, expect, it } from "vitest";
import { loadingRow, visibleBubbles } from "./selectors";

const fold = (
  frames: ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

const shape = (view: ConversationView) =>
  visibleBubbles(view).map((bubble) =>
    bubble.kind === "reply"
      ? `reply:${bubble.replyId}:${bubble.text}`
      : bubble.key,
  );

describe("visibleBubbles", () => {
  it("shows user messages, replies and notices in seq order and hides the bookkeeping kinds", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, approvalRequested("k1", "p1")),
      entryFrame(4, approvalDecided("p1")),
      entryFrame(5, workFinished("k1")),
      entryFrame(6, reply("r1", "a1", "done")),
      entryFrame(7, replySettled("r1", ["m1"], 5)),
      entryFrame(8, stopRequested("s1")),
      entryFrame(9, notice("n1")),
    ]);
    expect(shape(view)).toEqual(["user:m1", "reply:r1:done", "notice:n1"]);
  });

  it("carries the user message itself so the screen can read its fields", () => {
    const view = fold([entryFrame(1, userMessage("m1", "hello"))]);
    expect(visibleBubbles(view)[0]).toMatchObject({
      kind: "user",
      seq: 1,
      message: { id: "m1", text: "hello" },
    });
  });

  it("shows the live draft in place of a reply's empty saved content", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      textDelta("a1", { replyId: "r1" }, "Hel"),
      entryFrame(2, reply("r1", "a1")),
      textDelta("a1", { replyId: "r1" }, "lo"),
    ]);
    expect(visibleBubbles(view)[1]).toMatchObject({
      kind: "reply",
      seq: 2,
      text: "Hello",
      streaming: true,
    });
  });

  it("shows the saved content once the reply is filled in place", () => {
    const view = fold([
      textDelta("a1", { replyId: "r1" }, "Hel"),
      entryFrame(2, reply("r1", "a1")),
      entryUpdatedFrame(2, reply("r1", "a1", "Hello there")),
    ]);
    expect(visibleBubbles(view)[0]).toMatchObject({
      kind: "reply",
      text: "Hello there",
      streaming: false,
    });
  });

  it("shows a draft whose reply has no entry yet after every entry and before pending sends", () => {
    let view = fold([
      entryFrame(1, userMessage("m1")),
      textDelta("a1", { replyId: "r1" }, "Hi"),
    ]);
    view = addPendingSend(view, { id: "m2", text: "second" });
    expect(shape(view)).toEqual(["user:m1", "reply:r1:Hi", "pending:m2"]);
    expect(visibleBubbles(view)[1]).toMatchObject({
      seq: null,
      streaming: true,
    });
  });

  it("shows one work bubble per live task with its streamed cards, at the seq it started", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      entryFrame(3, workStarted("k2", 1)),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Searching mail"),
      entryFrame(4, notice("n1")),
    ]);
    expect(shape(view)).toEqual(["user:m1", "work:k1", "work:k2", "notice:n1"]);
    const [, first, second] = visibleBubbles(view);
    expect(first.kind === "work" && first.toolData).toHaveLength(1);
    expect(second.kind === "work" && second.toolData).toEqual([]);
  });

  it("drops the work bubble when its work finishes", () => {
    const view = fold([
      entryFrame(1, userMessage("m1")),
      entryFrame(2, workStarted("k1", 1)),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Searching mail"),
      entryFrame(3, workFinished("k1")),
    ]);
    expect(shape(view)).toEqual(["user:m1"]);
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
      stateFrame(2, "working", "running"),
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Searching mail"),
      toolCardDelta("w2", { taskId: "k2" }, "c2", "Reading calendar"),
    ]);
    expect(loadingRow(view)).toEqual({
      visible: true,
      status: "working",
      detail: "Reading calendar",
    });
  });

  it("shows no detail while idle even if a draft carries progress", () => {
    const view = fold([
      toolCardDelta("w1", { taskId: "k1" }, "c1", "Searching mail"),
    ]);
    expect(loadingRow(view)).toEqual({
      visible: false,
      status: "idle",
      detail: null,
    });
  });
});
