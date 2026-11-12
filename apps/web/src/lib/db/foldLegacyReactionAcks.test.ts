import { describe, expect, it } from "vitest";

import {
  foldLegacyReactionAcks,
  type LegacyStoredMessage,
} from "@/lib/db/foldLegacyReactionAcks";

function message(
  overrides: Partial<LegacyStoredMessage> & { id: string },
): LegacyStoredMessage {
  return {
    conversationId: "conv-1",
    content: "book it",
    role: "user",
    status: "sent",
    createdAt: new Date("2026-01-01T00:00:00Z"),
    updatedAt: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

const ack = (
  id: string,
  target: string,
  overrides: Partial<LegacyStoredMessage> = {},
) =>
  message({
    id,
    role: "assistant",
    content: "👍",
    kind: "emoji_ack",
    reacts_to_message_id: target,
    ...overrides,
  });

const CARD = { tool_name: "calendar_events", data: { events: [] } };

describe("foldLegacyReactionAcks", () => {
  it("turns an ack without cards into the reaction on its message and removes it", () => {
    const { updated, removedIds } = foldLegacyReactionAcks([
      message({ id: "user-1" }),
      ack("ack-1", "user-1"),
    ]);

    expect(removedIds).toEqual(["ack-1"]);
    expect(updated).toEqual([
      expect.objectContaining({
        id: "user-1",
        reaction: { emoji: "👍", by: "chat_model" },
      }),
    ]);
  });

  it("keeps an ack with cards as a message with no text", () => {
    const { updated, removedIds } = foldLegacyReactionAcks([
      message({ id: "user-1" }),
      ack("ack-1", "user-1", {
        tool_data: [CARD] as LegacyStoredMessage["tool_data"],
      }),
    ]);

    expect(removedIds).toEqual([]);
    const kept = updated.find((m) => m.id === "ack-1");
    expect(kept?.content).toBe("");
    expect(kept?.tool_data).toEqual([CARD]);
    expect(kept).not.toHaveProperty("kind");
    expect(kept).not.toHaveProperty("reacts_to_message_id");
  });

  it("keeps an ack whose message is gone as a plain text message", () => {
    const { updated, removedIds } = foldLegacyReactionAcks([
      ack("ack-1", "trimmed-off"),
    ]);

    expect(removedIds).toEqual([]);
    expect(updated).toHaveLength(1);
    expect(updated[0].content).toBe("👍");
    expect(updated[0]).not.toHaveProperty("kind");
  });

  it("leaves a history without acks untouched", () => {
    expect(
      foldLegacyReactionAcks([
        message({ id: "user-1" }),
        message({ id: "bot-1", role: "assistant", content: "Done." }),
      ]),
    ).toEqual({ updated: [], removedIds: [] });
  });
});
