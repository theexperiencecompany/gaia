// @vitest-environment jsdom
/**
 * When the browser's PostHog identity is reset, and when it must not be.
 *
 * GlobalAuth mounts useFetchUser on every landing page, so every logged-out
 * visitor gets a 401 from /user/me. Resetting on that 401 gave each visitor a
 * fresh anonymous id before signup and stranded the landing history of 59% of
 * signups on a person nobody could join.
 */

import { ApiError } from "@shared/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { InternalAxiosRequestConfig } from "axios";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { posthogMock, fetchUserInfo } = vi.hoisted(() => ({
  posthogMock: {
    __loaded: false,
    capture: vi.fn(),
    identify: vi.fn(),
    setPersonProperties: vi.fn(),
    reset: vi.fn(),
    _isIdentified: vi.fn(),
    get_distinct_id: vi.fn(),
    get_session_id: vi.fn(),
  },
  fetchUserInfo: vi.fn(),
}));

vi.mock("posthog-js", () => ({ default: posthogMock }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  RedirectType: { push: "push", replace: "replace" },
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/" }));

vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo: () => fetchUserInfo() },
}));

import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import useFetchUser from "@/features/auth/hooks/useFetchUser";
import {
  analyticsRequestHeaders,
  flushPendingAnalytics,
  resetLegacyEmailIdentity,
} from "@/lib/analytics";
import { apiauth } from "@/lib/api/client";

const SIGNED_IN_USER = {
  user_id: "6812f0b3c9a14e2b7d5a91cc",
  email: "a@b.co",
  name: "A",
  onboarding: { completed: true },
};

function renderFetchUser(cachedUser: typeof SIGNED_IN_USER | null) {
  const queryClient = new QueryClient();
  if (cachedUser) queryClient.setQueryData(CURRENT_USER_QUERY_KEY, cachedUser);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useFetchUser(), { wrapper });
}

beforeEach(() => {
  posthogMock.__loaded = true;
  flushPendingAnalytics();
  posthogMock.__loaded = false;
  vi.clearAllMocks();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

describe("useFetchUser identity reset", () => {
  it("does not reset on a non-401 /me failure", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("down", 503));

    renderFetchUser(SIGNED_IN_USER);
    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalled());
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(posthogMock.reset).not.toHaveBeenCalled();
  });

  it("resets on a 401 that ends a signed-in session, through the pre-init queue", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("expired", 401));
    posthogMock._isIdentified.mockReturnValue(true);

    renderFetchUser(SIGNED_IN_USER);
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    expect(posthogMock.reset).not.toHaveBeenCalled();

    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(posthogMock.reset).toHaveBeenCalledTimes(1);
    // Identify replays first, so the reset is the last word on identity.
    expect(posthogMock.identify.mock.invocationCallOrder[0]).toBeLessThan(
      posthogMock.reset.mock.invocationCallOrder[0],
    );
  });

  it("resets once on a 401 that follows a 5xx on the refetch", async () => {
    fetchUserInfo
      .mockRejectedValueOnce(new ApiError("down", 503))
      .mockRejectedValue(new ApiError("expired", 401));
    posthogMock._isIdentified.mockReturnValue(true);

    const { rerender } = renderFetchUser(SIGNED_IN_USER);
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    // The next render re-reads the cleared query, so /me is asked again.
    rerender();
    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalledTimes(2));
    await act(async () => undefined);
    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(posthogMock.reset).toHaveBeenCalledTimes(1);
  });

  it("does not reset an anonymous visitor's 401", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("anonymous", 401));
    posthogMock._isIdentified.mockReturnValue(false);

    renderFetchUser(null);
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(posthogMock.reset).not.toHaveBeenCalled();
  });

  it("resets an identified browser whose profile cache was lost", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("expired", 401));
    posthogMock._isIdentified.mockReturnValue(true);

    renderFetchUser(null);
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(posthogMock.reset).toHaveBeenCalledTimes(1);
  });
});

describe("legacy email distinct_id", () => {
  it("resets a browser still carrying an email-shaped id, once", () => {
    posthogMock.__loaded = true;
    posthogMock.get_distinct_id.mockReturnValueOnce("old@example.com");
    posthogMock.get_distinct_id.mockReturnValue(
      "0199b6a2-7c1e-7d3a-9f0e-2b6c1a4d5e6f",
    );

    resetLegacyEmailIdentity();
    resetLegacyEmailIdentity();

    expect(posthogMock.reset).toHaveBeenCalledTimes(1);
  });

  it("leaves a Mongo-id identity alone", () => {
    posthogMock.__loaded = true;
    posthogMock.get_distinct_id.mockReturnValue(SIGNED_IN_USER.user_id);

    resetLegacyEmailIdentity();

    expect(posthogMock.reset).not.toHaveBeenCalled();
  });
});

describe("API request headers", () => {
  it("carries the PostHog session id once PostHog is loaded", () => {
    posthogMock.__loaded = true;
    posthogMock.get_session_id.mockReturnValue("sess-1");

    expect(analyticsRequestHeaders()).toEqual({
      "X-PostHog-Session-Id": "sess-1",
    });
  });

  it("sends no session header before init", () => {
    expect(analyticsRequestHeaders()).toEqual({});
  });

  it("puts the session id on a real API client request", async () => {
    posthogMock.__loaded = true;
    posthogMock.get_session_id.mockReturnValue("sess-3");
    let sent: InternalAxiosRequestConfig | undefined;

    await apiauth.get("/api/v1/user/me", {
      adapter: async (config) => {
        sent = config;
        return { data: {}, status: 200, statusText: "OK", headers: {}, config };
      },
    });

    expect(sent?.headers.get("X-PostHog-Session-Id")).toBe("sess-3");
  });

  async function sentClientType(): Promise<unknown> {
    let sent: InternalAxiosRequestConfig | undefined;
    await apiauth.get("/api/v1/notifications", {
      adapter: async (config) => {
        sent = config;
        return { data: {}, status: 200, statusText: "OK", headers: {}, config };
      },
    });
    return sent?.headers.get("X-Client-Type");
  }

  it("tells the server every request from the desktop app is from the desktop app", async () => {
    vi.stubGlobal("api", { isElectron: true });
    try {
      expect(await sentClientType()).toBe("desktop");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("sends no client type from the web app", async () => {
    expect(await sentClientType()).toBeUndefined();
  });
});
