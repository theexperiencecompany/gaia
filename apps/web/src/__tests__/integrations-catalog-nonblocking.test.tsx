// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSnapshot = vi.fn();
const getStatuses = vi.fn();

vi.mock("@/features/integrations/api/integrationsApi", () => ({
  integrationsApi: {
    getMyIntegrationsSnapshot: () => getSnapshot(),
    getIntegrationStatuses: () => getStatuses(),
  },
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { INTEGRATION_ERROR: "integration:error" },
  trackEvent: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    dismiss: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: { on: vi.fn(), off: vi.fn() },
}));

import type { IntegrationStatusesResponse } from "@shared/api/generated";
import type { MyIntegrationsResponse } from "@shared/types";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const snapshot: MyIntegrationsResponse = {
  integrations: [
    {
      id: "posthog",
      name: "PostHog",
      description: "Product analytics",
      category: "business",
      source: "platform",
      managedBy: "mcp",
      status: "connected",
      requiresAuth: true,
      authType: "oauth",
      isFeatured: true,
      displayPriority: 1,
      available: true,
      slug: "posthog",
      toolCount: 1,
      cloneCount: 0,
    },
  ],
  total: 1,
};

describe("non-blocking integration catalog", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("renders the snapshot before the slower status request resolves", async () => {
    const statusRefresh = deferred<IntegrationStatusesResponse>();
    getSnapshot.mockResolvedValue(snapshot);
    getStatuses.mockReturnValue(statusRefresh.promise);

    const { result } = renderHook(() => useIntegrations(), { wrapper });

    await waitFor(() => expect(result.current.integrations).toHaveLength(1));
    expect(result.current.isPending).toBe(false);
    expect(result.current.integrations[0].status).toBe("connected");
    expect(getSnapshot).toHaveBeenCalledOnce();
    expect(getStatuses).toHaveBeenCalledOnce();

    await act(async () => {
      statusRefresh.resolve({ statuses: { posthog: false } });
      await statusRefresh.promise;
    });

    await waitFor(() =>
      expect(result.current.integrations[0].status).toBe("created"),
    );
  });
});
