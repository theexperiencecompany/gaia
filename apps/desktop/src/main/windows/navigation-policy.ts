/**
 * Pure navigation policy for the main window, split out from {@link guardNavigation}
 * for unit-testing without electron. "allow" = same origin as a known-good origin;
 * "open-external" = a different http(s) origin (open in the OS browser instead);
 * "block" = malformed or a non-http(s) scheme (mailto:, javascript:, custom).
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
