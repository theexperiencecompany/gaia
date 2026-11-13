import type { ImageLoaderProps } from "next/image";

/**
 * Cloudflare Image Resizing loader for next/image: same-origin images route
 * through `/cdn-cgi/image/` (edge-cached; Next's default optimizer runs uncached
 * on OpenNext/Workers). Remote images pass through untouched — this zone 403s
 * off-origin resizing, and Google's s2/favicons redirects (unfollowed) anyway.
 * Requires "Transformations" enabled on the zone.
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
