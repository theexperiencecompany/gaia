// @vitest-environment jsdom
/**
 * Refetches no user action caused (a token renewal, the post-connect settle
 * poll, an SSE re-attach) say so, so the server never counts them as the user
 * being active.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { InternalAxiosRequestConfig } from "axios";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

import { useLiveView } from "@/features/browser/hooks/useLiveView";
import { chatApi } from "@/features/chat/api/chatApi";
import { useToolsQuery } from "@/features/chat/hooks/useToolsQuery";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationTools } from "@/features/integrations/hooks/useIntegrationTools";
import { usePostConnectSettlePolling } from "@/features/integrations/hooks/usePostConnectSettlePolling";
import type { Integration } from "@/features/integrations/types";
import { apiauth } from "@/lib/api/client";

const ORIGIN_HEADER = "X-GAIA-Request-Origin";
const LIVE_VIEW_TOKEN_TTL_SECONDS = 120;

let sent: InternalAxiosRequestConfig[] = [];
const realAdapter = apiauth.defaults.adapter;

function responseFor(url: string): unknown {
  if (url.endsWith("/live-view-token"))
    return { token: "tok", expires_in: LIVE_VIEW_TOKEN_TTL_SECONDS };
  if (url.endsWith("/integrations/me/snapshot")) return { integrations: [] };
  if (url.endsWith("/integrations/status")) return { statuses: {} };
  return { tools: [] };
}

function withQueryClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

const origins = () =>
  sent.map((config) => [
    new URL(config.url ?? "", "http://api.test").pathname,
    config.headers.get(ORIGIN_HEADER),
  ]);

beforeEach(() => {
  vi.useFakeTimers();
  sent = [];
  apiauth.defaults.adapter = async (config) => {
    sent.push(config);
    return {
      data: responseFor(config.url ?? ""),
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
  vi.unstubAllGlobals();
});

describe("the live-view token", () => {
  it("is minted, renewed and re-minted on a socket drop as background work", async () => {
    const { result } = renderHook(() => useLiveView("session-1"), {
      wrapper: withQueryClient,
    });
    await act(() => vi.advanceTimersByTimeAsync(0));

    await act(() =>
      vi.advanceTimersByTimeAsync(LIVE_VIEW_TOKEN_TTL_SECONDS * 1000),
    );
    act(() => result.current.renew());
    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(sent.length).toBeGreaterThanOrEqual(3);
    expect(new Set(sent.map((c) => c.headers.get(ORIGIN_HEADER)))).toEqual(
      new Set(["background"]),
    );
  });
});

describe("the post-connect settle poll", () => {
  const SETTLING: Integration = {
    id: "gmail",
    status: "connected",
    toolCount: 0,
  } as Integration;

  function useIntegrationsPage() {
    useIntegrations();
    useToolsQuery();
    useIntegrationTools(SETTLING);
    return usePostConnectSettlePolling([SETTLING]);
  }

  it("re-reads the catalog, statuses and tools as background work", async () => {
    const { result } = renderHook(useIntegrationsPage, {
      wrapper: withQueryClient,
    });
    await act(() => vi.advanceTimersByTimeAsync(0));
    sent = [];

    act(() => result.current.beginSettling(SETTLING.id));
    await act(() => vi.advanceTimersByTimeAsync(2_000));

    expect(origins()).toEqual(
      expect.arrayContaining([
        ["/api/v1/integrations/me/snapshot", "background"],
        ["/api/v1/integrations/status", "background"],
        ["/api/v1/integrations/gmail/tools", "background"],
        ["/api/v1/tools", "background"],
      ]),
    );
    expect(origins().every(([, origin]) => origin === "background")).toBe(true);
  });
});

describe("an executor stream subscription", () => {
  it("is a re-attach no user action caused", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("data: [DONE]\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await chatApi.subscribeToExecutorStream(
      "stream-1",
      vi.fn(),
      vi.fn(),
      vi.fn(),
      new AbortController().signal,
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(ORIGIN_HEADER)).toBe("background");
  });
});
