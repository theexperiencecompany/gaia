/**
 * Resolves the API base URL for SSR/SSG. Prefers `API_BASE_URL_INTERNAL` — a
 * server-only var over the private network — since the public
 * `NEXT_PUBLIC_API_BASE_URL` can be unreachable or have an untrusted TLS cert
 * from inside the container, silently turning server-fetched pages into a "not found".
 *
 * Falls back to the public var for local dev (where the two are the same); returns null instead of guessing localhost.
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
