import "server-only";

import { isSelfhostWeb } from "@/lib/selfhost";

/** Header names the API's rate limiter reads (apps/api/app/constants/http.py). */
const INTERNAL_CALLER_HEADER = "X-Gaia-Internal";
const VIEWER_IP_HEADER = "X-Gaia-Viewer-IP";

/**
 * Headers for a request this server makes to the API. INTERNAL_API_TOKEN counts
 * it against the web server's own ceiling instead of one shared Cloudflare
 * address; the API reads it for rate limiting only, never for auth. Given the
 * incoming request, it also names the viewer the page is rendered for:
 * Cloudflare's verified CF-Connecting-IP, else the first X-Forwarded-For hop the
 * instance's proxy wrote. Empty without the token: the API's normal limits apply.
 */
export function internalApiHeaders(viewer?: Headers): Record<string, string> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token) return {};
  const headers: Record<string, string> = { [INTERNAL_CALLER_HEADER]: token };
  const viewerIp =
    viewer?.get("cf-connecting-ip") ??
    viewer?.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (viewerIp) headers[VIEWER_IP_HEADER] = viewerIp;
  return headers;
}

/**
 * Say loudly at boot that GAIA Cloud's web server has no INTERNAL_API_TOKEN: its
 * requests then share the anonymous ceiling of Cloudflare's addresses. A
 * self-host image and development need none.
 */
export function warnWhenInternalApiTokenMissing(): void {
  if (process.env.NODE_ENV !== "production" || isSelfhostWeb()) return;
  if (process.env.INTERNAL_API_TOKEN) return;
  console.error(
    "[startup] INTERNAL_API_TOKEN is not set: the API will rate-limit this web server's requests as one anonymous caller per address.",
  );
}
