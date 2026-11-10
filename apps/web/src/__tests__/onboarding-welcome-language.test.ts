/**
 * The welcome thread is written in the user's language. The /onboarding route
 * is never localised (/de/onboarding redirects to it), so the app locale there
 * is always "en" and a German browser used to get an English welcome.
 */

import { describe, expect, it } from "vitest";

import { welcomeLanguage } from "@/features/onboarding/utils/welcomeLanguage";

describe("welcomeLanguage", () => {
  it("takes the first browser language the app is translated into", () => {
    expect(welcomeLanguage(["zh-CN", "de-DE", "en-US"], "en")).toBe("de-DE");
  });

  it("matches a regional browser tag to its translated language", () => {
    expect(welcomeLanguage(["pt-BR"], "en")).toBe("pt-BR");
    expect(welcomeLanguage(["ja"], "en")).toBe("ja");
  });

  it("falls back to the app locale when no browser language is translated", () => {
    expect(welcomeLanguage(["zh-CN", "ru"], "en")).toBe("en");
    expect(welcomeLanguage([], "fr")).toBe("fr");
  });
});
