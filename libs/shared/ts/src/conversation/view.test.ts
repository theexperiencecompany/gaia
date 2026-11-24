import { afterEach, describe, expect, it, vi } from "vitest";
import { screenRows } from "./selectors";
import {
  founderConversationFrames,
  insertFrame,
  patchFrame,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  timelineDelta,
  toolCallCard,
  updateFrame,
  userItem,
  workItem,
} from "./testing";
import type { ConversationFrame, ConversationView } from "./types";
import {
  addPendingSend,
  applyFrame,
  applyPage,
  EMPTY_CONVERSATION_VIEW,
} from "./view";

const apply = (view: ConversationView, frame: ConversationFrame) => {
  const outcome = applyFrame(view, frame);
  if (outcome.status !== "applied") throw new Error(outcome.status);
  return outcome.view;
};

const ids = (view: ConversationView) => view.items.map((item) => item.id);

afterEach(() => vi.restoreAllMocks());

describe("a client's copy of the server's screen", () => {
  it("shows the founder's conversation in the server's order, never moving a shown item", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    let view = EMPTY_CONVERSATION_VIEW;
    for (const frame of founderConversationFrames()) {
      const before = ids(view);
      view = apply(view, frame);
      expect(ids(view).filter((id) => before.includes(id))).toEqual(before);
    }
    expect(ids(view)).toEqual(["u1", "u2", "work:c4f22a9a", "u3", "r2.1"]);
    expect(warn).not.toHaveBeenCalled();
  });

  it("keeps a settled reply when a page read before it settled lands later", () => {
    let view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u2", 2)));
    view = apply(view, insertFrame(replyItem("r1", 3, "Not")));
    view = apply(
      view,
      updateFrame(replyItem("r1", 3, "Not added.", "answered")),
    );
    view = apply(view, stateFrame(4, "idle"));

    view = applyPage(
      view,
      [userItem("u1", 1), userItem("u2", 2), replyItem("r1", 3, "Not")],
      { kind: "state", head: 3, display: "thinking", work: [] },
    );

    expect(
      view.items.map((item) => [
        item.id,
        item.kind === "reply" ? item.bubbles : null,
      ]),
    ).toEqual([
      ["u1", null],
      ["u2", null],
      ["r1", ["Not added."]],
    ]);
    expect([view.head, view.display]).toEqual([4, "idle"]);
  });

  it("keeps a settled reply when a page read before it settled lands before the state frame", () => {
    let view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u4", 4)));
    view = apply(view, stateFrame(8, "thinking"));
    view = apply(view, insertFrame(replyItem("r2", 9, "Seco"), 9));
    view = apply(view, updateFrame(replyItem("r2", 9, "Second turn."), 9));
    view = apply(
      view,
      updateFrame(replyItem("r2", 9, "Second turn.", "answered"), 10),
    );

    view = applyPage(view, [userItem("u4", 4), replyItem("r2", 9, "Seco")], {
      kind: "state",
      head: 9,
      display: "thinking",
      work: [],
    });
    view = apply(view, stateFrame(10, "idle"));

    expect(view.items.find((item) => item.id === "r2")).toMatchObject({
      bubbles: ["Second turn."],
      outcome: "answered",
    });
  });

  it("keeps live work cards when a page at the same head carries fewer", () => {
    let view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u1", 1)));
    view = apply(view, insertFrame(replyItem("r1", 2, ["Checked", "it."])));
    view = apply(view, stateFrame(2, "working"));

    view = applyPage(view, [replyItem("r1", 2, "Checked")], {
      kind: "state",
      head: 2,
      display: "working",
      work: [],
    });

    expect(view.items.find((item) => item.id === "r1")).toMatchObject({
      bubbles: ["Checked", "it."],
    });
  });

  it("places an item that became visible late at its seq, before later items", () => {
    let view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u1", 1)));
    view = apply(view, insertFrame(userItem("u3", 3)));
    view = apply(view, insertFrame(replyItem("r2", 2, "late")));
    expect(ids(view)).toEqual(["u1", "r2", "u3"]);
  });

  it("warns when an update would move a shown item", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u1", 1)));
    apply(view, updateFrame(userItem("u1", 5)));
    expect(warn).toHaveBeenCalledWith("[conversation] item moved", "u1", 1, 5);
  });

  it("keeps older pages under a fresh screen and replaces what the screen covers", () => {
    let view = apply(
      EMPTY_CONVERSATION_VIEW,
      screenFrame([userItem("u1", 1), replyItem("r1", 2, "old")]),
    );
    view = apply(
      view,
      screenFrame([replyItem("r1", 2, "new", "answered"), userItem("u2", 3)]),
    );
    expect(ids(view)).toEqual(["u1", "r1", "u2"]);
    expect(view.items[1]).toMatchObject({ bubbles: ["new"] });
  });

  it("ignores an update to an item older than the loaded page", () => {
    const view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u5", 5)));
    expect(apply(view, updateFrame(replyItem("r1", 1, "x")))).toBe(view);
  });

  it("shows this device's send until the server inserts it", () => {
    let view = addPendingSend(EMPTY_CONVERSATION_VIEW, {
      id: "m1",
      text: "hi",
    });
    expect(screenRows(view).map((row) => row.kind)).toEqual(["pending"]);
    view = apply(view, insertFrame(userItem("m1", 1, "hi")));
    expect(screenRows(view).map((row) => row.kind)).toEqual(["item"]);
    expect(addPendingSend(view, { id: "m1", text: "hi" })).toBe(view);
  });

  it("streams a reply's text into its item and lets go of it once the item settles", () => {
    let view = apply(
      EMPTY_CONVERSATION_VIEW,
      insertFrame(replyItem("r1", 1, "He")),
    );
    view = apply(view, replyDelta("a1", "r1", 0, "Hello"));
    view = apply(view, replyDelta("a1", "r1", 1, " there"));
    const [row] = screenRows(view);
    expect(row.kind === "item" && row.draft?.content.bubbles).toEqual([
      "Hello there",
    ]);
    view = apply(
      view,
      updateFrame(replyItem("r1", 1, "Hello there", "answered")),
    );
    expect(view.drafts).toEqual([]);
    expect(apply(view, replyDelta("a1", "r1", 2, "!"))).toEqual(view);
  });

  it("patches an item it holds, keeping its place and every step the patch did not touch", () => {
    const first = { kind: "tool" as const, key: "tc-a", data: { id: "a" } };
    const running = {
      ...workItem("t1", 2, "running"),
      timeline: { steps: [first], cards: [], progress: null },
    };
    const opened = apply(
      EMPTY_CONVERSATION_VIEW,
      screenFrame([userItem("u1", 1), running, userItem("u3", 3)]),
    );
    const view = apply(
      opened,
      patchFrame(
        "work:t1",
        [
          {
            op: "set",
            path: ["timeline", "steps", 0, "data", "output"],
            value: "out",
          },
          {
            op: "set",
            path: ["timeline", "steps", 1],
            value: { kind: "tool", key: "tc-b", data: { id: "b" } },
          },
          { op: "set", path: ["status"], value: "done" },
        ],
        4,
      ),
    );

    expect(ids(view)).toEqual(["u1", "work:t1", "u3"]);
    const work = view.items[1];
    expect(work.kind === "work" && work.status).toBe("done");
    expect(work.kind === "work" && work.timeline.steps).toEqual([
      { kind: "tool", key: "tc-a", data: { id: "a", output: "out" } },
      { kind: "tool", key: "tc-b", data: { id: "b" } },
    ]);
    expect(view.screenHead).toBe(4);
    expect(view.items[0]).toBe(opened.items[0]);
  });

  it("closes finished work's stream when a patch ends it", () => {
    let view = apply(
      EMPTY_CONVERSATION_VIEW,
      insertFrame(workItem("t1", 1, "running")),
    );
    view = apply(
      view,
      patchFrame(
        "work:t1",
        [{ op: "set", path: ["status"], value: "done" }],
        2,
      ),
    );
    expect(view.closed).toEqual({ t1: true });
  });

  it("ignores a patch for an item it does not hold", () => {
    const view = apply(EMPTY_CONVERSATION_VIEW, insertFrame(userItem("u5", 5)));
    const patch = patchFrame(
      "work:old",
      [{ op: "set", path: ["status"], value: "done" }],
      6,
    );
    expect(apply(view, patch)).toBe(view);
  });

  it("reports a patch that has no place in the item it holds, so the client reopens on the whole screen", () => {
    const view = apply(
      EMPTY_CONVERSATION_VIEW,
      insertFrame(workItem("t1", 1, "running")),
    );
    const outcome = applyFrame(
      view,
      patchFrame(
        "work:t1",
        [
          {
            op: "set",
            path: ["timeline", "steps", 3, "data", "output"],
            value: "x",
          },
        ],
        1,
      ),
    );
    expect(outcome.status).toBe("stale_copy");
    expect(outcome.view).toBe(view);
  });

  it("folds a reply's cards from the changes to its timeline, starting from none", () => {
    const card = { key: "search-c1", card: toolCallCard("c1", "Searching") };
    let view = apply(
      EMPTY_CONVERSATION_VIEW,
      timelineDelta("a1", "r1", 0, [
        { op: "set", path: ["cards", 0], value: card },
      ]),
    );
    view = apply(
      view,
      timelineDelta("a1", "r1", 1, [
        {
          op: "set",
          path: ["cards", 0, "card", "data", "output"],
          value: "found",
        },
      ]),
    );

    expect(view.drafts[0].content.timeline.cards).toEqual([
      {
        key: "search-c1",
        card: { ...card.card, data: { ...card.card.data, output: "found" } },
      },
    ]);
  });

  it("still takes a reply's cards whole, as a server older than wire 2 sends them", () => {
    const timeline = {
      steps: [],
      cards: [{ key: "search-c1", card: toolCallCard("c1", "Searching") }],
      progress: null,
    };
    const view = apply(EMPTY_CONVERSATION_VIEW, {
      kind: "reply_delta",
      attempt_id: "a1",
      reply_id: "r1",
      index: 0,
      payload: { type: "cards", tool_data: [], timeline },
    });
    expect(view.drafts[0].content.timeline).toEqual(timeline);
  });

  it("reports timeline changes that have no place in the reply's draft", () => {
    const outcome = applyFrame(
      EMPTY_CONVERSATION_VIEW,
      timelineDelta("a1", "r1", 0, [
        { op: "set", path: ["cards", 2, "card", "data"], value: 1 },
      ]),
    );
    expect(outcome.status).toBe("stale_copy");
  });

  it("reports a gap in a stream's deltas so the client reopens for a fresh screen", () => {
    const outcome = applyFrame(
      EMPTY_CONVERSATION_VIEW,
      replyDelta("a1", "r1", 1, "x"),
    );
    expect(outcome.status).toBe("index_gap");
  });
});
