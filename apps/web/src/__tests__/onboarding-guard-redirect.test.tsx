// @vitest-environment jsdom
/**
 * Where the onboarding guard sends a user the moment onboarding completes.
 *
 * Completion seeds GAIA's "Getting started" conversation server-side, so the
 * whole point of the flow is landing inside it. A guard that keeps sending
 * everyone to `/c` leaves that conversation sitting unread in the sidebar and
 * the user staring at an empty composer.
 */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
const usePathname = vi.fn();
const useCurrentUser = vi.fn();
const useEntitlement = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (...args: unknown[]) => redirect(...args),
  RedirectType: { push: "push", replace: "replace" },
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => usePathname(),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => useCurrentUser(),
}));

vi.mock("@/features/pricing/hooks/useEntitlement", () => ({
  useEntitlement: () => useEntitlement(),
}));

import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";
import {
  clearPendingCheckout,
  writePendingCheckout,
} from "@/features/pricing/lib/pendingCheckout";

const completedUser = (firstConversationId?: string) => ({
  email: "a@b.com",
  onboarding: {
    completed: true,
    ...(firstConversationId
      ? { getting_started_conversation_id: firstConversationId }
      : {}),
  },
});

describe("useOnboardingGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearPendingCheckout();
    useEntitlement.mockReturnValue("entitled");
    usePathname.mockReturnValue("/onboarding");
  });

  it("lands the user in the seeded conversation on completion", () => {
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/c/conv-123", "replace");
  });

  it("falls back to the chat home when no conversation was seeded", () => {
    useCurrentUser.mockReturnValue(completedUser());

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/c", "replace");
  });

  it("still sends an unfinished user back to onboarding", () => {
    usePathname.mockReturnValue("/c");
    useCurrentUser.mockReturnValue({
      email: "a@b.com",
      onboarding: { completed: false },
    });

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/onboarding", "replace");
  });

  it("does not redirect while a checkout is pending", () => {
    writePendingCheckout("pro");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });

  // Regression: a never-paid account on /c got a non-dismissable wall whose
  // only exit was Log out, instead of the wizard's paywall it left.
  it("sends a never-subscribed account from the app to the onboarding paywall", () => {
    usePathname.mockReturnValue("/c");
    useEntitlement.mockReturnValue("never_subscribed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).toHaveBeenCalledWith("/onboarding", "replace");
  });

  it("keeps a never-subscribed account on the onboarding paywall", () => {
    useEntitlement.mockReturnValue("never_subscribed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });

  it("leaves a lapsed account in the app, where the UpgradeModal stands", () => {
    usePathname.mockReturnValue("/c");
    useEntitlement.mockReturnValue("lapsed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });

  it("holds a finished user on onboarding until the plan is read", () => {
    useEntitlement.mockReturnValue("unknown");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });

  it("lets a pending checkout resume before unpaid routing", () => {
    writePendingCheckout("pro");
    usePathname.mockReturnValue("/c");
    useEntitlement.mockReturnValue("never_subscribed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));

    renderHook(() => useOnboardingGuard());

    expect(redirect).not.toHaveBeenCalled();
  });

  // Regression: a failed checkout resume cleared the pending plan without a
  // re-render, so the guard never re-ran and the user sat on the shell spinner.
  it("routes a never-subscribed account to the paywall once a resume fails", () => {
    writePendingCheckout("pro");
    usePathname.mockReturnValue("/c");
    useEntitlement.mockReturnValue("never_subscribed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));
    renderHook(() => useOnboardingGuard());
    expect(redirect).not.toHaveBeenCalled();

    act(() => clearPendingCheckout());

    expect(redirect).toHaveBeenCalledWith("/onboarding", "replace");
  });

  it("leaves a lapsed account under the UpgradeModal once a resume fails", () => {
    writePendingCheckout("pro");
    usePathname.mockReturnValue("/c");
    useEntitlement.mockReturnValue("lapsed");
    useCurrentUser.mockReturnValue(completedUser("conv-123"));
    renderHook(() => useOnboardingGuard());

    act(() => clearPendingCheckout());

    expect(redirect).not.toHaveBeenCalled();
  });
});
