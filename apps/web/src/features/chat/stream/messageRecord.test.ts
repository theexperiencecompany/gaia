import { createTurnAccumulator } from "@shared/chat";
import { describe, expect, it } from "vitest";

import { buildTurnMessageRecord } from "./messageRecord";

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
  it("records the streamed text as the reply, never a reaction", () => {
    const acc = createTurnAccumulator("<EMOJI>😎</EMOJI>");

    const record = buildTurnMessageRecord(meta, acc, "sending");

    expect(record.content).toBe("<EMOJI>😎</EMOJI>");
    expect(record.reaction).toBeUndefined();
  });

  it("marks a turn the user stopped, and only that turn", () => {
    const acc = createTurnAccumulator("Looking into dentists");

    expect(buildTurnMessageRecord(meta, acc, "sent", null, true).stopped).toBe(
      true,
    );
    expect(buildTurnMessageRecord(meta, acc, "sent").stopped).toBeNull();
  });
});
