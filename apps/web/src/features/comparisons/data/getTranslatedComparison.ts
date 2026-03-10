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

export async function getTranslatedComparison(
  slug: string,
): Promise<ComparisonData | undefined> {
  const base = getComparison(slug);
  if (!base) return undefined;
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getTranslatedComparisons(): Promise<ComparisonData[]> {
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  return getAllComparisons().map((comp) => {
    const t = translations[comp.slug];
    return t ? { ...comp, ...t } : comp;
  });
}
