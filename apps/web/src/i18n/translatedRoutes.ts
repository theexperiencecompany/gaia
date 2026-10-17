/** Route families served in every locale; everything else on the marketing site is English-only. */
export const TRANSLATED_ROUTE_FAMILIES = [
  "/compare",
  "/alternative-to",
  "/automate",
  "/for",
  "/learn",
] as const;

/** Whether an internal path lives in a translated family, so a localized page should keep its locale when linking it. */
export function isTranslatedPath(path: string): boolean {
  return TRANSLATED_ROUTE_FAMILIES.some(
    (family) => path === family || path.startsWith(`${family}/`),
  );
}
