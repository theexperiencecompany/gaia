/**
 * Canonical filenames for bundled integration logos.
 *
 * Each value is a relative path under `/images/icons/` (web) or under the
 * marketing-site CDN (`https://heygaia.io/images/icons/`) used by mobile.
 * This is the single source of truth for which file represents each
 * integration logo across platforms.
 *
 * For new integrations: add the asset under `apps/web/public/images/icons/`
 * and add an entry here. Web reads it via {@link getWebIntegrationLogoPath};
 * mobile reads it via {@link getMobileIntegrationLogoUrl}.
 */
export const INTEGRATION_LOGO_FILES: Record<string, string> = {
  gmail: "gmail.svg",
  googledocs: "googledocs.webp",
  googlesheets: "googlesheets.webp",
  search: "google.svg",
  weather: "weather.webp",
  notion: "notion.webp",
  twitter: "twitter.webp",
  linkedin: "linkedin.svg",
  googlecalendar: "googlecalendar.webp",
  github: "github.png",
  reddit: "reddit.svg",
  airtable: "airtable.svg",
  linear: "linear.svg",
  slack: "slack.svg",
  hubspot: "hubspot.svg",
  googletasks: "googletasks.svg",
  todoist: "todoist.svg",
  microsoft_teams: "microsoft_teams.svg",
  googlemeet: "googlemeet.svg",
  zoom: "zoom.svg",
  google_maps: "google_maps.svg",
  asana: "asana.svg",
  trello: "trello.svg",
  instagram: "instagram.svg",
  clickup: "clickup.svg",
  deepwiki: "deepwiki.webp",
  context7: "context7.png",
  hackernews: "hackernews.png",
  instacart: "instacart.png",
  yelp: "yelp.png",
  vercel: "vercel.svg",
  perplexity: "perplexity.png",
  figma: "figma.svg",
};

/**
 * Direct external URLs for integrations whose logos are not hosted in
 * `/public/images/icons/` (web embeds these as the value of `webIconUrls`).
 * Mobile reuses the same URLs verbatim — they are CDN-served already.
 */
export const INTEGRATION_LOGO_EXTERNAL_URLS: Record<string, string> = {
  browserbase:
    "https://www.google.com/s2/favicons?domain=browserbase.com&sz=128",
  posthog: "https://www.google.com/s2/favicons?domain=posthog.com&sz=128",
  agentmail:
    "https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://agentmail.to&size=256",
};

/**
 * Public CDN base for the bundled `/images/icons/*` assets. Mobile uses this
 * because Metro cannot bundle the SVG/WebP files directly without a custom
 * transformer; the marketing site serves the same assets with long-cache
 * headers and `access-control-allow-origin: *`.
 */
export const MOBILE_INTEGRATION_LOGO_CDN = "https://heygaia.io/images/icons";

/**
 * Resolve the web-relative path for an integration logo (e.g. `/images/icons/slack.svg`).
 * Returns null when the integration is not in the registry.
 */
export function getWebIntegrationLogoPath(key: string): string | null {
  const external = INTEGRATION_LOGO_EXTERNAL_URLS[key];
  if (external) return external;
  const file = INTEGRATION_LOGO_FILES[key];
  if (!file) return null;
  return `/images/icons/${file}`;
}

/**
 * Resolve the absolute CDN URL for an integration logo. Mobile uses this so it
 * renders the exact same artwork as web (no Google S2 favicon downscale).
 * Returns null when the integration is not in the registry.
 */
export function getMobileIntegrationLogoUrl(key: string): string | null {
  const external = INTEGRATION_LOGO_EXTERNAL_URLS[key];
  if (external) return external;
  const file = INTEGRATION_LOGO_FILES[key];
  if (!file) return null;
  return `${MOBILE_INTEGRATION_LOGO_CDN}/${file}`;
}
