// @vitest-environment jsdom
import { ApiError } from "@shared/api";
import type { ReferralMeResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { referralsApi } from "../api/referralsApi";
import { useHoverCardInvite, useReferralMe } from "./useReferrals";

vi.mock("../api/referralsApi", () => ({
  referralsApi: { getMe: vi.fn() },
}));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ email: "me@example.com" }),
}));

const getMe = vi.mocked(referralsApi.getMe);

function refusedWith(code: string): ApiError {
  return new ApiError("refused", 403, {
    envelope: { message: "refused", code },
  });
}

function freshClient() {
  const client = new QueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useReferralMe", () => {
  it("reports the program switched off, so every surface can hide", async () => {
    getMe.mockImplementation(() =>
      Promise.reject(refusedWith("REFERRALS_DISABLED")),
    );

    const { result } = renderHook(() => useReferralMe(), {
      wrapper: freshClient(),
    });

    await vi.waitFor(() => expect(result.current.status).toBe("disabled"));
  });

  it("asks a caller without a subscription to subscribe first", async () => {
    getMe.mockImplementation(() =>
      Promise.reject(refusedWith("REFERRAL_SUBSCRIPTION_REQUIRED")),
    );

    const { result } = renderHook(() => useReferralMe(), {
      wrapper: freshClient(),
    });

    await vi.waitFor(() =>
      expect(result.current.status).toBe("subscribe_first"),
    );
  });

  it("offers no hover-card invite while the program is off", async () => {
    getMe.mockImplementation(() =>
      Promise.reject(refusedWith("REFERRALS_DISABLED")),
    );

    const { result } = renderHook(
      () => ({
        me: useReferralMe(),
        invite: useHoverCardInvite("friend@example.com"),
      }),
      { wrapper: freshClient() },
    );

    await vi.waitFor(() => expect(result.current.me.status).toBe("disabled"));
    expect(result.current.invite).toBeUndefined();
  });

  it("offers the hover-card invite once the caller has a link", async () => {
    getMe.mockResolvedValue({ code: "aryan-k7f2" } as ReferralMeResponse);

    const { result } = renderHook(
      () => useHoverCardInvite("friend@example.com"),
      { wrapper: freshClient() },
    );

    await vi.waitFor(() => expect(result.current).toBeDefined());
  });
});
