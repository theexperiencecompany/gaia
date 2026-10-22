import { afterEach, describe, expect, it, vi } from "vitest";
import { prerenderedMarketingParams } from "@/lib/selfhost";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("prerenderedMarketingParams", () => {
  it("prerenders every marketing page on hosted GAIA", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");

    await expect(
      prerenderedMarketingParams(async () => [{ slug: "a" }, { slug: "b" }]),
    ).resolves.toEqual([{ slug: "a" }, { slug: "b" }]);
  });

  it("prerenders no marketing page and loads nothing on a self-host build", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    const load = vi.fn(async () => [{ slug: "a" }]);

    await expect(prerenderedMarketingParams(load)).resolves.toEqual([]);
    expect(load).not.toHaveBeenCalled();
  });
});
