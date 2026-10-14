// @vitest-environment jsdom
/**
 * The Monday recap card is asked for once a session, because a shown card
 * spends the user's weekly referral nudge; dismissing hides it at once and
 * must never re-ask, or the next answer would spend another week.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const claimWeeklyCard = vi.fn();
const dismissWeeklyCard = vi.fn();
let paid = { isPaid: true, isUnknown: false };

vi.mock("@/features/referrals/api/referralsApi", () => ({
  referralsApi: {
    claimWeeklyCard: () => claimWeeklyCard(),
    dismissWeeklyCard: () => dismissWeeklyCard(),
  },
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => paid,
}));

import { useWeeklyCard } from "@/features/referrals/hooks/useWeeklyCard";

const CARD = {
  show: true,
  code: "aryan-k7f2",
  stats: { minutes_saved: 95, actions: 12, workflow_runs: 3 },
};

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useWeeklyCard", () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient();
    paid = { isPaid: true, isUnknown: false };
    claimWeeklyCard.mockResolvedValue(CARD);
    dismissWeeklyCard.mockResolvedValue({ paused: false });
  });

  it("shows the week's card to a subscriber the server grants it to", async () => {
    const { result } = renderHook(() => useWeeklyCard(), {
      wrapper: wrapperFor(client),
    });

    await waitFor(() => expect(result.current.card).toEqual(CARD));
  });

  it("never asks for someone who is not subscribed", () => {
    paid = { isPaid: false, isUnknown: false };
    renderHook(() => useWeeklyCard(), { wrapper: wrapperFor(client) });

    expect(claimWeeklyCard).not.toHaveBeenCalled();
  });

  it("hides the card on dismissal, records it, and never asks again", async () => {
    const { result } = renderHook(() => useWeeklyCard(), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.card).toBeDefined());

    act(() => result.current.dismiss());

    await waitFor(() => expect(result.current.card).toBeUndefined());
    await waitFor(() => expect(dismissWeeklyCard).toHaveBeenCalledTimes(1));
    expect(claimWeeklyCard).toHaveBeenCalledTimes(1);
  });
});
