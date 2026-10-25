import { afterEach, describe, expect, it, vi } from "vitest";
import { locales } from "@/i18n/config";
import { prerenderedLocales } from "@/i18n/prerenderedLocales";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("prerenderedLocales", () => {
  it("prerenders every locale on hosted GAIA", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");

    expect(prerenderedLocales()).toEqual(locales);
  });

  it("prerenders only the default locale on a self-host build", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");

    expect(prerenderedLocales()).toEqual(["en"]);
  });
});
