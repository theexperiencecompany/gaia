/**
 * Sanitizes a redirect/link URL to prevent XSS and open-redirect attacks from
 * backend- or LLM-driven values.
 *
 * Allows only http:, https:, and mailto: absolute URLs, plus safe internal
 * relative paths (single leading slash, not protocol-relative `//` or `/\`).
 * Blocks dangerous schemes like javascript:, data:, vbscript:, etc.
 *
 * @param url - The URL to sanitize
 * @returns The original URL if safe, null if dangerous
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
 * Returns true only for safe internal relative paths — an absolute path that
 * stays on the current origin.
 *
 * Resolves the path against a placeholder origin via the URL parser and checks
 * the origin is unchanged. A genuine same-origin path keeps that origin;
 * protocol-relative (`//host`), backslash (`/\host`), whitespace-smuggled
 * (`/\t/host`), and absolute URLs resolve elsewhere. Delegating to the parser
 * catches normalization tricks that manual prefix checks miss.
 *
 * Use this when navigation must stay same-origin (e.g. router.push from an
 * untrusted payload).
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
