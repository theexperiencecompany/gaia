import { getLocale } from "next-intl/server";
import { cache } from "react";
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
    "personas",
  );
}

/** Wrapped with React.cache() for per-request deduplication between generateMetadata and page component */
export const getTranslatedPersona = cache(
  async (slug: string, locale?: string): Promise<PersonaData | undefined> => {
    const [base, translations] = await Promise.all([
      getPersona(slug),
      loadPersonaTranslations(locale),
    ]);
    if (!base) return undefined;
    const t = translations[slug];
    if (!t) return base;
    return { ...base, ...t };
  },
);

export async function getAllTranslatedPersonas(
  locale?: string,
): Promise<PersonaData[]> {
  const [all, translations] = await Promise.all([
    getAllPersonas(),
    loadPersonaTranslations(locale),
  ]);
  return all.map((persona) => {
    const t = translations[persona.slug];
    return t ? { ...persona, ...t } : persona;
  });
}
