/** Marketing titles name the year through the token, so "Best X in <year>" rolls over on 1 January without an edit. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { CURRENT_YEAR_TOKEN, getFeatureEntry } from "@/lib/feature-data";

afterEach(() => {
  vi.useRealTimers();
});

describe("current-year token", () => {
  it("writes the running year into a dated title when the entry loads", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2031-03-01T00:00:00Z"));

    const entry = await getFeatureEntry<{ metaTitle: string }>(
      "alternatives",
      "omnifocus",
    );

    expect(entry?.metaTitle).toBe(
      "OmniFocus Alternative in 2031: AI Tasks on Windows",
    );
    expect(JSON.stringify(entry)).not.toContain(CURRENT_YEAR_TOKEN);
  });
});
