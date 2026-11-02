// @vitest-environment jsdom

/**
 * Stop stays on offer for the whole turn, the background executor run included:
 * pressing it stops everything (product decision). Only a result the executor
 * finished before the Stop landed is still delivered, server-side.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/db/chatDb", () => ({
  db: {
    getAllConversations: vi.fn().mockResolvedValue([]),
    getAllMessages: vi.fn().mockResolvedValue([]),
  },
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));

import { textSendArgs } from "@/__tests__/helpers/sendArgs";
import { TurnSession } from "@/features/chat/stream/turnSession";
import { useChatStore } from "@/stores/chatStore";
import { useActiveComposerLocked, useStreamStore } from "@/stores/streamStore";

const CONV = "conv-stop";

/** The private steps the SSE plumbing reaches; the transport is not under test. */
interface TurnInternals {
  acc: { toolData: { tool_name: string; tool_category?: string }[] };
  handleMainResponseComplete: () => void;
}

const mainResponseComplete = (toolCategory: string | null): void => {
  const session = new TurnSession(
    CONV,
    textSendArgs(CONV, "find me five fintech companies"),
    {
      onEnd: vi.fn(),
      onRekey: vi.fn(),
    },
  ) as unknown as TurnInternals;
  session.acc = {
    ...session.acc,
    toolData: toolCategory
      ? [{ tool_name: "call_executor", tool_category: toolCategory }]
      : [],
  };
  act(() => session.handleMainResponseComplete());
};

describe("Stop after the comms ack", () => {
  beforeEach(() => {
    act(() => {
      useChatStore.setState({ activeConversationId: CONV });
      useStreamStore.getState().startSession(CONV, undefined);
      useStreamStore.getState().updateSession(CONV, { phase: "streaming" });
    });
  });

  it("keeps Stop on offer after the turn was handed to the executor", () => {
    mainResponseComplete("executor");

    const { result } = renderHook(() => useActiveComposerLocked());
    expect(result.current).toBe(true);
  });

  it("still locks a turn comms is answering itself until the stream ends", () => {
    mainResponseComplete(null);

    const { result } = renderHook(() => useActiveComposerLocked());
    expect(result.current).toBe(true);
  });
});
