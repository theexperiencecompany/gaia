// @vitest-environment jsdom

/**
 * A send that lands in the last moments of a turn becomes a steer, which owns no
 * loading row. When the main turn ended first, the steer's own run streamed its
 * tool cards with no loading row at all (prod conversation 49ad837c, 2026-11-11).
 */
import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface StreamHandle {
  onMessage: (event: EventSourceMessage) => Promise<string | undefined>;
  onClose: (sawDone: boolean) => void;
  resolve: () => void;
}

const streams = vi.hoisted((): StreamHandle[] => []);

vi.mock("@/lib/db/chatDb", () => {
  const resolved = () => vi.fn().mockResolvedValue(undefined);
  return {
    db: {
      getAllConversations: vi.fn().mockResolvedValue([]),
      getAllMessages: vi.fn().mockResolvedValue([]),
      getMessagesForConversation: vi.fn().mockResolvedValue([]),
      putMessage: resolved(),
      putConversation: resolved(),
      updateMessage: vi.fn().mockResolvedValue(true),
      updateMessageStatus: resolved(),
      updateConversationFields: resolved(),
      persistMessagePair: resolved(),
    },
    dbEventEmitter: { on: vi.fn(), off: vi.fn() },
  };
});

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {
    fetchChatStream: vi.fn(
      (request: Omit<StreamHandle, "resolve">) =>
        new Promise<void>((resolve) => {
          streams.push({ ...request, resolve });
        }),
    ),
  },
  DuplicateTurnError: class extends Error {},
  RateLimitError: class extends Error {},
  SubscriptionRequiredError: class extends Error {},
}));
vi.mock("@/services/syncService", () => ({ syncSingleConversation: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));
vi.mock("@/features/chat/stream/unread", () => ({
  isViewingConversation: () => true,
  markConversationUnread: vi.fn(),
}));

import { textSendArgs } from "@/__tests__/helpers/sendArgs";
import { useExecutorCancelWebSocket } from "@/features/chat/hooks/useExecutorCancelWebSocket";
import { turnManager } from "@/features/chat/stream/turnManager";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import {
  steerSessionKey,
  useActiveLoading,
  useStreamStore,
} from "@/stores/streamStore";

const CONV = "conv-handover";

const frame = async (stream: StreamHandle, payload: object): Promise<void> => {
  await act(async () => {
    await stream.onMessage({
      id: "",
      event: "",
      data: JSON.stringify(payload),
    });
  });
};

// An existing conversation's identity frame carries no conversation_id.
const init = (n: number) => ({
  user_message_id: `user-${n}`,
  bot_message_id: `bot-${n}`,
  stream_id: `stream-${n}`,
});

const toolCard = {
  tool_data: {
    tool_name: "tool_calls_data",
    data: { tool_name: "search_integrations", tool_category: "integrations" },
    tool_category: "integrations",
  },
};

const send = (text: string, id: string) => {
  const args = textSendArgs(CONV, text);
  turnManager.send({
    ...args,
    options: { ...args.options, optimisticUserId: id },
  });
};

describe("the loading row while a steer outlives the main turn", () => {
  beforeEach(() => {
    streams.length = 0;
    act(() => {
      useChatStore.setState({ activeConversationId: CONV });
      useStreamStore.setState({ sessions: {} });
    });
  });

  it("passes to the steer that is still working", async () => {
    send("does resend have an mcp?", "opt-main");
    send("yup", "opt-steer");
    await act(() => Promise.resolve());
    const [main, steer] = streams;

    await frame(main, init(1));
    await frame(steer, init(2));
    await frame(main, { main_response_complete: true });
    await act(async () => {
      main.onClose(true);
    });
    await frame(steer, toolCard);
    const loading = renderHook(() => useActiveLoading());

    expect(loading.result.current.isLoading).toBe(true);

    await frame(steer, { main_response_complete: true });
    await act(async () => {
      steer.onClose(true);
    });
    loading.rerender();
    expect(loading.result.current.isLoading).toBe(false);
  });

  it("ends one waiting slot per delivered result, the main turn's first", () => {
    const steer = steerSessionKey(CONV, "s1");
    const store = useStreamStore.getState();
    act(() => {
      for (const key of [CONV, steer]) {
        store.startSession(key);
        store.updateSession(key, {
          phase: "awaiting_executor",
          spinnerActive: false,
        });
      }
    });
    const loading = renderHook(() => useActiveLoading());

    act(() => useStreamStore.getState().endAwaitingSession(CONV));
    expect(Object.keys(useStreamStore.getState().sessions)).toEqual([steer]);
    expect(loading.result.current.isLoading).toBe(true);

    act(() => useStreamStore.getState().endAwaitingSession(CONV));
    expect(loading.result.current.isLoading).toBe(false);
  });

  it("ends every waiting slot when the agent cancels everything, and only those", () => {
    const steer = steerSessionKey(CONV, "s1");
    const streaming = steerSessionKey(CONV, "s2");
    const elsewhere = "conv-other";
    const store = useStreamStore.getState();
    act(() => {
      for (const key of [CONV, steer, streaming, elsewhere]) {
        store.startSession(key);
      }
      for (const key of [CONV, steer, elsewhere]) {
        store.updateSession(key, { phase: "awaiting_executor" });
      }
    });
    const on = vi.spyOn(wsManager, "on");
    renderHook(() => useExecutorCancelWebSocket());
    const [, onCancelled] =
      on.mock.calls.find(([type]) => type === "executor.cancelled") ?? [];

    act(() => onCancelled?.({ conversation_id: CONV, cancel_all: true }));

    expect(Object.keys(useStreamStore.getState().sessions).sort()).toEqual(
      [elsewhere, streaming].sort(),
    );
  });

  it("ends only the oldest waiting slot on a targeted cancel", () => {
    const steer = steerSessionKey(CONV, "s1");
    const store = useStreamStore.getState();
    act(() => {
      for (const key of [CONV, steer]) {
        store.startSession(key);
        store.updateSession(key, { phase: "awaiting_executor" });
      }
    });
    const on = vi.spyOn(wsManager, "on");
    renderHook(() => useExecutorCancelWebSocket());
    const [, onCancelled] =
      on.mock.calls.find(([type]) => type === "executor.cancelled") ?? [];

    act(() => onCancelled?.({ conversation_id: CONV, cancel_all: false }));

    expect(Object.keys(useStreamStore.getState().sessions)).toEqual([steer]);
  });
});
