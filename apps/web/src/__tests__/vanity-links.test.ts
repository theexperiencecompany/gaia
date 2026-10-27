import { describe, expect, it } from "vitest";

import { appConfig, footerSections } from "@/config/appConfig";

import {
  VANITY_REDIRECT_PAIRS,
  vanityTarget,
} from "../../vanity-redirects.mjs";

const VANITY_PATHS = new Set(VANITY_REDIRECT_PAIRS.map(([source]) => source));

const navAndFooterHrefs = [
  ...Object.values(appConfig.links).flat(),
  ...footerSections.flatMap((section) => section.links),
].map((link) => link.href);

describe("vanity redirects", () => {
  it("are never linked from the nav or footer, which link the destination instead", () => {
    expect(navAndFooterHrefs.filter((href) => VANITY_PATHS.has(href))).toEqual(
      [],
    );
  });

  it("resolve a vanity path to its destination", () => {
    expect(vanityTarget("/status")).toBe("https://status.heygaia.io");
  });

  it("refuse a path that is not a vanity redirect", () => {
    expect(() => vanityTarget("/pricing")).toThrow(/not a vanity/);
  });
});
