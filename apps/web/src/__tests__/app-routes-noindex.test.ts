import { describe, expect, it, vi } from "vitest";

vi.mock("@/layouts/MainAppShell", () => ({ default: () => null }));

describe("signed-in app routes", () => {
  it("tell crawlers not to index or follow anything under the (main) layout", async () => {
    const { metadata } = await import("@/app/[locale]/(main)/layout");
    expect(metadata?.robots).toEqual({ index: false, follow: false });
  });
});
