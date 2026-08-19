/**
 * The live-update seam behind the integrations page.
 *
 * When Composio revokes a grant the backend broadcasts
 * `integration_status_update` so an open page flips "Connected" -> "Reconnect"
 * without a refresh. The handler must invalidate the integrations *and* tools
 * caches on a real update and ignore a malformed broadcast (invalidating on one
 * would blow away the whole catalog for nothing); the subscription must hand
 * back the teardown for that exact handler (a leaked one multiplies
 * invalidations on every navigation).
 *
 * Fidelity note: this workspace has no jsdom/happy-dom and no
 * `@testing-library/react`, so there is no renderer and `renderHook` is
 * unavailable. These tests therefore drive the two pieces the hook composes
 * directly, against a real `QueryClient` whose cache state is asserted after
 * invalidation. What is NOT exercised: that the hook wires them together, and
 * React's dependency-array scheduling — i.e. nothing here catches a
 * re-subscribe loop caused by an unstable handler identity.
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
