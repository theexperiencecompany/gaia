import { getLocale } from "next-intl/server";
import { cache } from "react";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { getAllCombos, getCombo, type IntegrationCombo } from "./combosData";

type TranslationOverrides = Partial<
  Pick<
    IntegrationCombo,
    | "tagline"
    | "metaTitle"
    | "metaDescription"
    | "keywords"
    | "intro"
    | "useCases"
    | "howItWorks"
    | "faqs"
  >
>;

async function loadComboTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    "integrations",
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedCombo = cache(
  async (
    slug: string,
    locale?: string,
  ): Promise<IntegrationCombo | undefined> => {
    const [base, translations] = await Promise.all([
      getCombo(slug),
      loadComboTranslations(locale),
    ]);
    if (!base) return undefined;
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getTranslatedCombos(
  locale?: string,
): Promise<IntegrationCombo[]> {
  const [all, translations] = await Promise.all([
    getAllCombos(),
    loadComboTranslations(locale),
  ]);
  return all.map((combo) => {
    const t = translations[combo.slug];
    return t ? { ...combo, ...t } : combo;
  });
}
