/**
 * Pure navigation policy for the main window, split out from the electron-bound
 * {@link guardNavigation} so it can be unit-tested without the electron runtime.
 *
 * - `"allow"` — same-origin as one of the app's known-good origins; let it navigate.
 * - `"open-external"` — a different http(s) origin; block in-window, open in the
 *   OS browser instead.
 * - `"block"` — malformed, or a non-http(s) scheme (mailto:, javascript:, custom
 *   protocols); block outright and do not hand it to the OS.
 */
export type NavigationDecision = "allow" | "open-external" | "block";

export function classifyNavigation(
  url: string,
  allowedOrigins: ReadonlySet<string>,
): NavigationDecision {
  let targetUrl: URL;
  try {
    targetUrl = new URL(url);
  } catch {
    return "block";
  }

  if (allowedOrigins.has(targetUrl.origin)) return "allow";

  if (targetUrl.protocol === "https:" || targetUrl.protocol === "http:") {
    return "open-external";
  }

  return "block";
}
