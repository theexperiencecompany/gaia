import type { ImageLoaderProps } from "next/image";

/**
 * Cloudflare Image Resizing loader for next/image.
 *
 * Routes optimization to Cloudflare's image CDN via the `/cdn-cgi/image/`
 * endpoint instead of Next.js' default optimizer (which, on OpenNext/Workers,
 * runs uncached in the worker and is slow). Cloudflare transforms on the fly at
 * the edge and caches each (source, params, format) variant, so repeat hits are
 * free CDN cache hits and never touch the worker.
 *
 * Requires "Transformations" (Image Resizing) enabled on the zone, plus
 * "resize images from any origin" if remote sources are transformed.
 */
const normalizeSrc = (src: string) =>
  src.startsWith("/") ? src.slice(1) : src;

// Cloudflare treats everything after the options segment as the source, so a
// `?` or `#` in the source (e.g. signed image URLs) would otherwise be parsed
// as the loader URL's own query/fragment and truncate the path. Escape them.
const escapeSrcForPath = (src: string) =>
  normalizeSrc(src).replaceAll("?", "%3F").replaceAll("#", "%23");

export default function cloudflareLoader({
  src,
  width,
  quality,
}: ImageLoaderProps): string {
  // Data URIs and already-transformed URLs pass through untouched.
  if (src.startsWith("data:") || src.includes("/cdn-cgi/image/")) {
    return src;
  }

  // In dev there is no Cloudflare edge, so serve the original source directly.
  if (process.env.NODE_ENV === "development") {
    return src;
  }

  const params = [`width=${width}`, `quality=${quality || 75}`, "format=auto"];
  return `/cdn-cgi/image/${params.join(",")}/${escapeSrcForPath(src)}`;
}
