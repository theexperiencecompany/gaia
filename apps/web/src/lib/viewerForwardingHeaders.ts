/** Header names the API's rate limiter reads (apps/api/app/constants/http.py). */
const VIEWER_IP_HEADER = "X-Gaia-Viewer-IP";
const INTERNAL_RESOLVER_HEADER = "X-Gaia-Internal";

/**
 * Headers that let a server-side fetch made for one viewer count against that
 * viewer's rate limit instead of the web server's. The viewer is Cloudflare's
 * verified CF-Connecting-IP on GAIA Cloud, else the first X-Forwarded-For hop
 * the instance's own proxy wrote. Empty without INTERNAL_RESOLVER_TOKEN, since
 * the API believes the viewer header only alongside it.
 */
export function viewerForwardingHeaders(
  incoming: Headers,
): Record<string, string> {
  const token = process.env.INTERNAL_RESOLVER_TOKEN;
  const viewerIp =
    incoming.get("cf-connecting-ip") ??
    incoming.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (!token || !viewerIp) return {};
  return { [VIEWER_IP_HEADER]: viewerIp, [INTERNAL_RESOLVER_HEADER]: token };
}
