// @vitest-environment jsdom
/**
 * Where the onboarding guard sends a user the moment onboarding completes.
 *
 * Completion seeds GAIA's "Getting started" conversation server-side, so the
 * whole point of the flow is landing inside it. A guard that keeps sending
 * everyone to `/c` leaves that conversation sitting unread in the sidebar and
 * the user staring at an empty composer.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
const usePathname = vi.fn();
const useUser = vi.fn();
const readPendingCheckout = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (...args: unknown[]) => redirect(...args),
  RedirectType: { push: "push" },
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => usePathname(),
}));

vi.mock("@/features/auth/hooks/useUser", () => ({
  useUser: () => useUser(),
}));

vi.mock("@/features/pricing/lib/pendingCheckout", () => ({
  readPendingCheckout: () => readPendingCheckout(),
}));

import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";

const completedUser = (firstConversationId?: string) => ({
  email: "a@b.com",
  onboarding: {
    completed: true,
    ...(firstConversationId
      ? { first_message_conversation_id: firstConversationId }
      : {}),
  },
});

describe("useOnboardingGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readPendingCheckout.mockReturnValue(null);
    usePathname.mockReturnValue("/onboarding");
  });

  it("lands the user in the seeded conversation on completion", () => {
    useUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/c/conv-123", "push");
  });

  it("falls back to the chat home when no conversation was seeded", () => {
    useUser.mockReturnValue(completedUser());

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/c", "push");
  });

  it("still sends an unfinished user back to onboarding", () => {
    usePathname.mockReturnValue("/c");
    useUser.mockReturnValue({
      email: "a@b.com",
      onboarding: { completed: false },
    });

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/onboarding", "push");
  });

  it("does not redirect while a checkout is pending", () => {
    readPendingCheckout.mockReturnValue({ planId: "pro" });
    useUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });
});
