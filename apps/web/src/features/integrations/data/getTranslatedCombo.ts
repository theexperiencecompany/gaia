import { getLocale } from "next-intl/server";
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

export async function getTranslatedCombo(
  slug: string,
): Promise<IntegrationCombo | undefined> {
  const base = getCombo(slug);
  if (!base) return undefined;
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getTranslatedCombos(): Promise<IntegrationCombo[]> {
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  return getAllCombos().map((combo) => {
    const t = translations[combo.slug];
    return t ? { ...combo, ...t } : combo;
  });
}
