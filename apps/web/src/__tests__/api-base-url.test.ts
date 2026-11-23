import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("the API base URL", () => {
  it("refuses to load without NEXT_PUBLIC_API_BASE_URL instead of building relative links", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

    await expect(import("@/lib/api/client")).rejects.toThrow(
      "NEXT_PUBLIC_API_BASE_URL",
    );
  });
});
