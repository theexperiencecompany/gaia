import { getLocale } from "next-intl/server";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import {
  type ComparisonData,
  getAllComparisons,
  getComparison,
} from "./comparisonsData";

type TranslationOverrides = Partial<
  Pick<
    ComparisonData,
    | "name"
    | "tagline"
    | "description"
    | "metaTitle"
    | "metaDescription"
    | "keywords"
    | "intro"
    | "rows"
    | "gaiaAdvantages"
    | "competitorAdvantages"
    | "verdict"
    | "faqs"
  >
>;

async function loadComparisonTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    (l) => import(`../i18n/${l}.json`),
  );
}

export async function getTranslatedComparison(
  slug: string,
  locale?: string,
): Promise<ComparisonData | undefined> {
  const base = getComparison(slug);
  if (!base) return undefined;
  const translations = await loadComparisonTranslations(locale);
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getTranslatedComparisons(
  locale?: string,
): Promise<ComparisonData[]> {
  const translations = await loadComparisonTranslations(locale);
  return getAllComparisons().map((comp) => {
    const t = translations[comp.slug];
    return t ? { ...comp, ...t } : comp;
  });
}
