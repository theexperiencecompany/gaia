import type { Metadata } from "next";

import {
  generatePageMetadata,
  getSiteUrl,
  type PageMetadataOptions,
} from "@/lib/seo";

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
 * locale-aware canonical plus the hreflang map, so each variant points at
 * itself. `canonicalPath`, if given, consolidates near-duplicate pages so canonical and hreflang both resolve against it.
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

/**
 * Page metadata for a translated route: `generatePageMetadata` plus the
 * locale-aware self-canonical + hreflang block, in one call. Use on every page
 * under a translated route family instead of repeating the spread-and-override.
 */
export function generateLocalizedPageMetadata(
  options: PageMetadataOptions & { locale: string },
): Metadata {
  const { locale, ...pageOptions } = options;
  return {
    ...generatePageMetadata(pageOptions),
    alternates: getLocalizedAlternates(
      pageOptions.path,
      locale,
      pageOptions.canonicalPath,
    ),
  };
}
