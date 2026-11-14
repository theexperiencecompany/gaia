/**
 * The image qualities the resizer may be asked for; Next 16 rejects any other.
 * Plain-js on purpose: `next.config.mjs` (Node) imports it and cannot load TS.
 */

export const DEFAULT_IMAGE_QUALITY = 75;

/** Full-bleed wallpapers: at 1920px the default quality's JPEG fallback passes 200 KB. */
export const WALLPAPER_IMAGE_QUALITY = 60;

export const IMAGE_QUALITIES = [WALLPAPER_IMAGE_QUALITY, DEFAULT_IMAGE_QUALITY];
