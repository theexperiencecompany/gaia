// @vitest-environment jsdom
//
// Regression coverage for the "paying user sees paid-only UI on reload" bug:
// useIsPaid() must expose a signal that is true whenever the plan status is
// genuinely not yet known — including while the subscription-status query is
// disabled (persisted user store not yet rehydrated with a real userId) or
// still pending — and no consumer may treat that "unknown" state as "free".
//
// These tests exercise the REAL useIsPaid / useUserSubscriptionStatus /
// useIsSubscriptionStatusUnknown hooks (nothing is mocked away except the
// network call itself and the user store), because the bug was in how those
// hooks composed TanStack Query's disabled-query semantics with user
// hydration — mocking useIsPaid itself (as the other paywall tests do, to
// isolate their consumer under test) would hide exactly the code under test
// here.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSubscriptionStatus = vi.fn();

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    getSubscriptionStatus: (...args: unknown[]) =>
      getSubscriptionStatus(...args),
  },
}));

import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useUserStore } from "@/stores/userStore";

function withProviders(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function Probe() {
  const { isPaid, isUnknown } = useIsPaid();
  return (
    <div>
      <span data-testid="isPaid">{String(isPaid)}</span>
      <span data-testid="isUnknown">{String(isUnknown)}</span>
    </div>
  );
}

describe("useIsPaid — plan status unknown vs. known-free", () => {
  beforeEach(() => {
    useUserStore.getState().clearUser();
    getSubscriptionStatus.mockReset();
  });

  it("reports isUnknown === true (never a bare 'not paid') before the user store has rehydrated with a real userId", () => {
    // Simulates the exact pre-hydration window from the bug report: the
    // persisted user store hasn't rehydrated yet, so userId is still "" and
    // the subscription-status query is disabled — it has never fetched and
    // never will until userId appears. TanStack Query v5 reports
    // isLoading === false for a disabled query even though it has no data,
    // which is the trap the old `useIsPaid` contract fell into.
    withProviders(<Probe />);

    expect(screen.getByTestId("isPaid").textContent).toBe("false");
    // The critical assertion: a consumer relying on `isUnknown` must be able
    // to tell "hasn't answered yet" apart from "answered: free". Before the
    // fix this hook exposed `isLoading` here, which TanStack reports as
    // `false` for a disabled query — so a consumer gating on `isLoading ||
    // isPaid` would incorrectly treat this exact state as "known free" and
    // render the free-tier UI / paywall for a user who might be Pro.
    expect(screen.getByTestId("isUnknown").textContent).toBe("true");
    // The query must never have fired — proves this is genuinely the
    // disabled-query window, not a fast real fetch.
    expect(getSubscriptionStatus).not.toHaveBeenCalled();
  });

  it("reports isUnknown === true while the query is enabled but still in flight (data === undefined)", async () => {
    useUserStore.getState().setUser({
      userId: "user_1",
      profilePicture: "",
      name: "Test",
      email: "test@example.com",
    });
    // Never resolves within the test — pins the "in flight" state.
    getSubscriptionStatus.mockReturnValue(
      new Promise(() => {
        // Intentionally never settles.
      }),
    );

    withProviders(<Probe />);

    expect((await screen.findByTestId("isUnknown")).textContent).toBe("true");
    expect(screen.getByTestId("isPaid").textContent).toBe("false");
  });

  it("reports isUnknown === false and isPaid === true once the server actually answers 'pro'", async () => {
    useUserStore.getState().setUser({
      userId: "user_1",
      profilePicture: "",
      name: "Test",
      email: "test@example.com",
    });
    getSubscriptionStatus.mockResolvedValue({
      user_id: "user_1",
      is_subscribed: true,
      can_upgrade: false,
      can_downgrade: true,
      plan_type: "pro",
    });

    withProviders(<Probe />);

    await waitFor(() => {
      expect(screen.getByTestId("isPaid").textContent).toBe("true");
    });
    expect(screen.getByTestId("isUnknown").textContent).toBe("false");
  });

  it("reports isUnknown === false and isPaid === false once the server actually answers 'free'", async () => {
    useUserStore.getState().setUser({
      userId: "user_1",
      profilePicture: "",
      name: "Test",
      email: "test@example.com",
    });
    getSubscriptionStatus.mockResolvedValue({
      user_id: "user_1",
      is_subscribed: false,
      can_upgrade: true,
      can_downgrade: false,
      plan_type: "free",
    });

    withProviders(<Probe />);

    await waitFor(() => {
      expect(screen.getByTestId("isUnknown").textContent).toBe("false");
    });
    expect(screen.getByTestId("isPaid").textContent).toBe("false");
  });
});
