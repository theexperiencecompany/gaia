// @vitest-environment jsdom

import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: { updateMessage: vi.fn().mockResolvedValue(undefined) },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

import { applyMessageReaction } from "@/features/chat/utils/reactionUtils";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const CONV = "conv-1";

function message(overrides: Partial<IMessage> & { id: string }): IMessage {
  return {
    conversationId: CONV,
    content: "book it",
    role: "user",
    status: "sent",
    createdAt: new Date("2026-01-01T00:00:00Z"),
    updatedAt: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

const stored = () => useChatStore.getState().messagesByConversation[CONV];

describe("applyMessageReaction", () => {
  beforeEach(() => {
    vi.mocked(db.updateMessage).mockClear();
    act(() => {
      useChatStore
        .getState()
        .setMessagesForConversation(CONV, [
          message({ id: "user-1" }),
          message({ id: "bot-1", role: "assistant", content: "On it." }),
        ]);
    });
  });

  it("puts the reaction on the message in place and keeps it for a reload", async () => {
    await act(() =>
      applyMessageReaction(CONV, "user-1", { emoji: "🔎", by: "jev" }),
    );

    expect(stored().map((m) => m.id)).toEqual(["user-1", "bot-1"]);
    expect(stored()[0].reaction).toEqual({ emoji: "🔎", by: "jev" });
    expect(stored()[1].reaction).toBeUndefined();
    expect(db.updateMessage).toHaveBeenCalledWith("user-1", {
      reaction: { emoji: "🔎", by: "jev" },
    });
  });

  it("replaces an earlier reaction with the chat model's", async () => {
    await act(() =>
      applyMessageReaction(CONV, "user-1", { emoji: "🔎", by: "jev" }),
    );
    await act(() =>
      applyMessageReaction(CONV, "user-1", { emoji: "👍", by: "chat_model" }),
    );

    expect(stored()[0].reaction).toEqual({ emoji: "👍", by: "chat_model" });
  });

  it("still persists a reaction for a message this view has not loaded", async () => {
    await act(() =>
      applyMessageReaction(CONV, "elsewhere", {
        emoji: "👍",
        by: "chat_model",
      }),
    );

    expect(stored().every((m) => m.reaction === undefined)).toBe(true);
    expect(db.updateMessage).toHaveBeenCalledWith("elsewhere", {
      reaction: { emoji: "👍", by: "chat_model" },
    });
  });
});
