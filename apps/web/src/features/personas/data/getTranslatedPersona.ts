import { getLocale } from "next-intl/server";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { getAllPersonas, getPersona, type PersonaData } from "./personasData";

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

async function loadPersonaTranslations(
  localeOverride?: string,
): Promise<Record<string, TranslationOverrides>> {
  const locale = localeOverride ?? (await getLocale());
  return loadFeatureTranslations<Record<string, TranslationOverrides>>(
    locale,
    (l) => import(`../i18n/${l}.json`),
  );
}

export async function getTranslatedPersona(
  slug: string,
  locale?: string,
): Promise<PersonaData | undefined> {
  const base = getPersona(slug);
  if (!base) return undefined;
  const translations = await loadPersonaTranslations(locale);
  const t = translations[slug];
  if (!t) return base;
  return { ...base, ...t };
}

export async function getAllTranslatedPersonas(
  locale?: string,
): Promise<PersonaData[]> {
  const translations = await loadPersonaTranslations(locale);
  return getAllPersonas().map((persona) => {
    const t = translations[persona.slug];
    return t ? { ...persona, ...t } : persona;
  });
}
