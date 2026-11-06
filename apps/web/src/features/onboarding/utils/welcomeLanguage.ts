import { locales } from "@/i18n/config";

const primarySubtag = (tag: string): string =>
  tag.trim().replace("_", "-").split("-")[0].toLowerCase();

const SUPPORTED_LANGUAGES = new Set(locales.map(primarySubtag));

/**
 * The language the welcome thread is written in: the first browser language
 * the web app is translated into, else the app locale. The onboarding route
 * itself is never localised, so the app locale alone is always English there.
 */
export function welcomeLanguage(
  browserLanguages: readonly string[],
  appLocale: string,
): string {
  return (
    browserLanguages.find((tag) =>
      SUPPORTED_LANGUAGES.has(primarySubtag(tag)),
    ) ?? appLocale
  );
}
