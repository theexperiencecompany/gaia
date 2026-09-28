import { describe, expect, it } from "vitest";
import type { ReactionFoldable } from "./reactions";
import { foldReactionAcks, groupReactions, isReactionAck } from "./reactions";

interface ContentMessage extends ReactionFoldable {
  content: string;
}

interface TextMessage extends ReactionFoldable {
  text: string;
}

function contentMessage(
  overrides: Partial<ContentMessage> & { id: string },
): ContentMessage {
  return { content: "hello", ...overrides };
}

function textMessage(
  overrides: Partial<TextMessage> & { id: string },
): TextMessage {
  return { text: "hello", ...overrides };
}

const contentText = (message: ContentMessage): string => message.content;
const mobileText = (message: TextMessage): string => message.text;

describe("foldReactionAcks (shared)", () => {
  it("returns the same reference when there are no acks", () => {
    const messages = [
      contentMessage({ id: "user-1" }),
      contentMessage({ id: "bot-1" }),
    ];
    expect(foldReactionAcks(messages, contentText)).toBe(messages);
  });

  it("folds an ack onto its target and drops the ack bubble", () => {
    const target = contentMessage({ id: "user-1", content: "book it" });
    const ackMessage = contentMessage({
      id: "ack-1",
      content: "👍",
      kind: "emoji_ack",
      reacts_to_message_id: "user-1",
    });
    const result = foldReactionAcks([target, ackMessage], contentText);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("user-1");
    expect(result[0].reactions).toEqual([{ emoji: "👍", ackId: "ack-1" }]);
  });

  it("folds with a text-shaped message (mobile Message)", () => {
    const target = textMessage({ id: "user-1", text: "book it" });
    const ackMessage = textMessage({
      id: "ack-1",
      text: "✅",
      kind: "emoji_ack",
      reacts_to_message_id: "user-1",
    });
    const result = foldReactionAcks([target, ackMessage], mobileText);
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([{ emoji: "✅", ackId: "ack-1" }]);
  });

  it("resolves the target by messageId as well as id", () => {
    const target = contentMessage({ id: "user-1", messageId: "gaia-user-9" });
    const result = foldReactionAcks(
      [
        target,
        contentMessage({
          id: "ack-1",
          content: "✅",
          kind: "emoji_ack",
          reacts_to_message_id: "gaia-user-9",
        }),
      ],
      contentText,
    );
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([{ emoji: "✅", ackId: "ack-1" }]);
  });

  it("keeps an ack as a bubble when its target is absent", () => {
    const result = foldReactionAcks(
      [
        contentMessage({ id: "user-1" }),
        contentMessage({
          id: "ack-1",
          content: "👍",
          kind: "emoji_ack",
          reacts_to_message_id: "missing-target",
        }),
      ],
      contentText,
    );
    expect(result).toHaveLength(2);
    expect(result[1].kind).toBe("emoji_ack");
  });

  it("is idempotent across re-syncs (same ack id never badges twice)", () => {
    const target = contentMessage({
      id: "user-1",
      reactions: [{ emoji: "👍", ackId: "ack-1" }],
    });
    const result = foldReactionAcks(
      [
        target,
        contentMessage({
          id: "ack-1",
          content: "👍",
          kind: "emoji_ack",
          reacts_to_message_id: "user-1",
        }),
      ],
      contentText,
    );
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([{ emoji: "👍", ackId: "ack-1" }]);
  });

  it("aggregates multiple acks onto one target in order", () => {
    const result = foldReactionAcks(
      [
        textMessage({ id: "user-1", text: "book it" }),
        textMessage({
          id: "ack-1",
          text: "👍",
          kind: "emoji_ack",
          reacts_to_message_id: "user-1",
        }),
        textMessage({
          id: "ack-2",
          text: "✅",
          kind: "emoji_ack",
          reacts_to_message_id: "user-1",
        }),
      ],
      mobileText,
    );
    expect(result).toHaveLength(1);
    expect(result[0].reactions).toEqual([
      { emoji: "👍", ackId: "ack-1" },
      { emoji: "✅", ackId: "ack-2" },
    ]);
  });
});

describe("isReactionAck", () => {
  it("rejects an emoji_ack with blank content", () => {
    expect(
      isReactionAck(
        contentMessage({ id: "a", content: "  ", kind: "emoji_ack" }),
        contentText,
      ),
    ).toBe(false);
  });

  it("rejects a text message carrying an emoji", () => {
    expect(
      isReactionAck(contentMessage({ id: "a", content: "👍" }), contentText),
    ).toBe(false);
  });
});

describe("groupReactions", () => {
  it("collapses same-emoji reactions into one counted pill, in first-seen order", () => {
    expect(
      groupReactions([
        { emoji: "👍", ackId: "a" },
        { emoji: "✅", ackId: "b" },
        { emoji: "👍", ackId: "c" },
      ]),
    ).toEqual([
      { emoji: "👍", count: 2 },
      { emoji: "✅", count: 1 },
    ]);
  });
});
