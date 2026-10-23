/** A localized page keeps its locale only when linking into a translated family; English-only pages stay unprefixed. */
import { describe, expect, it } from "vitest";

import { isTranslatedPath } from "@/i18n/translatedRoutes";

describe("isTranslatedPath", () => {
  it("is true for translated hubs and their detail pages", () => {
    for (const path of [
      "/compare",
      "/compare/notion",
      "/alternative-to/sunsama",
      "/automate/slack-notion",
      "/for/founders",
      "/learn/ical",
    ]) {
      expect(isTranslatedPath(path), path).toBe(true);
    }
  });

  it("is false for English-only pages and lookalike prefixes", () => {
    for (const path of [
      "/",
      "/pricing",
      "/marketplace/gmail",
      "/use-cases",
      "/learning",
      "/compare-plans",
    ]) {
      expect(isTranslatedPath(path), path).toBe(false);
    }
  });
});
