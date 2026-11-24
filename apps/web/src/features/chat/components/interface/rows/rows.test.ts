import { replyItem, workItem } from "@shared/conversation/testing";
import { describe, expect, it } from "vitest";
import { type ChatRow, rowShows } from "./rows";

const NONE = { steps: [], cards: [], progress: null };
const THREAD = {
  ...NONE,
  steps: [
    { kind: "tool" as const, key: "tc-c1", data: { tool_call_id: "c1" } },
  ],
};
const CARD = {
  ...NONE,
  cards: [
    { key: "weather_data-c1", card: { tool_name: "weather_data", data: {} } },
  ],
};

const row = (item: Extract<ChatRow, { kind: "item" }>["item"]): ChatRow => ({
  kind: "item",
  item,
  draft: null,
});

describe("whether a GAIA row draws anything, read from its timeline", () => {
  it("draws a reply that has only a tool thread, or only a card", () => {
    const reply = replyItem("r1", 2, "");
    expect(rowShows(row({ ...reply, timeline: THREAD }), false)).toBe(true);
    expect(rowShows(row({ ...reply, timeline: CARD }), false)).toBe(true);
  });

  it("draws nothing for a reply with no text and an empty timeline", () => {
    expect(rowShows(row(replyItem("r1", 2, "")), false)).toBe(false);
  });

  it("draws running work once its timeline has a row", () => {
    const work = workItem("t1", 2, "running");
    expect(rowShows(row(work), false)).toBe(false);
    expect(rowShows(row({ ...work, timeline: THREAD }), false)).toBe(true);
  });

  it("draws a reply whose cards are still streaming into its draft", () => {
    const streaming: ChatRow = {
      kind: "item",
      item: replyItem("r1", 2, ""),
      draft: {
        attemptId: "a1",
        replyId: "r1",
        nextIndex: 1,
        content: {
          bubbles: [],
          tool_data: [],
          timeline: CARD,
          follow_up_actions: [],
        },
      },
    };
    expect(rowShows(streaming, false)).toBe(true);
  });
});
