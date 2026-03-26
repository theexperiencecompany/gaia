/**
 * Tool Icon Configuration - Web Layer
 *
 * Re-exports the shared config from @shared/icons and adds web-specific
 * utilities (OG image URL resolution, WebP format mapping).
 *
 * For the canonical config, see: libs/shared/ts/src/icons/tool-icon-config.ts
 */

import type { ToolIconConfig } from "@shared/icons";
import {
  getCategoryInitial,
  getToolIconConfig,
  iconAliases,
  normalizeCategoryName,
  toolIconConfigs,
} from "@shared/icons";

export type { ToolIconConfig };
export {
  getCategoryInitial,
  getToolIconConfig,
  iconAliases,
  normalizeCategoryName,
  toolIconConfigs,
};

/** Web-specific: maps integration key names to their public image URLs */
export const webIconUrls: Record<string, string> = {
  gmail: "/images/icons/gmail.svg",
  googledocs: "/images/icons/googledocs.webp",
  googlesheets: "/images/icons/googlesheets.webp",
  search: "/images/icons/google.svg",
  weather: "/images/icons/weather.webp",
  notion: "/images/icons/notion.webp",
  twitter: "/images/icons/twitter.webp",
  linkedin: "/images/icons/linkedin.svg",
  googlecalendar: "/images/icons/googlecalendar.webp",
  github: "/images/icons/github.png",
  reddit: "/images/icons/reddit.svg",
  airtable: "/images/icons/airtable.svg",
  linear: "/images/icons/linear.svg",
  slack: "/images/icons/slack.svg",
  hubspot: "/images/icons/hubspot.svg",
  googletasks: "/images/icons/googletasks.svg",
  todoist: "/images/icons/todoist.svg",
  microsoft_teams: "/images/icons/microsoft_teams.svg",
  googlemeet: "/images/icons/googlemeet.svg",
  zoom: "/images/icons/zoom.svg",
  google_maps: "/images/icons/google_maps.svg",
  asana: "/images/icons/asana.svg",
  trello: "/images/icons/trello.svg",
  instagram: "/images/icons/instagram.svg",
  clickup: "/images/icons/clickup.svg",
  deepwiki: "/images/icons/deepwiki.webp",
  context7: "/images/icons/context7.png",
  hackernews: "/images/icons/hackernews.png",
  instacart: "/images/icons/instacart.png",
  yelp: "/images/icons/yelp.png",
  vercel: "/images/icons/vercel.svg",
  perplexity: "/images/icons/perplexity.png",
  figma: "/images/icons/figma.svg",
  browserbase:
    "https://www.google.com/s2/favicons?domain=browserbase.com&sz=128",
  posthog: "https://www.google.com/s2/favicons?domain=posthog.com&sz=128",
  agentmail:
    "https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://agentmail.to&size=256",
  gaia: "/brand/gaia_logo.svg",
};

/** Get the full web URL for an image-based icon */
export function getIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  if (!config?.isImage) return null;
  return webIconUrls[config.icon] ?? null;
}

/** WebP → OG-compatible format mapping (Satori doesn't support WebP) */
const webpToOgFormat: Record<string, string> = {
  "/images/icons/twitter.webp": "/images/icons/x.svg",
};

/** Get an OG-compatible icon path (converts WebP to PNG/SVG when available) */
export function getOgIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  if (!config?.isImage) return null;

  const iconPath = webIconUrls[config.icon];
  if (!iconPath) return null;

  if (iconPath.endsWith(".webp")) {
    const alternative = webpToOgFormat[iconPath];
    if (!alternative || alternative.endsWith(".webp")) return null;
    return alternative;
  }

  return iconPath;
}
