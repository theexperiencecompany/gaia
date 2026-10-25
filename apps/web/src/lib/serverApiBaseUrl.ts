/**
 * Resolves the API base URL for SSR/SSG: `API_BASE_URL_INTERNAL` (the private
 * network) first, since the public URL can be unreachable from the container.
 * Falls back to the public var for local dev. A same-origin public base (the
 * self-host image's "/api/v1/") is browser-only, so it resolves to null.
 */
export function getServerApiBaseUrl(): string | null {
  const apiUrl =
    process.env.API_BASE_URL_INTERNAL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!apiUrl || !URL.canParse(apiUrl)) {
    return null;
  }

  return apiUrl.replace(/\/+$/, "");
}
