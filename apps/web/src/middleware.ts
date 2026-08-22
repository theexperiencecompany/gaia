import type { NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { NEGOTIATION_VARY, negotiate } from "@/lib/agentic/content-negotiation";
import { MARKDOWN_CONTENT_TYPE } from "@/lib/agentic/markdown-pages";
import { getMarkdownVariant } from "@/lib/agentic/markdown-registry";
import { routing } from "./i18n/routing";

// Renamed from `proxy.ts` → `middleware.ts` so we can deploy on Cloudflare via
// `@opennextjs/cloudflare`. Next 16's new `proxy.ts` convention is hard-coded
// to Node runtime; OpenNext-CF only accepts edge middleware (tracking issue:
// https://github.com/opennextjs/opennextjs-cloudflare/issues/972). Next 16
// still accepts `middleware.ts` with only a deprecation warning, and the
// classic `middleware.ts` defaults to edge runtime — exactly what the CF
// adapter requires. Keep this file name until OpenNext ships native proxy
// support.
//
// `next-llms-txt`'s middleware-side path matching was dropped because it
// calls `process.cwd()` at module load and reads files off disk, which
// breaks on edge. The /llms.txt URL is still served by the route handler at
// `src/app/llms.txt/route.ts`.
//
// Markdown content negotiation (acceptmarkdown.com v2): GET requests to
// registry paths (see src/lib/agentic/markdown-registry.ts) negotiate between a
// middleware-generated text/markdown variant and the normal HTML page per
// RFC 9110. Every negotiated response carries `Vary: Accept,
// Accept-Encoding`; non-registry paths are completely untouched.

const translatedPrefixes = [
  "/learn",
  "/automate",
  "/compare",
  "/alternative-to",
  "/for",
];

function isTranslatedRoute(pathname: string): boolean {
  const stripped = pathname.replace(/^\/(de|es|fr|ja|ko|pt-BR)(\/|$)/, "/");
  return translatedPrefixes.some(
    (prefix) => stripped === prefix || stripped.startsWith(`${prefix}/`),
  );
}

const intlMiddleware = createMiddleware(routing);

const intlMiddlewareDefaultOnly = createMiddleware({
  ...routing,
  localePrefix: "never",
  localeDetection: false,
});

const NOT_ACCEPTABLE_BODY =
  "This resource is available as text/html or text/markdown only. Send an Accept header that admits one of these types.";

export default function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const translated = isTranslatedRoute(pathname);

  // Only locale-invariant registry paths participate in negotiation; HEAD and
  // every other method falls through untouched (Next serves HEADs itself).
  let varyOnHtml = false;
  if (!translated && request.method === "GET") {
    const variant = getMarkdownVariant(pathname);
    if (variant) {
      switch (negotiate(request)) {
        case "markdown":
          return new Response(variant.body, {
            status: 200,
            headers: {
              "Content-Type": MARKDOWN_CONTENT_TYPE,
              Vary: NEGOTIATION_VARY,
              "Cache-Control": variant.cacheHint,
            },
          });
        case "notacceptable":
          return new Response(NOT_ACCEPTABLE_BODY, {
            status: 406,
            headers: {
              "Content-Type": "text/plain; charset=utf-8",
              Vary: NEGOTIATION_VARY,
            },
          });
        case "html":
          // Serve the regular page below, but mark the URL as varying by
          // Accept so caches never hand HTML to an agent asking for markdown.
          varyOnHtml = true;
      }
    }
  }

  if (translated) {
    return intlMiddleware(request);
  }
  // For non-translated routes: still run middleware (needed for [locale]
  // routing) but force default locale — no locale prefix in URL.
  const response = intlMiddlewareDefaultOnly(request);
  // These routes are locale-invariant (no detection, no prefix), so the
  // NEXT_LOCALE cookie next-intl writes here is inert — it can never change
  // what locale is served. Dropping the Set-Cookie lets Cloudflare's edge
  // cache store the ISR HTML for these public pages (CF bypasses the cache on
  // any response carrying Set-Cookie), removing the Worker — and its cold
  // start — from the critical path. Translated routes above keep the cookie,
  // since their locale genuinely varies and must not be edge-cached.
  response.headers.delete("set-cookie");
  if (varyOnHtml) {
    mergeVaryHeader(response);
  }
  return response;
}

/**
 * Add the negotiation Vary tokens to an outgoing response without disturbing
 * any header another layer may have set. Existing tokens are preserved and
 * duplicates collapsed.
 */
function mergeVaryHeader(response: NextResponse): void {
  const tokens = new Set(
    (response.headers.get("Vary") ?? "")
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean),
  );
  for (const token of NEGOTIATION_VARY.split(",")) {
    tokens.add(token.trim());
  }
  response.headers.set("Vary", [...tokens].join(", "));
}

export const config = {
  // `connect` is the locale-invariant connect-link redirect route handler
  // (src/app/connect/[code]/route.ts) — exclude it like `api` so next-intl
  // doesn't rewrite it into the [locale] tree.
  matcher: ["/((?!api|connect|_next|_vercel|sitemap|ingest|.*\\..*).*)", "/"],
};
