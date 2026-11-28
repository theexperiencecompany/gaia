import { replyItem, workItem } from "@shared/conversation/testing";
import { describe, expect, it } from "vitest";
import { type ChatRow, dayStarts, rowShows } from "./rows";

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
    {
      key: "screenshot_data-c1",
      card: {
        tool_name: "screenshot_data" as const,
        data: { thumbnail: "", width: null, height: null },
      },
    },
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

describe("which rows open a new calendar day", () => {
  const NOW = new Date(2026, 10, 26, 18, 0);
  const opens = (rows: ChatRow[]) =>
    dayStarts(rows, NOW).map((day) => day !== null);
  const at = (id: string, day: number, hour: number): ChatRow =>
    row({
      ...replyItem(id, 2, "hi"),
      at: new Date(2026, 10, day, hour).toISOString(),
    });

  it("names the day above the first row and above each row on a later day", () => {
    const rows = [
      at("a", 24, 9),
      at("b", 24, 23),
      at("c", 25, 0),
      at("d", 26, 8),
    ];
    expect(opens(rows)).toEqual([true, false, true, true]);
  });

  it("reads a row not logged yet as now, so it joins today's rows", () => {
    const draft: ChatRow = {
      kind: "draft",
      draft: {
        attemptId: "x",
        replyId: null,
        nextIndex: 0,
        content: replyItem("r", 2, ""),
      },
    };
    expect(opens([at("a", 26, 8), draft])).toEqual([true, false]);
    expect(opens([at("a", 25, 8), draft])).toEqual([true, true]);
    expect(dayStarts([at("a", 25, 8), draft], NOW)[1]).toBe(NOW);
  });
});
