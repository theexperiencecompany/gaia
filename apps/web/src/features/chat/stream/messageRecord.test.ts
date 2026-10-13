import { createTurnAccumulator } from "@shared/chat";
import { describe, expect, it } from "vitest";

import { buildTurnMessageRecord, type EmojiAckStamp } from "./messageRecord";

const meta = {
  conversationId: "conv-1",
  botMessageId: "bot-1",
  createdAt: new Date("2026-01-01T00:00:00Z"),
  options: {
    fileData: [],
    selectedTool: null,
    toolCategory: null,
    selectedWorkflow: null,
    selectedCalendarEvent: null,
    optimisticUserId: "opt-1",
    replyToMessage: null,
    conversationId: "conv-1",
    isOnboardingDemo: false,
    isRetry: false,
  },
};

describe("buildTurnMessageRecord", () => {
  it("records the streamed text as a plain message without an ack stamp", () => {
    const acc = createTurnAccumulator("<EMOJI>😎</EMOJI>");

    const record = buildTurnMessageRecord(meta, acc, "sending");

    expect(record.content).toBe("<EMOJI>😎</EMOJI>");
    expect(record.kind).toBeUndefined();
    expect(record.reacts_to_message_id).toBeUndefined();
  });

  it("re-stamps a REACT ack as the bare emoji targeting the user message", () => {
    const acc = createTurnAccumulator("<EMOJI>😎</EMOJI>");
    const ack: EmojiAckStamp = {
      kind: "emoji_ack",
      emoji: "😎",
      reactsToMessageId: "umsg-1",
    };

    const record = buildTurnMessageRecord(meta, acc, "sent", null, ack);

    expect(record.content).toBe("😎");
    expect(record.kind).toBe("emoji_ack");
    expect(record.reacts_to_message_id).toBe("umsg-1");
  });
});
