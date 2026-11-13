import { afterEach, describe, expect, it, vi } from "vitest";
import { withTimeout } from "../../../../../libs/shared/ts/src/bots/utils/timeout";

afterEach(() => {
  vi.useRealTimers();
});

describe("withTimeout", () => {
  it("settles with the promise when it wins, leaving no timer behind", async () => {
    vi.useFakeTimers();

    await expect(
      withTimeout(Promise.resolve("ok"), 5_000, "slow"),
    ).resolves.toBe("ok");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects with the given reason once the deadline passes", async () => {
    vi.useFakeTimers();
    const pending = withTimeout(
      new Promise<never>(() => undefined),
      5_000,
      "slow",
    );
    const outcome = expect(pending).rejects.toThrow("slow");

    await vi.advanceTimersByTimeAsync(5_000);

    await outcome;
  });
});
