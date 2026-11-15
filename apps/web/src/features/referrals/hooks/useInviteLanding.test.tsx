// @vitest-environment jsdom
import { ApiError } from "@shared/api";
import type { ReferralResolveResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import { referralsApi } from "../api/referralsApi";
import { useInviteLanding } from "./useInviteLanding";

vi.mock("../api/referralsApi", () => ({
  referralsApi: { resolve: vi.fn() },
}));
vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo: vi.fn() },
}));

const resolve = vi.mocked(referralsApi.resolve);
const fetchUserInfo = vi.mocked(authApi.fetchUserInfo);

function freshClient() {
  const client = new QueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  resolve.mockResolvedValue({ valid: true } as ReferralResolveResponse);
});

describe("useInviteLanding", () => {
  it("never resolves the code for a signed-in visitor, so no attribution cookie is set", async () => {
    fetchUserInfo.mockResolvedValue({
      user_id: "507f1f77bcf86cd799439011",
      email: "member@example.com",
    } as UserInfo);

    const { result } = renderHook(() => useInviteLanding("ABC123"), {
      wrapper: freshClient(),
    });

    await vi.waitFor(() => expect(result.current.isSignedIn).toBe(true));
    await new Promise((settle) => setTimeout(settle, 20));
    expect(resolve).not.toHaveBeenCalled();
    expect(result.current.invite).toBeUndefined();
  });

  it("resolves the code once the visitor is known to be signed out", async () => {
    fetchUserInfo.mockRejectedValue(new ApiError("unauthorized", 401));

    const { result } = renderHook(() => useInviteLanding("ABC123"), {
      wrapper: freshClient(),
    });

    await vi.waitFor(() => expect(result.current.invite).toBeDefined());
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(resolve.mock.calls[0][0]).toBe("ABC123");
    expect(result.current.isSignedIn).toBe(false);
  });

  it("holds the resolve until the sign-in check answers", async () => {
    fetchUserInfo.mockReturnValue(new Promise<UserInfo>(() => undefined));

    renderHook(() => useInviteLanding("ABC123"), { wrapper: freshClient() });

    await new Promise((settle) => setTimeout(settle, 20));
    expect(resolve).not.toHaveBeenCalled();
  });
});
