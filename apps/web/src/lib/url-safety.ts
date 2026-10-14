/**
 * Sanitizes a URL for redirects: allows http:, https:, mailto:, and safe internal
 * relative paths (single leading slash, not protocol-relative `//` or backslash `/\`).
 * Returns null for anything else (e.g. javascript:, data:, vbscript:).
 */
export function sanitizeRedirectUrl(url: string): string | null {
  // Allow safe internal relative paths: a single leading slash, but not
  // protocol-relative (`//host`) or backslash tricks (`/\host`).
  if (isSafeInternalPath(url)) {
    return url;
  }

  try {
    const parsed = new URL(url);

    if (
      parsed.protocol !== "http:" &&
      parsed.protocol !== "https:" &&
      parsed.protocol !== "mailto:"
    ) {
      console.warn(`Blocked redirect to unsafe URL scheme: ${parsed.protocol}`);
      return null;
    }

    return url;
  } catch {
    console.warn(`Blocked redirect to malformed URL: ${url}`);
    return null;
  }
}

/**
 * True only for a same-origin relative path: single leading slash, not protocol-relative
 * (`//host`), backslash (`/\host`), or whitespace-smuggled (`/\t/host`).
 *
 * Resolves against a placeholder origin via the URL parser so normalization tricks a
 * manual prefix check would miss are still caught.
 */
export function isSafeInternalPath(url: string): boolean {
  if (!url.startsWith("/")) return false;
  const placeholderOrigin = "https://internal.invalid";
  try {
    return new URL(url, placeholderOrigin).origin === placeholderOrigin;
  } catch {
    return false;
  }
}

/**
 * True when `href` stays inside this app: a same-origin path, or an absolute
 * URL on `appOrigin` (the API links to `/integrations` with its FRONTEND_URL,
 * so the absolute form is the common one). Such links belong in the same
 * tab: opening the app beside itself leaves the user with two sessions of
 * one chat. An empty `appOrigin` (server render) treats only paths as
 * internal.
 */
export function isAppLink(href: string, appOrigin: string): boolean {
  if (isSafeInternalPath(href)) return true;
  if (!appOrigin) return false;
  try {
    return new URL(href).origin === appOrigin;
  } catch {
    return false;
  }
}
