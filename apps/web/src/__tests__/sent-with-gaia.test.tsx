// @vitest-environment jsdom
/**
 * Saving "Sent with GAIA" merges into the onboarding cached when the save
 * lands, so a preference another settings row saved meanwhile is not reverted.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

const updateOnboardingPreferences = vi.fn();

vi.mock("@/features/auth/api/authApi", () => ({
  authApi: {
    fetchUserInfo: () =>
      new Promise(() => {
        // Seeded below; never fetched.
      }),
    updateOnboardingPreferences: (...args: unknown[]) =>
      updateOnboardingPreferences(...args),
  },
}));

vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));

import type { UserInfo } from "@/features/auth/api/authApi";
import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { useSentWithGaia } from "@/features/referrals/hooks/useSentWithGaia";

function userWith(profession: string): UserInfo {
  return {
    user_id: "65f0c0ffee00000000000a01",
    auth_provider: "workos",
    message: "ok",
    email: "aryan@example.com",
    onboarding: {
      completed: true,
      completed_at: null,
      first_message_conversation_id: null,
      phase: null,
      preferences: { profession, sent_with_gaia: false },
    },
  };
}

describe("useSentWithGaia", () => {
  it("keeps a preference saved while its own save was in flight", async () => {
    const client = new QueryClient();
    client.setQueryData(CURRENT_USER_QUERY_KEY, userWith("founder"));
    let land: (value: { success: boolean }) => void = () => undefined;
    updateOnboardingPreferences.mockReturnValue(
      new Promise((resolve) => {
        land = resolve;
      }),
    );
    const { result } = renderHook(() => useSentWithGaia(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    let saving: Promise<void> = Promise.resolve();
    act(() => {
      saving = result.current.setEnabled(true);
    });
    act(() => {
      client.setQueryData(CURRENT_USER_QUERY_KEY, userWith("designer"));
    });
    await act(async () => {
      land({ success: true });
      await saving;
    });

    expect(
      client.getQueryData<UserInfo>(CURRENT_USER_QUERY_KEY)?.onboarding
        ?.preferences,
    ).toEqual({ profession: "designer", sent_with_gaia: true });
    expect(result.current.isEnabled).toBe(true);
  });
});
