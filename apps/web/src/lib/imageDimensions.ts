import dimensions from "./image-dimensions.generated.json";

export interface ImageDimensions {
  width: number;
  height: number;
}

const DIMENSIONS = dimensions as Record<string, ImageDimensions>;

/**
 * Fallback ratio for images we cannot measure at build time (remote URLs or
 * assets outside public/). It only supplies width/height attributes; the
 * rendered box is still controlled by the caller's classes.
 */
const FALLBACK: ImageDimensions = { width: 1200, height: 630 };

/**
 * Resolve a local public asset to its intrinsic pixel size. Accepts plain
 * paths (/images/...), absolute URLs, and Cloudflare Image Resizing URLs
 * (/cdn-cgi/image/width=3840,quality=75,format=auto/images/...).
 */
export function getImageDimensions(src: string): ImageDimensions {
  if (!src) return FALLBACK;

  const path = src.split(/[?#]/, 1)[0];
  const marker = path.includes("/images/")
    ? "/images/"
    : path.includes("/brand/")
      ? "/brand/"
      : null;
  if (!marker) return FALLBACK;

  const localPath = path.slice(path.indexOf(marker));
  return DIMENSIONS[localPath] ?? FALLBACK;
}
