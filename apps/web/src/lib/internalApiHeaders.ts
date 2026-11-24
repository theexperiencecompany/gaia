import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";
import { isSelfhostWeb } from "@/lib/selfhost";

/** Header names the API's rate limiter reads (apps/api/app/constants/http.py). */
const INTERNAL_CALLER_HEADER = "X-Gaia-Internal";
const VIEWER_IP_HEADER = "X-Gaia-Viewer-IP";

/**
 * Headers for a request this server makes to the API: INTERNAL_API_TOKEN (rate
 * limiting only, never auth) and the viewer the page is rendered for. GAIA
 * Cloud names Cloudflare's CF-Connecting-IP; a self-host, whose proxy passes a
 * client's own CF-Connecting-IP through, the X-Forwarded-For hop it wrote.
 * Empty without the token: the API's normal limits apply.
 */
export function internalApiHeaders(viewer?: Headers): Record<string, string> {
  const token = process.env.INTERNAL_API_TOKEN;
  if (!token) return {};
  const headers: Record<string, string> = { [INTERNAL_CALLER_HEADER]: token };
  const forwardedFor = viewer?.get("x-forwarded-for")?.split(",")[0]?.trim();
  const viewerIp = isSelfhostWeb()
    ? forwardedFor
    : (viewer?.get("cf-connecting-ip") ?? forwardedFor);
  if (viewerIp) headers[VIEWER_IP_HEADER] = viewerIp;
  return headers;
}

/** Whether a request from the API presents INTERNAL_API_TOKEN (constant-time); never without one configured. */
export function carriesInternalToken(headers: Headers): boolean {
  const token = process.env.INTERNAL_API_TOKEN;
  const presented = headers.get(INTERNAL_CALLER_HEADER);
  if (!token || presented === null) return false;
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(presented), digest(token));
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
