// @vitest-environment jsdom
/**
 * The "Setting up tools" state after a connect is derived from the catalog the
 * page already has: it shows while the integration is connected with no tools,
 * ends when a refetch (driven by the integration_status_update broadcast) brings
 * them, and ends after one bounded wait when they never arrive. It makes no
 * requests of its own. Fidelity: the broadcast-driven refetch is stood in for by
 * rerendering with the refetched catalog.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { InternalAxiosRequestConfig } from "axios";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST_CONNECT_SETTLE_TIMEOUT_MS } from "@/features/integrations/constants/connect";
import { usePostConnectSettling } from "@/features/integrations/hooks/usePostConnectSettling";
import type { Integration } from "@/features/integrations/types";
import { apiauth } from "@/lib/api/client";

const CONNECTED_NO_TOOLS = {
  id: "gmail",
  status: "connected",
  toolCount: 0,
} as Integration;
const CONNECTED_WITH_TOOLS = { ...CONNECTED_NO_TOOLS, toolCount: 12 };

let sent: InternalAxiosRequestConfig[] = [];
const realAdapter = apiauth.defaults.adapter;

function withQueryClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

function renderSettling() {
  return renderHook(
    ({ integrations }: { integrations: Integration[] }) =>
      usePostConnectSettling(integrations),
    {
      wrapper: withQueryClient,
      initialProps: { integrations: [CONNECTED_NO_TOOLS] },
    },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  sent = [];
  apiauth.defaults.adapter = async (config) => {
    sent.push(config);
    return {
      data: {},
      status: 200,
      statusText: "OK",
      headers: { "content-type": "application/json" },
      config,
    };
  };
});

afterEach(() => {
  apiauth.defaults.adapter = realAdapter;
  vi.useRealTimers();
});

describe("post-connect settling", () => {
  it("shows after a connect and clears when the refetched catalog brings tools, without requesting anything itself", async () => {
    const { result, rerender } = renderSettling();
    expect(result.current.settlingIntegrationId).toBeNull();

    act(() => result.current.beginSettling("gmail"));
    expect(result.current.settlingIntegrationId).toBe("gmail");

    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(result.current.settlingIntegrationId).toBe("gmail");
    expect(sent).toEqual([]);

    rerender({ integrations: [CONNECTED_WITH_TOOLS] });
    expect(result.current.settlingIntegrationId).toBeNull();
  });

  it("ends after one bounded wait when the tools never arrive", async () => {
    const { result } = renderSettling();

    act(() => result.current.beginSettling("gmail"));
    await act(() =>
      vi.advanceTimersByTimeAsync(POST_CONNECT_SETTLE_TIMEOUT_MS - 1),
    );
    expect(result.current.settlingIntegrationId).toBe("gmail");

    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(result.current.settlingIntegrationId).toBeNull();
    expect(sent).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });
});
