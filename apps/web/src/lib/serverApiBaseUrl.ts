/**
 * Resolves API base URL for server-side rendering and static generation.
 * Returns null when not configured instead of silently falling back to localhost.
 */
export function getServerApiBaseUrl(): string | null {
  const apiUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!apiUrl) {
    return null;
  }

  return apiUrl.replace(/\/+$/, "");
}
