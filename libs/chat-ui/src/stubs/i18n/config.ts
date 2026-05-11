/**
 * Pure data + helper copied verbatim from apps/web/src/i18n/config.ts.
 * No runtime side effects to stub.
 */
export const locales = ["en", "es", "fr", "de", "ja", "ko", "pt-BR"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

export function stripLocalePrefix(pathname: string): string {
  for (const locale of locales) {
    const prefix = `/${locale}`;
    if (pathname === prefix) return "/";
    if (pathname.startsWith(`${prefix}/`)) return pathname.slice(prefix.length);
  }
  return pathname;
}
