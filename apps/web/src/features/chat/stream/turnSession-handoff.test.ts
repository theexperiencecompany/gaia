// @vitest-environment jsdom

/**
 * Once comms hands a turn to the background executor, the composer stops
 * offering Stop.
 *
 * Regression for prod eefc68cc: the SSE stays open for the whole executor run,
 * so Stop stayed on screen after the ack, and pressing it threw the finished
 * result away. The run is now stopped by asking, the way it is everywhere else.
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

const CONV = "conv-handoff";

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

describe("the composer after the comms ack", () => {
  beforeEach(() => {
    act(() => {
      useChatStore.setState({ activeConversationId: CONV });
      useStreamStore.getState().startSession(CONV, undefined);
      useStreamStore.getState().updateSession(CONV, { phase: "streaming" });
    });
  });

  it("offers no Stop once the turn was handed to the executor", () => {
    mainResponseComplete("executor");

    const { result } = renderHook(() => useActiveComposerLocked());
    expect(result.current).toBe(false);
  });

  it("still locks a turn comms is answering itself until the stream ends", () => {
    mainResponseComplete(null);

    const { result } = renderHook(() => useActiveComposerLocked());
    expect(result.current).toBe(true);
  });
});
