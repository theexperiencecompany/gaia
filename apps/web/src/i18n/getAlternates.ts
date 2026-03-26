import { getSiteUrl } from "@/lib/seo";

import { defaultLocale, locales } from "./config";

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
