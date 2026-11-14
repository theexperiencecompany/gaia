import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { isValidSection } from "@/features/settings/config/sectionKeys";

import {
  DEFAULT_SETTINGS_SECTION,
  settingsRedirects,
} from "../../settings-redirects.mjs";

const SETTINGS_DIR = path.join(
  process.cwd(),
  "src/app/[locale]/(main)/settings",
);

describe("settings redirects", () => {
  it("leave /settings without a page, whose redirect() would stream a meta-refresh reload", () => {
    expect(existsSync(path.join(SETTINGS_DIR, "page.tsx"))).toBe(false);
  });

  it("forward bare /settings to a section that exists", () => {
    const bare = settingsRedirects().find((rule) => rule.has === undefined);
    expect(bare?.destination).toBe(`/settings/${DEFAULT_SETTINGS_SECTION}`);
    expect(isValidSection(DEFAULT_SETTINGS_SECTION)).toBe(true);
  });

  it("match a legacy ?section= link before the bare /settings rule swallows it", () => {
    const [first, second] = settingsRedirects();
    expect(first.has?.[0].key).toBe("section");
    expect(first.destination).toBe("/settings/:section");
    expect(second.has).toBeUndefined();
  });
});
