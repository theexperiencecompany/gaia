/**
 * Salesforce is retiring Quip: no new accounts for non-customers since
 * 2026-02-17, no renewals after 2027-03-01. The Quip comparison must say so
 * in every locale wherever it recommends Quip.
 */
import { describe, expect, it } from "vitest";

import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";
import { locales } from "@/i18n/config";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { getFeatureEntry } from "@/lib/feature-data";

const mentionsRetirementDates = (text: string): boolean =>
  text.includes("2026") && text.includes("2027");

async function quipFor(locale: string): Promise<ComparisonData> {
  const base = await getFeatureEntry<ComparisonData>("comparisons", "quip");
  if (!base) throw new Error("comparisons/quip.json is missing");
  const overlay = await loadFeatureTranslations<
    Record<string, Partial<ComparisonData>>
  >(locale, "comparisons");
  return { ...base, ...overlay.quip };
}

describe.each(locales)("Quip comparison (%s)", (locale) => {
  it("states the retirement dates in the verdict", async () => {
    const { verdict } = await quipFor(locale);
    expect(mentionsRetirementDates(verdict)).toBe(true);
  });

  it("states the retirement dates in the intro", async () => {
    const { intro } = await quipFor(locale);
    expect(mentionsRetirementDates(intro)).toBe(true);
  });

  it("has an FAQ answer with the retirement dates", async () => {
    const { faqs } = await quipFor(locale);
    expect(faqs.some(({ answer }) => mentionsRetirementDates(answer))).toBe(
      true,
    );
  });
});
