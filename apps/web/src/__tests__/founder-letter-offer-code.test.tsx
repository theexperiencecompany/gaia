// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const getDiscountCodes = vi.fn();
const track = vi.fn();

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: { getDiscountCodes: () => getDiscountCodes() },
}));

vi.mock("@/lib/analytics", () => ({
  track: (...args: unknown[]) => track(...args),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ name: "Ada Lovelace" }),
}));

import { useFounderLetter } from "@/features/chat/hooks/useFounderLetter";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  window.matchMedia =
    window.matchMedia ||
    ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
  window.localStorage.clear();
  getDiscountCodes.mockReset();
  track.mockReset();
});

describe("founder letter offer code", () => {
  it("offers the code the server is configured with", async () => {
    getDiscountCodes.mockResolvedValue({ founder_letter: "THANKYOU40" });

    const { result } = renderHook(() => useFounderLetter(false), { wrapper });

    await waitFor(() =>
      expect(result.current.liveOfferCode).toBe("THANKYOU40"),
    );
    expect(track).toHaveBeenCalledWith("founder_letter:shown", {
      discount_code: "THANKYOU40",
    });
  });

  it("carries no offer when the server has no code configured", async () => {
    getDiscountCodes.mockResolvedValue({ founder_letter: null });

    const { result } = renderHook(() => useFounderLetter(false), { wrapper });

    await waitFor(() =>
      expect(track).toHaveBeenCalledWith("founder_letter:shown", {
        discount_code: undefined,
      }),
    );
    expect(result.current.liveOfferCode).toBeNull();
  });

  it("withdraws a configured code once the offer has expired", async () => {
    vi.setSystemTime(new Date("2026-11-13T00:00:00Z"));
    getDiscountCodes.mockResolvedValue({ founder_letter: "THANKYOU40" });

    const { result } = renderHook(() => useFounderLetter(false), { wrapper });

    await waitFor(() => expect(track).toHaveBeenCalled());
    expect(result.current.liveOfferCode).toBeNull();
  });

  it("counts the letter as shown even when it is dismissed before the code arrives", async () => {
    const codes = Promise.withResolvers<{ founder_letter: string }>();
    getDiscountCodes.mockReturnValue(codes.promise);

    const { result } = renderHook(() => useFounderLetter(false), { wrapper });
    act(() => result.current.dismissLetter());
    await act(async () => codes.resolve({ founder_letter: "THANKYOU40" }));

    await waitFor(() =>
      expect(track).toHaveBeenCalledWith("founder_letter:shown", {
        discount_code: "THANKYOU40",
      }),
    );
  });
});
