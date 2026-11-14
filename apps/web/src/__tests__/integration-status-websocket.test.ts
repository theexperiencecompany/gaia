/**
 * The live-update seam behind the integrations page.
 *
 * On `integration_status_update` the handler must invalidate both the
 * integrations and tools caches (never on a malformed broadcast); a socket
 * (re)connect re-reads them, since broadcasts sent while it was down are lost;
 * and the subscription must return its own teardown or invalidations
 * multiply on every navigation. Fidelity: no renderer here (no jsdom, no
 * `renderHook`) — these drive the hook's two pieces directly against a real
 * `QueryClient`; hook wiring and dependency-array re-subscribe aren't exercised.
 */
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import {
  createIntegrationStatusHandler,
  INTEGRATION_STATUS_UPDATE,
  subscribeToIntegrationStatus,
} from "@/features/integrations/hooks/useIntegrationStatusWebSocket";

type StatusHandler = (message: unknown) => void;
type ConnectHandler = () => void;

const harness = vi.hoisted(() => ({
  wsManager: {
    on: vi.fn<(type: string, handler: StatusHandler) => void>(),
    off: vi.fn<(type: string, handler: StatusHandler) => void>(),
    onConnect: vi.fn<(handler: ConnectHandler) => void>(),
    offConnect: vi.fn<(handler: ConnectHandler) => void>(),
  },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: harness.wsManager,
}));

/** Both key sets, seeded so invalidation has something real to mark stale. */
function seedCaches(client: QueryClient): void {
  client.setQueryData(integrationKeys.me, [{ id: "notion" }]);
  client.setQueryData(toolKeys.available, [{ name: "notion_search" }]);
}

const isInvalidated = (client: QueryClient, key: readonly unknown[]): boolean =>
  client.getQueryState(key)?.isInvalidated ?? false;

describe("createIntegrationStatusHandler", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    seedCaches(queryClient);
  });

  it("invalidates the integrations and tools caches on a status update", () => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    createIntegrationStatusHandler(queryClient)({
      type: INTEGRATION_STATUS_UPDATE,
      data: { integration_id: "notion", status: "expired" },
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: integrationKeys.all,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: toolKeys.all });
    // The keys must actually reach the cached entries, not just match a call arg.
    expect(isInvalidated(queryClient, integrationKeys.me)).toBe(true);
    expect(isInvalidated(queryClient, toolKeys.available)).toBe(true);
  });

  it.each([
    ["no data envelope", { type: INTEGRATION_STATUS_UPDATE }],
    ["null data", { type: INTEGRATION_STATUS_UPDATE, data: null }],
    [
      "missing integration_id",
      { type: INTEGRATION_STATUS_UPDATE, data: { status: "expired" } },
    ],
    [
      "empty integration_id",
      {
        type: INTEGRATION_STATUS_UPDATE,
        data: { integration_id: "", status: "expired" },
      },
    ],
  ])("ignores a malformed broadcast with %s", (_label, message) => {
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    createIntegrationStatusHandler(queryClient)(message);

    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(isInvalidated(queryClient, integrationKeys.me)).toBe(false);
    expect(isInvalidated(queryClient, toolKeys.available)).toBe(false);
  });
});

describe("subscribeToIntegrationStatus", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    seedCaches(queryClient);
  });

  it("invalidates both caches on a broadcast it subscribed to", () => {
    subscribeToIntegrationStatus(queryClient);

    expect(harness.wsManager.on).toHaveBeenCalledTimes(1);
    const [type, onStatus] = harness.wsManager.on.mock.calls[0];
    expect(type).toBe(INTEGRATION_STATUS_UPDATE);

    onStatus({
      type: INTEGRATION_STATUS_UPDATE,
      data: { integration_id: "notion", status: "connected" },
    });
    expect(isInvalidated(queryClient, integrationKeys.me)).toBe(true);
    expect(isInvalidated(queryClient, toolKeys.available)).toBe(true);
  });

  it("re-reads both caches when the socket (re)connects", () => {
    subscribeToIntegrationStatus(queryClient);

    expect(harness.wsManager.onConnect).toHaveBeenCalledTimes(1);
    const [onConnect] = harness.wsManager.onConnect.mock.calls[0];
    onConnect();

    expect(isInvalidated(queryClient, integrationKeys.me)).toBe(true);
    expect(isInvalidated(queryClient, toolKeys.available)).toBe(true);
  });

  it("unsubscribes the same handlers it subscribed", () => {
    const unsubscribe = subscribeToIntegrationStatus(queryClient);
    expect(harness.wsManager.off).not.toHaveBeenCalled();
    expect(harness.wsManager.offConnect).not.toHaveBeenCalled();

    unsubscribe();

    expect(harness.wsManager.off).toHaveBeenCalledWith(
      INTEGRATION_STATUS_UPDATE,
      harness.wsManager.on.mock.calls[0][1],
    );
    expect(harness.wsManager.offConnect).toHaveBeenCalledWith(
      harness.wsManager.onConnect.mock.calls[0][0],
    );
  });
});
