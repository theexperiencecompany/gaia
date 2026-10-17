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

  it("asks once per local week and rolls over at Monday on a page left open", async () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 12, 9) });
    claimWeeklyCard.mockResolvedValueOnce({ ...CARD, show: false });
    const { result } = renderHook(() => useWeeklyCard(), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(claimWeeklyCard).toHaveBeenCalledTimes(1));

    // Sunday 23:00, still the same week: no second claim.
    await act(async () => {
      await vi.advanceTimersByTimeAsync((6 * 24 + 14) * 60 * 60 * 1000);
    });
    expect(claimWeeklyCard).toHaveBeenCalledTimes(1);

    // Past Monday 00:00 with no re-render: the new week claims and shows its card.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60 * 60 * 1000);
    });
    await vi.waitFor(() => expect(result.current.card).toEqual(CARD));
    expect(claimWeeklyCard).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
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
