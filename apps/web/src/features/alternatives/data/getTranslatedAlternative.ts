import { getLocale } from "next-intl/server";
import { cache } from "react";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import {
  type AlternativeData,
  getAllAlternatives,
  getAlternative,
} from "./alternativesData";

type TranslationOverrides = Partial<
  Pick<
    AlternativeData,
    | "name"
    | "tagline"
    | "metaTitle"
    | "metaDescription"
    | "keywords"
    | "painPoints"
    | "whyPeopleLook"
    | "gaiaReplaces"
    | "gaiaAdvantages"
    | "migrationSteps"
    | "faqs"
    | "comparisonRows"
  >
>;

async function loadAlternativeTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    (l) => import(`../i18n/${l}.json`),
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedAlternative = cache(
  async (
    slug: string,
    locale?: string,
  ): Promise<AlternativeData | undefined> => {
    const base = getAlternative(slug);
    if (!base) return undefined;
    const translations = await loadAlternativeTranslations(locale);
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getTranslatedAlternatives(
  locale?: string,
): Promise<AlternativeData[]> {
  const translations = await loadAlternativeTranslations(locale);
  return getAllAlternatives().map((alt) => {
    const t = translations[alt.slug];
    return t ? { ...alt, ...t } : alt;
  });
}
