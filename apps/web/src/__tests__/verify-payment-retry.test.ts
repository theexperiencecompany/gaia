import { afterEach, describe, expect, it, vi } from "vitest";
import { CHECKOUT_CONFIRM_TOTAL_BUDGET_MS } from "@/features/pricing/constants";
import {
  retryDelays,
  verifyPaymentWithRetry,
} from "@/features/pricing/utils/verifyPaymentWithRetry";

const completed = {
  payment_completed: true,
  subscription_id: "sub_1",
  message: "Payment completed",
};
const pending = {
  payment_completed: false,
  message: "No active subscription found",
};

/** Two retries, no real waiting. */
const immediate = { delays: [0, 0] };

describe("verifyPaymentWithRetry", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns immediately when the first verify succeeds", async () => {
    const verify = vi.fn().mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, immediate);

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(1);
  });

  it("retries not-completed results and succeeds once the webhook lands", async () => {
    const verify = vi
      .fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(pending)
      .mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, immediate);

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(3);
  });

  it("retries through transient network errors", async () => {
    const verify = vi
      .fn()
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, immediate);

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(2);
  });

  it("throws the last error after exhausting attempts", async () => {
    const verify = vi.fn().mockRejectedValue(new Error("Network Error"));

    await expect(verifyPaymentWithRetry(verify, immediate)).rejects.toThrow(
      "Network Error",
    );
    expect(verify).toHaveBeenCalledTimes(3);
  });

  it("returns the last not-completed result after exhausting attempts", async () => {
    const verify = vi.fn().mockResolvedValue(pending);

    const result = await verifyPaymentWithRetry(verify, { delays: [0] });

    expect(result.payment_completed).toBe(false);
    expect(verify).toHaveBeenCalledTimes(2);
  });

  it("a late error after a not-completed result still surfaces the error", async () => {
    const verify = vi
      .fn()
      .mockResolvedValueOnce(pending)
      .mockRejectedValue(new Error("boom"));

    await expect(
      verifyPaymentWithRetry(verify, { delays: [0] }),
    ).rejects.toThrow("boom");
  });
});

/**
 * The result page and the in-app checkout wizard wait out the same
 * webhook-vs-redirect race, so they must wait the same length of time. They
 * did not: the wizard gave the webhook five minutes while this schedule ran
 * out after about 49 seconds, and a user who had genuinely paid was told
 * "Payment not completed" while the wizard would still have been confirming.
 */
describe("the retry schedule is the checkout wait budget", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("spends exactly the shared budget across its gaps", () => {
    const delays = retryDelays(CHECKOUT_CONFIRM_TOTAL_BUDGET_MS);

    expect(delays.reduce((total, delay) => total + delay, 0)).toBe(
      CHECKOUT_CONFIRM_TOTAL_BUDGET_MS,
    );
  });

  it("grows the gaps and stays under the endpoint's 20 calls a minute", () => {
    const delays = retryDelays(CHECKOUT_CONFIRM_TOTAL_BUDGET_MS);
    const callsInFirstMinute =
      delays.filter(
        (_delay, index) =>
          delays.slice(0, index + 1).reduce((a, b) => a + b, 0) < 60_000,
      ).length + 1;

    expect(delays[1]).toBeGreaterThan(delays[0]);
    expect(callsInFirstMinute).toBeLessThanOrEqual(20);
  });

  it("is still asking at four minutes, when the wizard still is", async () => {
    vi.useFakeTimers();
    const verify = vi.fn().mockResolvedValue(pending);

    const settled = verifyPaymentWithRetry(verify).catch(() => undefined);

    await vi.advanceTimersByTimeAsync(4 * 60_000);
    const callsAtFourMinutes = verify.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);

    expect(verify.mock.calls.length).toBeGreaterThan(callsAtFourMinutes);

    await vi.advanceTimersByTimeAsync(CHECKOUT_CONFIRM_TOTAL_BUDGET_MS);
    await settled;
  });
});
