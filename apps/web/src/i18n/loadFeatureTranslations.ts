import { defaultLocale } from "./config";

/**
 * Load translated JSON for a feature module.
 * Returns empty object for defaultLocale or if the file is missing.
 */
export async function loadFeatureTranslations<T = Record<string, unknown>>(
  locale: string,
  importFn: (locale: string) => Promise<{ default: T }>,
): Promise<T> {
  if (locale === defaultLocale) return {} as T;
  try {
    return (await importFn(locale)).default;
  } catch {
    console.error(`[i18n] Missing translation file for locale: ${locale}`);
    return {} as T;
  }
}
