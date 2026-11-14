// @vitest-environment jsdom
/** A failed idle prefetch of the mention editor chunk is logged, not left as an unhandled rejection. */
import { afterEach, describe, expect, it, vi } from "vitest";

const { idleCallbacks } = vi.hoisted(() => ({
  idleCallbacks: [] as Array<() => unknown>,
}));

vi.mock("@/lib/idle", () => ({
  whenIdle: (callback: () => unknown) => {
    idleCallbacks.push(callback);
  },
}));

vi.mock("@/features/integrations/components/MentionEditor", () => {
  throw new Error("chunk load failed");
});

describe("LazyMentionEditor idle prefetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("logs a failed chunk fetch instead of rejecting", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    await import("@/features/integrations/components/LazyMentionEditor");
    expect(idleCallbacks).toHaveLength(1);

    await expect(idleCallbacks[0]()).resolves.toBeUndefined();
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("mention editor"),
      expect.any(Error),
    );
  });
});
