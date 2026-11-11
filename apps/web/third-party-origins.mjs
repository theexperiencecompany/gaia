/**
 * Third-party origins the web app loads from, shared by the code that loads
 * them and the Content-Security-Policy that allows them (security-headers.mjs).
 *
 * Plain-js on purpose: `next.config.mjs` (Node) imports it and cannot load TS.
 */

/** PostHog ingestion host; the app proxies it under /ingest (next.config.mjs rewrites). */
export const POSTHOG_HOST = (
  process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com"
).replace(/\/+$/, "");

export const RYBBIT_HOST =
  process.env.NEXT_PUBLIC_RYBBIT_HOST ?? "https://as.heygaia.io";

export const FASTLANE_HOST =
  process.env.NEXT_PUBLIC_FASTLANE_HOST ??
  "https://aromatic-caribou-889.convex.site";
