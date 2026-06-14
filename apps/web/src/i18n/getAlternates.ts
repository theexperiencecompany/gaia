import { getSiteUrl } from "@/lib/seo";

import { defaultLocale, locales } from "./config";

/**
 * Prefix a path with the locale segment for non-default locales, matching the
 * `as-needed` routing (default locale has no prefix). Unknown locales fall back
 * to the unprefixed (default-locale) path.
 */
function localizePath(path: string, locale: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const isLocalized =
    locale !== defaultLocale && (locales as readonly string[]).includes(locale);
  return isLocalized ? `/${locale}${normalized}` : normalized;
}

/**
 * Generate hreflang alternate links for a given path.
 * Used in page metadata to tell search engines about locale variants.
 */
export function getAlternates(path: string): Record<string, string> {
  if (path && !path.startsWith("/")) {
    path = `/${path}`;
  }

  const alternates: Record<string, string> = {};

  for (const locale of locales) {
    if (locale === defaultLocale) {
      alternates[locale] = `${getSiteUrl()}${path}`;
    } else {
      alternates[locale] = `${getSiteUrl()}/${locale}${path}`;
    }
  }

  alternates["x-default"] = `${getSiteUrl()}${path}`;

  return alternates;
}

/**
 * Build the full `alternates` block for a translated page: a self-referential,
 * locale-aware canonical plus the hreflang map. Use on every page under a
 * translated route family so each locale variant points its canonical at
 * itself (not at the default-locale URL) and cross-references its siblings.
 *
 * @param path           The page's own path (e.g. `/compare/zapier`).
 * @param locale         The active locale from the route params.
 * @param canonicalPath  Optional consolidated target for near-duplicate pages;
 *                       both canonical and hreflang resolve against it so they
 *                       never point at a non-canonical URL.
 */
export function getLocalizedAlternates(
  path: string,
  locale: string,
  canonicalPath?: string,
): { canonical: string; languages: Record<string, string> } {
  const target = canonicalPath ?? path;
  return {
    canonical: `${getSiteUrl()}${localizePath(target, locale)}`,
    languages: getAlternates(target),
  };
}
