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

async function loadComboTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    (l) => import(`../i18n/${l}.json`),
  );
}

export async function getTranslatedCombo(
  slug: string,
  locale?: string,
): Promise<IntegrationCombo | undefined> {
  const base = getCombo(slug);
  if (!base) return undefined;
  const translations = await loadComboTranslations(locale);
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getTranslatedCombos(
  locale?: string,
): Promise<IntegrationCombo[]> {
  const translations = await loadComboTranslations(locale);
  return getAllCombos().map((combo) => {
    const t = translations[combo.slug];
    return t ? { ...combo, ...t } : combo;
  });
}
