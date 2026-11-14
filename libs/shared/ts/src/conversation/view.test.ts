import { afterEach, describe, expect, it, vi } from "vitest";
import { screenRows } from "./selectors";
import {
  founderConversationFrames,
  insertFrame,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  updateFrame,
  userItem,
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

  it("reports a gap in a stream's deltas so the client reopens for a fresh screen", () => {
    const outcome = applyFrame(
      EMPTY_CONVERSATION_VIEW,
      replyDelta("a1", "r1", 1, "x"),
    );
    expect(outcome.status).toBe("index_gap");
  });
});
