import { loadStaticJson } from "@/lib/feature-data";

import { defaultLocale } from "./config";

/**
 * Load translated JSON for a feature module from
 * `public/data/i18n/{feature}/{locale}.json`, through the same reader as the
 * base entries (`loadStaticJson`).
 *
 * Returns empty object for `defaultLocale` or a missing file.
 */

const SOURCE_LOCALE_RETURNS_EMPTY = true;

/** Each overlay parsed once per process, as feature-data caches the base entries: a locale's file is read by every page in it. */
const overlayCache = new Map<string, unknown>();

export async function loadFeatureTranslations<T = Record<string, unknown>>(
  locale: string,
  feature: string,
): Promise<T> {
  if (SOURCE_LOCALE_RETURNS_EMPTY && locale === defaultLocale) return {} as T;

  const relPath = `/data/i18n/${feature}/${locale}.json`;
  const cached = overlayCache.get(relPath);
  if (cached) return cached as T;

  const translations = await loadStaticJson<T>(relPath);
  if (translations !== null) {
    overlayCache.set(relPath, translations);
    return translations;
  }

  console.error(`[i18n] Missing translations for ${feature}/${locale}`);
  return {} as T;
}
