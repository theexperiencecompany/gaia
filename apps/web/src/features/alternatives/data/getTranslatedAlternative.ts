import { getLocale } from "next-intl/server";
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

export async function getTranslatedAlternative(
  slug: string,
): Promise<AlternativeData | undefined> {
  const base = getAlternative(slug);
  if (!base) return undefined;
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getTranslatedAlternatives(): Promise<AlternativeData[]> {
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  return getAllAlternatives().map((alt) => {
    const t = translations[alt.slug];
    return t ? { ...alt, ...t } : alt;
  });
}
