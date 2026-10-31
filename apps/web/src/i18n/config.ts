export const locales = ["en", "es", "fr", "de", "ja", "ko", "pt-BR"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

/**
 * Prefix a path with the locale segment for non-default locales, matching the
 * `as-needed` routing (default locale has no prefix). Unknown locales fall back
 * to the unprefixed (default-locale) path.
 */
export function localizePath(path: string, locale: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const isLocalized =
    locale !== defaultLocale && (locales as readonly string[]).includes(locale);
  return isLocalized ? `/${locale}${normalized}` : normalized;
}

/**
 * Strip the locale prefix from a raw pathname (e.g. from window.location.pathname).
 * Useful in non-React contexts where the usePathname hook is unavailable.
 */
export function stripLocalePrefix(pathname: string): string {
  for (const locale of locales) {
    const prefix = `/${locale}`;
    if (pathname === prefix) return "/";
    if (pathname.startsWith(`${prefix}/`)) return pathname.slice(prefix.length);
  }
  return pathname;
}
