/**
 * Origin test for "is this URL served by our own GAIA API?".
 *
 * Dependency-free on purpose: the outbound envelope schema and the media
 * download path both need it, and the schema is imported by React Native
 * consumers that cannot resolve axios or `node:` builtins.
 */

/**
 * True when `url` is served by the GAIA API `baseUrl` points at.
 *
 * Origin equality, never a path or substring test: `https://evil.com/<our
 * host>/…` and `https://<our host>.evil.com/…` both carry our host and neither
 * is ours. `URL.origin` normalises case, a default port and a trailing slash.
 */
export function isOwnApiUrl(baseUrl: string | undefined, url: string): boolean {
  if (!baseUrl) return false;
  try {
    const origin = new URL(url).origin;
    return origin !== "null" && origin === new URL(baseUrl).origin;
  } catch {
    return false;
  }
}
