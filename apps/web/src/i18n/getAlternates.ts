import type { Metadata } from "next";

import {
  generatePageMetadata,
  getSiteUrl,
  type PageMetadataOptions,
} from "@/lib/seo";

import { defaultLocale, locales, localizePath } from "./config";

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
 * itself. Near-duplicate consolidation lives one layer down at the router
 * (308s in `canonical-redirects.mjs`), so every rendered page canonicalizes
 * to itself — no override parameter.
 */
function getLocalizedAlternates(
  path: string,
  locale: string,
): { canonical: string; languages: Record<string, string> } {
  return {
    canonical: `${getSiteUrl()}${localizePath(path, locale)}`,
    languages: getAlternates(path),
  };
}

/**
 * Page metadata for a translated route: `generatePageMetadata` plus the
 * locale-aware self-canonical + hreflang block, with og:url on that canonical,
 * in one call. Use on every page under a translated route family instead of
 * repeating the spread-and-override.
 */
export function generateLocalizedPageMetadata(
  options: PageMetadataOptions & { locale: string },
): Metadata {
  const { locale, ...pageOptions } = options;
  const metadata = generatePageMetadata(pageOptions);
  const alternates = getLocalizedAlternates(pageOptions.path, locale);
  return {
    ...metadata,
    alternates,
    openGraph: { ...metadata.openGraph, url: alternates.canonical },
  };
}
