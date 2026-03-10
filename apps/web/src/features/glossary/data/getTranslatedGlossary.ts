import { getLocale } from "next-intl/server";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { type GlossaryTerm, getGlossaryTerm } from "./glossaryData";

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

export async function getTranslatedGlossaryTerm(
  slug: string,
): Promise<GlossaryTerm | undefined> {
  const base = getGlossaryTerm(slug);
  if (!base) return undefined;
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

