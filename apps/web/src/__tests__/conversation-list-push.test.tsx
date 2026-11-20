// @vitest-environment jsdom
//
// The conversation list has no timer: it re-syncs on mount, focus and reconnect.
// A conversation.list_changed push names the row that changed, so it syncs that row
// alone and never re-reads the list; it syncs even inside the mount sync's throttle
// window, and a burst of pushes (one per committed entry of a turn) must not stack
// concurrent syncs over the local store.
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CONVERSATION_LIST_CHANGED_EVENT,
  useBackgroundSync,
} from "@/hooks/useBackgroundSync";

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: {
    on: (event: string, handler: Handler) => {
      const set = handlers.get(event) ?? new Set<Handler>();
      set.add(handler);
      handlers.set(event, set);
    },
    off: (event: string, handler: Handler) => {
      handlers.get(event)?.delete(handler);
    },
    onConnect: vi.fn(),
    offConnect: vi.fn(),
  },
}));

const batchSyncConversations = vi.fn<() => Promise<void>>();
const syncPushedConversations =
  vi.fn<(conversationIds: readonly string[]) => Promise<void>>();
vi.mock("@/services/syncService", () => ({
  batchSyncConversations: () => batchSyncConversations(),
  syncPushedConversations: (conversationIds: readonly string[]) =>
    syncPushedConversations(conversationIds),
}));

const push = (conversationId = "c1") => {
  for (const handler of handlers.get(CONVERSATION_LIST_CHANGED_EVENT) ?? []) {
    handler({
      type: CONVERSATION_LIST_CHANGED_EVENT,
      conversation_id: conversationId,
    });
  }
};

describe("conversation list push", () => {
  beforeEach(() => {
    handlers.clear();
    batchSyncConversations.mockReset();
    batchSyncConversations.mockResolvedValue();
    syncPushedConversations.mockReset();
  });

  it("syncs the pushed row, not the list, on a push right after the mount sync", async () => {
    syncPushedConversations.mockResolvedValue();
    renderHook(() => useBackgroundSync(true));
    await act(async () => undefined);
    expect(batchSyncConversations).toHaveBeenCalledTimes(1);

    await act(async () => push("c1"));

    expect(syncPushedConversations.mock.calls).toEqual([[["c1"]]]);
    expect(batchSyncConversations).toHaveBeenCalledTimes(1);
  });

  it("folds pushes that land during a sync into one more sync of their rows", async () => {
    renderHook(() => useBackgroundSync(true));
    await act(async () => undefined);

    let finish: () => void = () => undefined;
    syncPushedConversations.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    syncPushedConversations.mockResolvedValue();

    await act(async () => {
      push("c1");
      push("c2");
      push("c3");
      push("c2");
    });
    expect(syncPushedConversations.mock.calls).toEqual([[["c1"]]]);

    await act(async () => finish());

    expect(syncPushedConversations.mock.calls).toEqual([
      [["c1"]],
      [["c2", "c3"]],
    ]);
    expect(batchSyncConversations).toHaveBeenCalledTimes(1);
  });
});
