import { foldReactionAcks } from "@gaia/shared/utils";
import { beforeEach, describe, expect, it } from "vitest";
import type { Message } from "@/features/chat/api/chat-api";
import { useChatStore } from "./chat-store";

const CONV = "conv-1";

function message(id: string, isUser: boolean, text = ""): Message {
  return { id, text, isUser, timestamp: new Date(0) };
}

/** The live turn as sendMessage seeds it: an earlier exchange, then the temp pair. */
function seedTurn(): void {
  useChatStore
    .getState()
    .setMessages(CONV, [
      message("u-0", true, "hey"),
      message("b-0", false, "hi!"),
      message("temp-user-1", true, "book it"),
      message("temp-ai-1", false),
    ]);
}

const live = (): Message[] =>
  useChatStore.getState().messagesByConversation[CONV] ?? [];

describe("chat store — the live turn", () => {
  beforeEach(() => {
    useChatStore.setState({ messagesByConversation: {} });
  });

  it("adopts the server ids of the turn's two messages and nothing else", () => {
    seedTurn();

    useChatStore.getState().adoptTurnMessageIds(CONV, "u-1", "b-1");

    expect(live().map((m) => m.id)).toEqual(["u-0", "b-0", "u-1", "b-1"]);
  });

  it("renders an emoji ack as a reaction on the user's message, not a bubble", () => {
    seedTurn();
    const store = useChatStore.getState();
    store.adoptTurnMessageIds(CONV, "u-1", "b-1");

    store.updateLastAssistantMessage(CONV, {
      text: "👍",
      kind: "emoji_ack",
      reacts_to_message_id: "u-1",
    });
    const rendered = foldReactionAcks(live(), (m) => m.text);

    expect(rendered.map((m) => m.id)).toEqual(["u-0", "b-0", "u-1"]);
    expect(rendered[2].reactions).toEqual([{ emoji: "👍", ackId: "b-1" }]);
  });
});
