import { describe, expect, it } from "vitest";

import { foldReactionAcks } from "@/features/chat/utils/reactionUtils";
import type { IMessage } from "@/lib/db/chatDb";

function message(overrides: Partial<IMessage> & { id: string }): IMessage {
  return {
    conversationId: "conv-1",
    content: "hello",
    role: "assistant",
    status: "sent",
    createdAt: new Date("2026-01-01T00:00:00Z"),
    updatedAt: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

const userMsg = () =>
  message({ id: "user-1", content: "book it", role: "user" });
const ack = (id: string, target: string | null, emoji = "👍") =>
  message({
    id,
    content: emoji,
    kind: "emoji_ack",
    reacts_to_message_id: target,
  });

describe("foldReactionAcks", () => {
  it("returns the same reference when there are no acks", () => {
    const messages = [userMsg(), message({ id: "bot-1" })];
    expect(foldReactionAcks(messages)).toBe(messages);
  });

  it("folds an ack onto its target and drops the ack bubble", () => {
    const target = userMsg();
    const result = foldReactionAcks([target, ack("ack-1", "user-1")]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("user-1");
    expect(result[0].reactions).toEqual([{ emoji: "👍", ackId: "ack-1" }]);
  });

  it("resolves the target by messageId as well as id", () => {
    const target = { ...userMsg(), messageId: "gaia-user-9" };
    const result = foldReactionAcks([
      target,
      ack("ack-1", "gaia-user-9", "✅"),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([{ emoji: "✅", ackId: "ack-1" }]);
  });

  it("keeps an ack as a bubble when its target is absent", () => {
    const result = foldReactionAcks([
      userMsg(),
      ack("ack-1", "missing-target"),
    ]);
    expect(result).toHaveLength(2);
    expect(result[1].kind).toBe("emoji_ack");
  });

  it("keeps an ack as a bubble when it has no target", () => {
    const result = foldReactionAcks([userMsg(), ack("ack-1", null)]);
    expect(result).toHaveLength(2);
  });

  it("is idempotent across re-syncs (same ack id never badges twice)", () => {
    const target = {
      ...userMsg(),
      reactions: [{ emoji: "👍", ackId: "ack-1" }],
    };
    const result = foldReactionAcks([target, ack("ack-1", "user-1")]);
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([{ emoji: "👍", ackId: "ack-1" }]);
  });

  it("aggregates multiple acks onto one target in order", () => {
    const result = foldReactionAcks([
      userMsg(),
      ack("ack-1", "user-1", "👍"),
      ack("ack-2", "user-1", "✅"),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([
      { emoji: "👍", ackId: "ack-1" },
      { emoji: "✅", ackId: "ack-2" },
    ]);
  });

  it("handles an ack arriving before its target", () => {
    const result = foldReactionAcks([ack("ack-1", "user-1"), userMsg()]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("user-1");
    expect(result[0].reactions).toEqual([{ emoji: "👍", ackId: "ack-1" }]);
  });
});
