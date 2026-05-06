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
    "alternatives",
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedAlternative = cache(
  async (
    slug: string,
    locale?: string,
  ): Promise<AlternativeData | undefined> => {
    const [base, translations] = await Promise.all([
      getAlternative(slug),
      loadAlternativeTranslations(locale),
    ]);
    if (!base) return undefined;
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getTranslatedAlternatives(
  locale?: string,
): Promise<AlternativeData[]> {
  const [all, translations] = await Promise.all([
    getAllAlternatives(),
    loadAlternativeTranslations(locale),
  ]);
  return all.map((alt) => {
    const t = translations[alt.slug];
    return t ? { ...alt, ...t } : alt;
  });
}
