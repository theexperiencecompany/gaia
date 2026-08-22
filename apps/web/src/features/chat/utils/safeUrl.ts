/**
 * Parse a value into an absolute http(s) URL, or return null instead of
 * throwing on malformed input from search payloads.
 */
export function safeUrl(value: unknown): URL | null {
  try {
    const url = new URL(String(value));
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}
