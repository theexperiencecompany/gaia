// @vitest-environment jsdom
//
// The conversation list has no timer: it re-syncs on mount, focus, reconnect and
// the server's conversation.list_changed push. A push must sync even inside the
// mount sync's throttle window, and a burst of pushes (one per committed entry of
// a turn) must not stack concurrent syncs over the local store.
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
vi.mock("@/services/syncService", () => ({
  batchSyncConversations: () => batchSyncConversations(),
}));

const push = () => {
  for (const handler of handlers.get(CONVERSATION_LIST_CHANGED_EVENT) ?? []) {
    handler({ type: CONVERSATION_LIST_CHANGED_EVENT });
  }
};

describe("conversation list push", () => {
  beforeEach(() => {
    handlers.clear();
    batchSyncConversations.mockReset();
  });

  it("syncs on a push that lands right after the mount sync", async () => {
    batchSyncConversations.mockResolvedValue();
    renderHook(() => useBackgroundSync(true));
    await act(async () => undefined);
    expect(batchSyncConversations).toHaveBeenCalledTimes(1);

    await act(async () => push());

    expect(batchSyncConversations).toHaveBeenCalledTimes(2);
  });

  it("folds pushes that land during a sync into one more sync", async () => {
    batchSyncConversations.mockResolvedValueOnce();
    renderHook(() => useBackgroundSync(true));
    await act(async () => undefined);

    let finish: () => void = () => undefined;
    batchSyncConversations.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    batchSyncConversations.mockResolvedValue();

    await act(async () => {
      push();
      push();
      push();
    });
    expect(batchSyncConversations).toHaveBeenCalledTimes(2);

    await act(async () => finish());

    expect(batchSyncConversations).toHaveBeenCalledTimes(3);
  });
});
