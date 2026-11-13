// @vitest-environment jsdom
//
// Regression coverage for the "paying user sees paid-only UI on reload" bug:
// useIsPaid() must expose a signal that is true whenever the plan status is
// genuinely not yet known — including while the subscription-status query is
// disabled (persisted query cache not yet restored with a real userId) or
// still pending — and no consumer may treat that "unknown" state as "free".
//
// These tests exercise the REAL useIsPaid / useUserSubscriptionStatus /
// useIsSubscriptionStatusUnknown hooks (nothing is mocked away except the
// network call itself), because the bug was in how those
// hooks composed TanStack Query's disabled-query semantics with user
// cache restoration — mocking useIsPaid itself (as the other paywall tests do, to
// isolate their consumer under test) would hide exactly the code under test
// here.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSubscriptionStatus = vi.fn();

// The user is seeded into the cache directly; nothing here should hit the
// network for it, and an unseeded test must stay in the "never answered" state.
vi.mock("@/features/auth/api/authApi", () => ({
  authApi: {
    fetchUserInfo: () =>
      new Promise(() => {
        // Intentionally never settles.
      }),
  },
}));

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    getSubscriptionStatus: (...args: unknown[]) =>
      getSubscriptionStatus(...args),
  },
}));

import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";

let queryClient: QueryClient;

/** Seeds the `["current-user"]` cache the way a restored/fetched user would. */
function seedCurrentUser(userId: string) {
  queryClient.setQueryData(CURRENT_USER_QUERY_KEY, {
    user_id: userId,
    name: "Test",
    email: "test@example.com",
    picture: "",
  });
}

function withProviders(ui: React.ReactNode) {
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
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    getSubscriptionStatus.mockReset();
  });

  it("reports isUnknown === true (never a bare 'not paid') before the current-user cache has a real userId", () => {
    // Simulates pre-hydration: userId is "" so the subscription-status
    // query is disabled and never fetches. TanStack v5 reports
    // isLoading === false for a disabled query — the trap the old `useIsPaid` contract fell into.
    withProviders(<Probe />);

    expect(screen.getByTestId("isPaid").textContent).toBe("false");
    // A consumer relying on `isUnknown` must tell "hasn't answered" apart
    // from "answered: free" — the old hook exposed `isLoading` here (false
    // for a disabled query), so `isLoading || isPaid` wrongly read "known free".
    expect(screen.getByTestId("isUnknown").textContent).toBe("true");
    // The query must never have fired — proves this is genuinely the
    // disabled-query window, not a fast real fetch.
    expect(getSubscriptionStatus).not.toHaveBeenCalled();
  });

  it("reports isUnknown === true while the query is enabled but still in flight (data === undefined)", async () => {
    seedCurrentUser("user_1");
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
    seedCurrentUser("user_1");
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
    seedCurrentUser("user_1");
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
