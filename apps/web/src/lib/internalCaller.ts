import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";
import { INTERNAL_CALLER_HEADER } from "@/lib/internalApiHeaders";

/**
 * Whether a request from the API presents INTERNAL_API_TOKEN (constant-time);
 * never without one configured. Apart from internalApiHeaders because that
 * module also loads in the edge runtime, which has no node:crypto.
 */
export function carriesInternalToken(headers: Headers): boolean {
  const token = process.env.INTERNAL_API_TOKEN;
  const presented = headers.get(INTERNAL_CALLER_HEADER);
  if (!token || presented === null) return false;
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(presented), digest(token));
}
