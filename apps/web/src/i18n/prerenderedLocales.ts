import { isSelfhostWeb } from "@/lib/selfhost";

import { defaultLocale, type Locale, locales } from "./config";

/**
 * Locales the [locale] tree prerenders at build. Self-host serves its
 * marketing pages in the default locale only: all seven multiplied the image
 * by ~1.3 GB of SEO pages nobody crawls on a private instance.
 */
export function prerenderedLocales(): readonly Locale[] {
  return isSelfhostWeb() ? [defaultLocale] : locales;
}
