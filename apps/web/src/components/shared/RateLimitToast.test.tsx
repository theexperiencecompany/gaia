// @vitest-environment jsdom

/** Regression: a Pro user hitting the daily wall saw "Rate Limit Exceeded: You've used today's AI usage allowance." with no word on when it comes back. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { handleRateLimitError } from "@/utils/interceptorUtils";

const toastError = vi.fn();

vi.mock("@/lib/toast", () => ({
  toast: { error: (message: string) => toastError(message) },
}));

const THREE_HOURS_MS = 3 * 60 * 60 * 1000;

describe("handleRateLimitError on the daily cost wall", () => {
  beforeEach(() => {
    toastError.mockClear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-28T21:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("tells a Pro user when chat comes back", () => {
    handleRateLimitError({
      code: "rate_limit_exceeded",
      message: "You've used today's AI usage allowance.",
      feature: "chat_messages",
      current_plan: "pro",
      reset_time: new Date(Date.now() + THREE_HOURS_MS).toISOString(),
    });

    expect(toastError).toHaveBeenCalledWith(
      "Usage limit reached: You've used today's AI usage allowance. Resets in 3 hours.",
    );
  });
});
