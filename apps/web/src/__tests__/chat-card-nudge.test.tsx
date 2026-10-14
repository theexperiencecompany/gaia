// @vitest-environment jsdom
/**
 * The in-chat share card asks the server once per finished turn, because a
 * yes spends the user's weekly referral nudge; dismissing hides it at once
 * and must never re-ask, or the next answer would spend another week.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const claimChatCard = vi.fn();
const dismissChatCard = vi.fn();

vi.mock("@/features/referrals/api/referralsApi", () => ({
  referralsApi: {
    claimChatCard: () => claimChatCard(),
    dismissChatCard: () => dismissChatCard(),
  },
}));

import { useChatCardNudge } from "@/features/referrals/hooks/useChatCardNudge";

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useChatCardNudge", () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient();
    claimChatCard.mockResolvedValue({ show: true });
    dismissChatCard.mockResolvedValue({ paused: false });
  });

  it("shows the card when the server grants this week's nudge", async () => {
    const { result } = renderHook(() => useChatCardNudge("turn-1", true), {
      wrapper: wrapperFor(client),
    });

    await waitFor(() => expect(result.current.show).toBe(true));
    expect(claimChatCard).toHaveBeenCalledTimes(1);
  });

  it("never asks before the turn qualifies", () => {
    renderHook(() => useChatCardNudge("turn-1", false), {
      wrapper: wrapperFor(client),
    });

    expect(claimChatCard).not.toHaveBeenCalled();
  });

  it("hides the card on dismissal, records it, and never asks again", async () => {
    const { result } = renderHook(() => useChatCardNudge("turn-1", true), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.show).toBe(true));

    act(() => result.current.dismiss());

    await waitFor(() => expect(result.current.show).toBe(false));
    await waitFor(() => expect(dismissChatCard).toHaveBeenCalledTimes(1));
    expect(claimChatCard).toHaveBeenCalledTimes(1);
  });
});
