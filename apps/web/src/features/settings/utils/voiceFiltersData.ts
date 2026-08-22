/** Shared constants/helpers for the voice settings filter UI. */

const FLAG_CDN_BASE = "https://flagcdn.com/w80";

/** Sentinel filter value meaning "no gender/country filtering". */
export const ALL_FILTER = "all";

/** Flag image URL for a country code, served from flagcdn. */
export const flagUrl = (countryCode: string) =>
  `${FLAG_CDN_BASE}/${countryCode.toLowerCase()}.png`;
