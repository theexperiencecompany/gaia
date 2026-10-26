/**
 * The one source of truth for the security headers every response carries.
 * Worker-rendered routes get them from next.config.mjs headers(); Workers Static
 * Assets (promoted landing HTML, public/ files) never reach the worker, so
 * scripts/write-static-headers.mjs renders the same rules into their _headers.
 *
 * Plain-js on purpose: `next.config.mjs` (Node) imports it and cannot load TS.
 */
import { FASTLANE_HOST, POSTHOG_HOST, RYBBIT_HOST } from "./third-party-origins.mjs";

/** Same-origin MCP-UI sandbox proxy, iframed by MCPAppRenderer; the one page the app frames. */
export const SANDBOX_PROXY_PATH = "/mcp-sandbox-proxy.html";

const CSP_REPORT_GROUP = "posthog";

// PostHog's CSP violation sink (posthog.com/docs/csp-tracking); the trailing slash is required.
const posthogProjectToken = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN;
const cspReportUrl = posthogProjectToken
  ? `${POSTHOG_HOST}/report/?token=${posthogProjectToken}`
  : undefined;

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
// Artifact previews iframe the API origin; a relative base is already 'self'.
const apiOrigin = apiBaseUrl && URL.canParse(apiBaseUrl) ? new URL(apiBaseUrl).origin : undefined;

// React needs eval in development for its debugging features (Next.js CSP guide).
const devScriptSources = process.env.NODE_ENV === "development" ? ["'unsafe-eval'"] : [];

// Report-Only: a wrong enforced CSP silently breaks the app, so violations are
// collected first. Images, media and fetches are open-ended (OAuth avatars,
// LLM-supplied media, LiveKit, user MCP servers), so those stay scheme-wide.
const CSP_DIRECTIVES = [
  ["default-src", "'self'"],
  [
    "script-src",
    "'self'",
    "'unsafe-inline'",
    "'wasm-unsafe-eval'",
    ...devScriptSources,
    "https://www.googletagmanager.com",
    "https://browser.sentry-cdn.com",
    "https://*.dodopayments.com",
    RYBBIT_HOST,
    FASTLANE_HOST,
  ],
  ["style-src", "'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
  ["font-src", "'self'", "data:", "https://cdn.jsdelivr.net"],
  ["img-src", "'self'", "data:", "blob:", "https:"],
  ["media-src", "'self'", "data:", "blob:", "https:"],
  ["connect-src", "'self'", "https:", "wss:", ...(apiOrigin ? [apiOrigin] : [])],
  [
    "frame-src",
    "'self'",
    "blob:",
    "https://status.heygaia.io",
    "https://www.youtube.com",
    "https://player.vimeo.com",
    "https://*.dodopayments.com",
    ...(apiOrigin ? [apiOrigin] : []),
  ],
  ["worker-src", "'self'", "blob:"],
  ["object-src", "'none'"],
  ["base-uri", "'self'"],
  ["frame-ancestors", "'none'"],
  ...(cspReportUrl
    ? [
        ["report-uri", cspReportUrl],
        ["report-to", CSP_REPORT_GROUP],
      ]
    : []),
];

const CONTENT_SECURITY_POLICY = CSP_DIRECTIVES.map((directive) => directive.join(" ")).join("; ");

/** Headers both the site and the sandbox proxy carry. */
const BASE_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Every resolving *.heygaia.io host serves valid HTTPS, so subdomains are pinned too.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  // The voice agent and wake word use the microphone; nothing uses camera, location or USB.
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self), usb=()" },
];

const SITE_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  ...BASE_HEADERS,
  { key: "Content-Security-Policy-Report-Only", value: CONTENT_SECURITY_POLICY },
  ...(cspReportUrl
    ? [{ key: "Reporting-Endpoints", value: `${CSP_REPORT_GROUP}="${cspReportUrl}"` }]
    : []),
];

// No site CSP here: the proxy writes MCP app HTML into a child frame that would
// inherit it, and it ships its own meta CSP. Only framing is constrained.
const SANDBOX_PROXY_HEADERS = [
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  ...BASE_HEADERS,
  { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
];

const escapedProxyPath = SANDBOX_PROXY_PATH.slice(1).replaceAll(".", "\\.");

/** next.config.mjs headers() rules; Next has no header detach, so the site rule skips the proxy. */
export const NEXT_SECURITY_HEADER_RULES = [
  { source: `/((?!${escapedProxyPath}$).*)`, headers: SITE_HEADERS },
  { source: SANDBOX_PROXY_PATH, headers: SANDBOX_PROXY_HEADERS },
];

function headerLines(headers) {
  return headers.map(({ key, value }) => `  ${key}: ${value}`);
}

/** The same rules in Workers Static Assets _headers syntax, appended to the checked-in cache rules. */
export function renderStaticHeaders(cacheRules) {
  return [
    cacheRules.trimEnd(),
    "",
    "# Security headers, generated from security-headers.mjs by scripts/write-static-headers.mjs.",
    "/*",
    ...headerLines(SITE_HEADERS),
    SANDBOX_PROXY_PATH,
    ...SITE_HEADERS.map(({ key }) => `  ! ${key}`),
    ...headerLines(SANDBOX_PROXY_HEADERS),
    "",
  ].join("\n");
}
