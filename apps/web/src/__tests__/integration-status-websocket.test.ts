/**
 * The live-update seam behind the integrations page.
 *
 * When Composio revokes a grant the backend broadcasts
 * `integration_status_update` so an open page flips "Connected" -> "Reconnect"
 * without a refresh. `useIntegrationStatusWebSocket` is the only consumer: it
 * must invalidate the integrations *and* tools caches on a real update, ignore
 * a malformed broadcast (invalidating on one would blow away the whole catalog
 * for nothing), and drop its subscription on unmount (a leaked handler
 * multiplies invalidations on every navigation).
 *
 * Fidelity note: this workspace has no jsdom/happy-dom and no
 * `@testing-library/react`, so there is no renderer to mount into and
 * `renderHook` is unavailable. `useCallback`/`useEffect` are stubbed with the
 * minimum semantics the hook relies on (identity memo, run-effect-return-
 * cleanup) and the hook body is invoked directly. What runs for real: the
 * guard, the wsManager subscribe/unsubscribe pair, and a real `QueryClient`
 * whose cache state is asserted after invalidation. What is NOT exercised:
 * React's dependency-array scheduling, i.e. this cannot catch a re-subscribe
 * loop caused by an unstable `handleStatusUpdate` identity.
 */
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import { useIntegrationStatusWebSocket } from "@/features/integrations/hooks/useIntegrationStatusWebSocket";

type StatusHandler = (message: unknown) => void;
type EffectCleanup = (() => void) | undefined;
type EffectCallback = () => EffectCleanup;

const harness = vi.hoisted(() => ({
  effects: [] as EffectCallback[],
  queryClient: null as import("@tanstack/react-query").QueryClient | null,
  wsManager: {
    on: vi.fn<(type: string, handler: StatusHandler) => void>(),
    off: vi.fn<(type: string, handler: StatusHandler) => void>(),
  },
}));

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useCallback: <T>(fn: T): T => fn,
    useEffect: (effect: EffectCallback): void => {
      harness.effects.push(effect);
    },
  };
});

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => {
      if (!harness.queryClient) throw new Error("queryClient not installed");
      return harness.queryClient;
    },
  };
});

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: harness.wsManager,
}));

/** Runs the hook body and flushes its effects, mimicking a mount. */
function mountHook(): { unmount: () => void } {
  harness.effects.length = 0;
  // biome-ignore lint/correctness/useHookAtTopLevel: no DOM renderer exists in this workspace, so this driver invokes the hook body outside React on purpose.
  useIntegrationStatusWebSocket();
  const cleanups: EffectCleanup[] = harness.effects.map((effect) => effect());
  return {
    unmount: () => {
      for (const cleanup of cleanups) cleanup?.();
    },
  };
}

function subscribedHandler(): StatusHandler {
  const call = harness.wsManager.on.mock.calls.at(-1);
  if (!call) throw new Error("hook never subscribed to the ws manager");
  return call[1];
}

/** Both key sets, seeded so invalidation has something real to mark stale. */
function seedCaches(client: QueryClient): void {
  client.setQueryData(integrationKeys.me, [{ id: "notion" }]);
  client.setQueryData(toolKeys.available, [{ name: "notion_search" }]);
}

const isInvalidated = (client: QueryClient, key: readonly unknown[]): boolean =>
  client.getQueryState(key)?.isInvalidated ?? false;

describe("useIntegrationStatusWebSocket", () => {
  let queryClient: QueryClient;
  let invalidateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    harness.queryClient = queryClient;
    invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    seedCaches(queryClient);
  });

  it("subscribes to integration_status_update on mount", () => {
    mountHook();

    expect(harness.wsManager.on).toHaveBeenCalledTimes(1);
    expect(harness.wsManager.on.mock.calls[0][0]).toBe(
      "integration_status_update",
    );
  });

  it("invalidates the integrations and tools caches on a status update", () => {
    mountHook();

    subscribedHandler()({
      type: "integration_status_update",
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
    ["no data envelope", { type: "integration_status_update" }],
    ["null data", { type: "integration_status_update", data: null }],
    [
      "missing integration_id",
      { type: "integration_status_update", data: { status: "expired" } },
    ],
    [
      "empty integration_id",
      {
        type: "integration_status_update",
        data: { integration_id: "", status: "expired" },
      },
    ],
  ])("ignores a malformed broadcast with %s", (_label, message) => {
    mountHook();

    subscribedHandler()(message);

    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(isInvalidated(queryClient, integrationKeys.me)).toBe(false);
    expect(isInvalidated(queryClient, toolKeys.available)).toBe(false);
  });

  it("unsubscribes the same handler on unmount", () => {
    const { unmount } = mountHook();
    const handler = subscribedHandler();

    expect(harness.wsManager.off).not.toHaveBeenCalled();

    unmount();

    expect(harness.wsManager.off).toHaveBeenCalledTimes(1);
    expect(harness.wsManager.off).toHaveBeenCalledWith(
      "integration_status_update",
      handler,
    );
  });
});
