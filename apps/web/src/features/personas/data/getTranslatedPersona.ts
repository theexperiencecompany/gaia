import { getLocale } from "next-intl/server";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { getPersona, type PersonaData } from "./personasData";

type TranslationOverrides = Partial<
  Pick<
    PersonaData,
    | "title"
    | "role"
    | "metaTitle"
    | "metaDescription"
    | "keywords"
    | "intro"
    | "painPoints"
    | "howGaiaHelps"
    | "faqs"
  >
>;

export async function getTranslatedPersona(
  slug: string,
): Promise<PersonaData | undefined> {
  const base = getPersona(slug);
  if (!base) return undefined;
  const locale = await getLocale();
  const translations = await loadFeatureTranslations<
    Record<string, TranslationOverrides>
  >(locale, (l) => import(`../i18n/${l}.json`));
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

