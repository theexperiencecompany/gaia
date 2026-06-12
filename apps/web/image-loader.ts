import type { ImageLoaderProps } from "next/image";

/**
 * Cloudflare Image Resizing loader for next/image.
 *
 * Routes optimization for SAME-ORIGIN images to Cloudflare's image CDN via the
 * `/cdn-cgi/image/` endpoint instead of Next.js' default optimizer (which, on
 * OpenNext/Workers, runs uncached in the worker and is slow). Cloudflare
 * transforms on the fly at the edge and caches each (source, params, format)
 * variant, so repeat hits are free CDN cache hits and never touch the worker.
 *
 * Remote images (favicons, external logos) are returned untouched so the
 * browser loads them straight from their own CDN. This zone does not enable
 * "resize images from any origin", so `/cdn-cgi/image/` answers 403 for any
 * off-origin source; routing remote URLs through it is what broke them. It also
 * would not help even if enabled — sources like Google's `s2/favicons`
 * 301-redirect to gstatic, and the resizer does not follow redirects. These
 * favicons are already tiny and CDN-cached at the source, so there is nothing
 * to gain from edge-resizing them.
 *
 * Requires "Transformations" (Image Resizing) enabled on the zone.
 */
const normalizeSrc = (src: string) =>
  src.startsWith("/") ? src.slice(1) : src;

const isRemoteSource = (src: string) => /^https?:\/\//i.test(src);

export default function cloudflareLoader({
  src,
  width,
  quality,
}: ImageLoaderProps): string {
  // Data URIs, already-transformed URLs, and any off-origin source bypass the
  // edge resizer and load directly.
  if (
    src.startsWith("data:") ||
    src.includes("/cdn-cgi/image/") ||
    isRemoteSource(src)
  ) {
    return src;
  }

  // In dev there is no Cloudflare edge, so serve the original source directly.
  if (process.env.NODE_ENV === "development") {
    return src;
  }

  const params = [`width=${width}`, `quality=${quality || 75}`, "format=auto"];
  return `/cdn-cgi/image/${params.join(",")}/${normalizeSrc(src)}`;
}
