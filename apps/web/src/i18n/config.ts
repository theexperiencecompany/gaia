export const locales = ["en", "es", "fr", "de", "ja", "ko", "pt-BR"] as const;

export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";
