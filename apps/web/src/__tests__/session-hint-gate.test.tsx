// @vitest-environment jsdom
/** Marketing pages ask /me only for a browser the API marked signed in. */
import { ApiError } from "@shared/api";
import { SESSION_HINT_COOKIE } from "@shared/utils/sessionCookies";
import {
  dehydrate,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  type PersistedClient,
  type Persister,
  PersistQueryClientProvider,
} from "@tanstack/react-query-persist-client";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { fetchUserInfo } = vi.hoisted(() => ({ fetchUserInfo: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  RedirectType: { push: "push", replace: "replace" },
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/" }));

vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo: () => fetchUserInfo() },
}));

import {
  CURRENT_USER_QUERY_KEY,
  SessionHintGateProvider,
  useCurrentUser,
} from "@/features/auth/hooks/useCurrentUser";
import useFetchUser from "@/features/auth/hooks/useFetchUser";

const SIGNED_IN_USER = {
  user_id: "6812f0b3c9a14e2b7d5a91cc",
  email: "a@b.co",
  name: "A",
  onboarding: { completed: true },
};

/** What document.cookie reads back; the API writes the hint, the web only reads it. */
let cookieJar = "";
const setHint = () => {
  cookieJar = `locale=en; ${SESSION_HINT_COOKIE}=1`;
};
const clearHint = () => {
  cookieJar = "locale=en";
};

/** GlobalAuth's driver plus a navbar-style reader, as a marketing page mounts them. */
const useMarketingPage = () => {
  useFetchUser();
  return useCurrentUser();
};

function renderPage({
  gated = true,
  cachedUser = null,
}: {
  gated?: boolean;
  cachedUser?: typeof SIGNED_IN_USER | null;
} = {}) {
  const queryClient = new QueryClient();
  if (cachedUser) queryClient.setQueryData(CURRENT_USER_QUERY_KEY, cachedUser);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <SessionHintGateProvider value={gated}>
        {children}
      </SessionHintGateProvider>
    </QueryClientProvider>
  );
  return { queryClient, ...renderHook(useMarketingPage, { wrapper }) };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.spyOn(document, "cookie", "get").mockImplementation(() => cookieJar);
  fetchUserInfo.mockResolvedValue(SIGNED_IN_USER);
});

afterEach(clearHint);

describe("marketing pages", () => {
  it("ask /me nothing for a visitor without the hint, from any reader", async () => {
    renderPage();
    await settle();

    expect(fetchUserInfo).not.toHaveBeenCalled();
  });

  it("ask /me once for a browser carrying the hint and show its user", async () => {
    setHint();

    const { result } = renderPage();

    await waitFor(() =>
      expect(result.current.userId).toBe(SIGNED_IN_USER.user_id),
    );
    expect(fetchUserInfo).toHaveBeenCalledTimes(1);
  });

  it("re-validate a user cached before the API issued the hint", async () => {
    renderPage({ cachedUser: SIGNED_IN_USER });

    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalledTimes(1));
  });

  it("re-validate a cached user the persister restores after mount", async () => {
    const seeded = new QueryClient();
    seeded.setQueryData(CURRENT_USER_QUERY_KEY, SIGNED_IN_USER);
    const persisted: PersistedClient = {
      timestamp: Date.now(),
      buster: "",
      clientState: dehydrate(seeded),
    };
    const persister: Persister = {
      persistClient: async () => undefined,
      restoreClient: () =>
        new Promise((resolve) => setTimeout(() => resolve(persisted), 10)),
      removeClient: async () => undefined,
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <PersistQueryClientProvider
        client={new QueryClient()}
        persistOptions={{ persister }}
      >
        <SessionHintGateProvider value>{children}</SessionHintGateProvider>
      </PersistQueryClientProvider>
    );

    renderHook(useMarketingPage, { wrapper });

    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalledTimes(1));
  });

  it("treat a 401 behind a stale hint as signed out, log nothing, and stop asking", async () => {
    setHint();
    // The API's 401 response expires the hint cookie (auth middleware); this stands in for it.
    fetchUserInfo.mockImplementation(async () => {
      clearHint();
      throw new ApiError("expired", 401);
    });

    const { result, rerender } = renderPage();
    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalledTimes(1));
    await settle();
    rerender();
    await settle();

    expect(fetchUserInfo).toHaveBeenCalledTimes(1);
    expect(result.current.userId).toBe("");
    expect(console.error).not.toHaveBeenCalledWith(
      "Error fetching user info:",
      expect.anything(),
    );
  });

  it("keep a cached user through a transient /me failure, and ask again later", async () => {
    fetchUserInfo.mockRejectedValueOnce(new ApiError("down", 503));

    const { result, queryClient } = renderPage({ cachedUser: SIGNED_IN_USER });
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    await settle();

    expect(result.current.userId).toBe(SIGNED_IN_USER.user_id);
    await queryClient.refetchQueries({ queryKey: CURRENT_USER_QUERY_KEY });
    expect(fetchUserInfo).toHaveBeenCalledTimes(2);
  });

  it("still log a real /me failure for a signed-in user", async () => {
    setHint();
    fetchUserInfo.mockRejectedValue(new ApiError("down", 503));

    renderPage();

    await waitFor(() =>
      expect(console.error).toHaveBeenCalledWith(
        "Error fetching user info:",
        expect.any(ApiError),
      ),
    );
  });
});

describe("app pages", () => {
  it("ask /me without the hint", async () => {
    renderPage({ gated: false });

    await waitFor(() => expect(fetchUserInfo).toHaveBeenCalledTimes(1));
  });

  it("sign out again after a later session ends, not only the first", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("expired", 401));
    const { result, queryClient } = renderPage({
      gated: false,
      cachedUser: SIGNED_IN_USER,
    });
    await waitFor(() => expect(result.current.userId).toBe(""));

    fetchUserInfo.mockResolvedValue(SIGNED_IN_USER);
    await queryClient.refetchQueries({ queryKey: CURRENT_USER_QUERY_KEY });
    await waitFor(() =>
      expect(result.current.userId).toBe(SIGNED_IN_USER.user_id),
    );

    fetchUserInfo.mockRejectedValue(new ApiError("expired", 401));
    await queryClient.refetchQueries({ queryKey: CURRENT_USER_QUERY_KEY });
    await waitFor(() => expect(result.current.userId).toBe(""));
  });
});
