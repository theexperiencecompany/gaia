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
    "glossary",
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedGlossaryTerm = cache(
  async (slug: string, locale?: string): Promise<GlossaryTerm | undefined> => {
    const [base, translations] = await Promise.all([
      getGlossaryTerm(slug),
      loadGlossaryTranslations(locale),
    ]);
    if (!base) return undefined;
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getAllTranslatedGlossaryTerms(
  locale?: string,
): Promise<GlossaryTerm[]> {
  const [all, translations] = await Promise.all([
    getAllGlossaryTerms(),
    loadGlossaryTranslations(locale),
  ]);
  return all.map((term) => {
    const t = translations[term.slug];
    return t ? { ...term, ...t } : term;
  });
}
