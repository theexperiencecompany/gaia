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
  getWebIntegrationLogoPath,
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

/** Web-only icons that aren't shared with mobile (brand assets). */
const webOnlyIconUrls: Record<string, string> = {
  gaia: "/brand/gaia_logo.svg",
};

/** Get the full web URL for an image-based icon */
export function getIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  if (!config?.isImage) return null;
  return webOnlyIconUrls[config.icon] ?? getWebIntegrationLogoPath(config.icon);
}

/** WebP → OG-compatible format mapping (Satori doesn't support WebP) */
const webpToOgFormat: Record<string, string> = {
  "/images/icons/twitter.webp": "/images/icons/x.svg",
};

/** Get an OG-compatible icon path (converts WebP to PNG/SVG when available) */
export function getOgIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  if (!config?.isImage) return null;

  const iconPath = getIconPath(category);
  if (!iconPath) return null;

  if (iconPath.endsWith(".webp")) {
    const alternative = webpToOgFormat[iconPath];
    if (!alternative || alternative.endsWith(".webp")) return null;
    return alternative;
  }

  return iconPath;
}
