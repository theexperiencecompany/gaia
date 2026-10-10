/**
 * The live-update seam behind the integrations page.
 *
 * On `integration_status_update` the handler must invalidate both the
 * integrations and tools caches (never on a malformed broadcast), and the
 * subscription must return that handler's own teardown or invalidations
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

const harness = vi.hoisted(() => ({
  wsManager: {
    on: vi.fn<(type: string, handler: StatusHandler) => void>(),
    off: vi.fn<(type: string, handler: StatusHandler) => void>(),
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("subscribes to integration_status_update with the given handler", () => {
    const handler: StatusHandler = vi.fn();

    subscribeToIntegrationStatus(handler);

    expect(harness.wsManager.on).toHaveBeenCalledTimes(1);
    expect(harness.wsManager.on).toHaveBeenCalledWith(
      INTEGRATION_STATUS_UPDATE,
      handler,
    );
  });

  it("unsubscribes the same handler it subscribed", () => {
    const handler: StatusHandler = vi.fn();

    const unsubscribe = subscribeToIntegrationStatus(handler);
    expect(harness.wsManager.off).not.toHaveBeenCalled();

    unsubscribe();

    expect(harness.wsManager.off).toHaveBeenCalledTimes(1);
    expect(harness.wsManager.off).toHaveBeenCalledWith(
      INTEGRATION_STATUS_UPDATE,
      handler,
    );
  });
});
