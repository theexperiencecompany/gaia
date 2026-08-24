import { describe, expect, it, vi } from "vitest";
import { verifyPaymentWithRetry } from "@/features/pricing/utils/verifyPaymentWithRetry";

const completed = {
  payment_completed: true,
  subscription_id: "sub_1",
  message: "Payment completed",
};
const pending = {
  payment_completed: false,
  message: "No active subscription found",
};

describe("verifyPaymentWithRetry", () => {
  it("returns immediately when the first verify succeeds", async () => {
    const verify = vi.fn().mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, { baseDelayMs: 0 });

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(1);
  });

  it("retries not-completed results and succeeds once the webhook lands", async () => {
    const verify = vi
      .fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(pending)
      .mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, { baseDelayMs: 0 });

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(3);
  });

  it("retries through transient network errors", async () => {
    const verify = vi
      .fn()
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue(completed);

    const result = await verifyPaymentWithRetry(verify, { baseDelayMs: 0 });

    expect(result.payment_completed).toBe(true);
    expect(verify).toHaveBeenCalledTimes(2);
  });

  it("throws the last error after exhausting attempts", async () => {
    const verify = vi.fn().mockRejectedValue(new Error("Network Error"));

    await expect(
      verifyPaymentWithRetry(verify, { attempts: 3, baseDelayMs: 0 }),
    ).rejects.toThrow("Network Error");
    expect(verify).toHaveBeenCalledTimes(3);
  });

  it("returns the last not-completed result after exhausting attempts", async () => {
    const verify = vi.fn().mockResolvedValue(pending);

    const result = await verifyPaymentWithRetry(verify, {
      attempts: 2,
      baseDelayMs: 0,
    });

    expect(result.payment_completed).toBe(false);
    expect(verify).toHaveBeenCalledTimes(2);
  });

  it("a late error after a not-completed result still surfaces the error", async () => {
    const verify = vi
      .fn()
      .mockResolvedValueOnce(pending)
      .mockRejectedValue(new Error("boom"));

    await expect(
      verifyPaymentWithRetry(verify, { attempts: 2, baseDelayMs: 0 }),
    ).rejects.toThrow("boom");
  });
});
