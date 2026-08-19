const FLAG_CDN_BASE = "https://flagcdn.com/w80";

export const flagUrl = (countryCode: string) =>
  `${FLAG_CDN_BASE}/${countryCode.toLowerCase()}.png`;
