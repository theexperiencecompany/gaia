// @vitest-environment jsdom

import type { ChatStreamEvent } from "@shared/chat";
/**
 * A reaction frame badges the user's message the moment it lands; it is not the
 * turn's answer, so the turn keeps its loading row and goes on to reply.
 */
import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getAllConversations: vi.fn().mockResolvedValue([]),
    getAllMessages: vi.fn().mockResolvedValue([]),
    updateMessage: vi.fn().mockResolvedValue(undefined),
    putMessage: vi.fn().mockResolvedValue("id"),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

import { textSendArgs } from "@/__tests__/helpers/sendArgs";
import { TurnSession } from "@/features/chat/stream/turnSession";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

const CONV = "conv-react";

interface TurnInternals {
  dispatchEvent: (event: ChatStreamEvent) => Promise<string | undefined>;
  acc: { responseText: string };
}

const reaction = (
  emoji: string,
  by: "jev" | "chat_model",
): ChatStreamEvent => ({
  type: "reaction",
  messageId: "user-1",
  reaction: { emoji, by },
});

describe("a reaction frame during a turn", () => {
  let session: TurnInternals;

  beforeEach(() => {
    act(() => {
      useChatStore.setState({ activeConversationId: CONV });
      useChatStore.getState().setMessagesForConversation(CONV, [
        {
          id: "user-1",
          conversationId: CONV,
          content: "find my flight email",
          role: "user",
          status: "sent",
          createdAt: new Date("2026-01-01T00:00:00Z"),
          updatedAt: new Date("2026-01-01T00:00:00Z"),
        },
      ]);
      useStreamStore.getState().startSession(CONV, undefined);
      useStreamStore
        .getState()
        .updateSession(CONV, { phase: "streaming", spinnerActive: true });
    });
    session = new TurnSession(
      CONV,
      textSendArgs(CONV, "find my flight email"),
      {
        onEnd: vi.fn(),
        onRekey: vi.fn(),
      },
    ) as unknown as TurnInternals;
  });

  it("badges the user's message and leaves the turn working", async () => {
    await act(async () => {
      await session.dispatchEvent(reaction("🔎", "jev"));
    });

    const [user] = useChatStore.getState().messagesByConversation[CONV];
    expect(user.reaction).toEqual({ emoji: "🔎", by: "jev" });
    const live = useStreamStore.getState().sessions[CONV];
    expect(live?.phase).toBe("streaming");
    expect(live?.spinnerActive).toBe(true);
    expect(session.acc.responseText).toBe("");
  });

  it("swaps in the chat model's emoji in place of the instant one", async () => {
    await act(async () => {
      await session.dispatchEvent(reaction("🔎", "jev"));
      await session.dispatchEvent(reaction("👍", "chat_model"));
    });

    const messages = useChatStore.getState().messagesByConversation[CONV];
    expect(messages).toHaveLength(1);
    expect(messages[0].reaction).toEqual({ emoji: "👍", by: "chat_model" });
  });
});
