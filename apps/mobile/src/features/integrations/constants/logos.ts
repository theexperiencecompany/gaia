import {
  getMobileIntegrationLogoUrl,
  INTEGRATION_LOGO_EXTERNAL_URLS,
  INTEGRATION_LOGO_FILES,
  MOBILE_INTEGRATION_LOGO_CDN,
} from "@gaia/shared/icons";

/**
 * Centralised registry of fallback logos for known platform integrations.
 * If a backend-provided iconUrl exists it always wins; otherwise we look up
 * the integration ID here. Returns null when nothing is known.
 *
 * Mirrors `webIconUrls` in `apps/web/src/config/toolIconConfig.ts` byte-for-byte
 * — the only difference is mobile points to the CDN-hosted copy of the same
 * assets (`heygaia.io/images/icons/...`) so the artwork is identical.
 */
export const INTEGRATION_LOGOS: Record<string, string> = Object.fromEntries(
  [
    ...Object.keys(INTEGRATION_LOGO_FILES),
    ...Object.keys(INTEGRATION_LOGO_EXTERNAL_URLS),
  ].flatMap((key) => {
    const url = getMobileIntegrationLogoUrl(key);
    return url ? [[key, url] as const] : [];
  }),
);

/** Generic placeholder for IDs that aren't in the registry. */
export const INTEGRATION_LOGO_FALLBACK = `${MOBILE_INTEGRATION_LOGO_CDN}/notion.webp`;

/**
 * Resolve a logo URI for an integration.
 *
 * @param id - integration ID (matches keys in INTEGRATION_LOGOS).
 * @param iconUrl - optional backend-provided icon URL; if present it wins.
 * @returns the best logo URI or null when no fallback exists.
 */
export function getIntegrationLogo(
  id: string,
  iconUrl?: string | null,
): string | null {
  if (iconUrl) return iconUrl;
  return INTEGRATION_LOGOS[id] ?? null;
}

/**
 * Like {@link getIntegrationLogo} but always returns a string by falling back
 * to a generic placeholder image when nothing else is known.
 */
export function getIntegrationLogoOrFallback(
  id: string,
  iconUrl?: string | null,
): string {
  return getIntegrationLogo(id, iconUrl) ?? INTEGRATION_LOGO_FALLBACK;
}
