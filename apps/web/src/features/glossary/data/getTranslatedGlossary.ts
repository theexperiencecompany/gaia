import { getLocale } from "next-intl/server";
import { cache } from "react";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import {
  type GlossaryTerm,
  getAllGlossaryTerms,
  getGlossaryTerm,
} from "./glossaryData";

type TranslationOverrides = Partial<
  Pick<
    GlossaryTerm,
    | "term"
    | "metaTitle"
    | "metaDescription"
    | "definition"
    | "extendedDescription"
    | "keywords"
    | "howGaiaUsesIt"
    | "faqs"
  >
>;

async function loadGlossaryTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    (l) => import(`../i18n/${l}.json`),
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedGlossaryTerm = cache(
  async (slug: string, locale?: string): Promise<GlossaryTerm | undefined> => {
    const base = getGlossaryTerm(slug);
    if (!base) return undefined;
    const translations = await loadGlossaryTranslations(locale);
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getAllTranslatedGlossaryTerms(
  locale?: string,
): Promise<GlossaryTerm[]> {
  const translations = await loadGlossaryTranslations(locale);
  return getAllGlossaryTerms().map((term) => {
    const t = translations[term.slug];
    return t ? { ...term, ...t } : term;
  });
}
