/**
 * Resolves the API base URL for server-side rendering and static generation.
 *
 * Prefers `API_BASE_URL_INTERNAL` — a server-only, runtime env var pointing at
 * the API over the private network (e.g. http://gaia-backend:8000/api/v1/).
 * This is what SSR/ISR fetches should use: the public `NEXT_PUBLIC_API_BASE_URL`
 * is reachable from the browser but, on container deploys, is often unreachable
 * or has an untrusted TLS cert from inside the web container — which silently
 * turns every server-fetched page (marketplace detail, feeds, profiles) into a
 * "not found".
 *
 * Falls back to `NEXT_PUBLIC_API_BASE_URL` for local dev, where the two are the
 * same. Returns null when neither is configured instead of guessing localhost.
 */
export function getServerApiBaseUrl(): string | null {
  const apiUrl =
    process.env.API_BASE_URL_INTERNAL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!apiUrl) {
    return null;
  }

  return apiUrl.replace(/\/+$/, "");
}
