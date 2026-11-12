/**
 * The content origin's edge: <content_id>.u.heygaia.link forwarded to the API.
 *
 * The API's /api/v1/usercontent route owns every serving rule (headers, the
 * Sec-Fetch-Dest gate, tokens, liveness). This Worker only proves the host,
 * names it in X-Gaia-Content-Host beside the internal token, and keeps cookies
 * out in both directions.
 */

export interface Env {
  /** The API's origin, e.g. https://api.heygaia.io (wrangler var). */
  API_ORIGIN: string;
  /** The API's INTERNAL_API_TOKEN (wrangler secret); vouches for X-Gaia-Content-Host. */
  INTERNAL_API_TOKEN: string;
}

const CONTENT_HOST_SUFFIX = ".u.heygaia.link";
const CONTENT_ID_PATTERN = /^[a-z2-7]{26}$/;
const CONTENT_ROUTE = "/api/v1/usercontent";
const THUMBNAIL_PATH = "/thumb.jpg";
const ALLOWED_METHODS = ["GET", "HEAD"];
// Only what the API's serving rules read; Cookie and Authorization never leave the edge.
const FORWARDED_REQUEST_HEADERS = ["Sec-Fetch-Dest", "Range", "If-None-Match"];

function contentIdOf(host: string): string | null {
  if (!host.endsWith(CONTENT_HOST_SUFFIX)) return null;
  const label = host.slice(0, -CONTENT_HOST_SUFFIX.length);
  return CONTENT_ID_PATTERN.test(label) ? label : null;
}

function upstreamPath(contentId: string, pathname: string): string | null {
  if (pathname === "/") return `${CONTENT_ROUTE}/${contentId}`;
  if (pathname === THUMBNAIL_PATH) {
    return `${CONTENT_ROUTE}/${contentId}${THUMBNAIL_PATH}`;
  }
  return null;
}

function upstreamHeaders(request: Request, host: string, env: Env): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("X-Gaia-Content-Host", host);
  headers.set("X-Gaia-Internal", env.INTERNAL_API_TOKEN);
  const viewerIp = request.headers.get("CF-Connecting-IP");
  if (viewerIp !== null) headers.set("X-Gaia-Viewer-IP", viewerIp);
  return headers;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!ALLOWED_METHODS.includes(request.method)) {
      return new Response(null, {
        status: 405,
        headers: { Allow: ALLOWED_METHODS.join(", ") },
      });
    }
    const url = new URL(request.url);
    const contentId = contentIdOf(url.hostname);
    const path = contentId && upstreamPath(contentId, url.pathname);
    if (!path) return new Response(null, { status: 404 });

    const upstream = await fetch(`${env.API_ORIGIN}${path}${url.search}`, {
      method: request.method,
      headers: upstreamHeaders(request, url.hostname, env),
      redirect: "manual",
    });
    const response = new Response(upstream.body, upstream);
    response.headers.delete("Set-Cookie");
    return response;
  },
};
