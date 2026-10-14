import { type NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

// heygaia.link is an alias domain of this app (configured at deploy). Its paths are bare
// slugs and the page lives at /l/<slug> under the locale routes, so heygaia.link/<slug>
// is 307'd to heygaia.io/l/<slug>.
const SHORTLINK_HOST = process.env.NEXT_PUBLIC_SHORTLINK_HOST ?? "heygaia.link";
const SHORTLINK_RESOLVE_ORIGIN =
  process.env.NEXT_PUBLIC_APP_ORIGIN ?? "https://heygaia.io";

// Renamed from proxy.ts to middleware.ts: Next 16's proxy.ts convention is hard-coded to Node
// runtime, but OpenNext-CF only accepts edge middleware (opennextjs-cloudflare#972); classic
// middleware.ts still works (deprecation warning only) and defaults to edge, which CF requires.

// next-llms-txt's middleware path matching was dropped: it calls process.cwd() at module load,
// which breaks on edge. /llms.txt is served instead by src/app/llms.txt/route.ts.

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

// Paths next-intl must never rewrite. Checked in code, after the short-link host
// check: the matcher cannot see the host, so excluding them there also dropped
// every heygaia.link slug that happens to start with one of these words.
const INTL_BYPASS_PATH = /^\/(api|connect|_vercel|sitemap|ingest)/;

const intlMiddleware = createMiddleware(routing);

const intlMiddlewareDefaultOnly = createMiddleware({
  ...routing,
  localePrefix: "never",
  localeDetection: false,
});

export default function middleware(request: NextRequest) {
  // Short-link alias host: bounce heygaia.link/<slug> → heygaia.io/l/<slug>
  // before any locale handling.
  if (request.headers.get("host") === SHORTLINK_HOST) {
    const target = new URL(
      `/l${request.nextUrl.pathname}${request.nextUrl.search}`,
      SHORTLINK_RESOLVE_ORIGIN,
    );
    return NextResponse.redirect(target, 307);
  }

  if (INTL_BYPASS_PATH.test(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  if (isTranslatedRoute(request.nextUrl.pathname)) {
    return intlMiddleware(request);
  }
  // For non-translated routes: still run middleware (needed for [locale]
  // routing) but force default locale — no locale prefix in URL.
  const response = intlMiddlewareDefaultOnly(request);
  // These routes have an invariant locale, so next-intl's NEXT_LOCALE cookie here is inert.
  // Dropping it lets Cloudflare edge-cache the ISR HTML (CF bypasses cache on any Set-Cookie),
  // skipping the Worker's cold start; translated routes above keep the cookie since locale varies.
  response.headers.delete("set-cookie");
  return response;
}

export const config = {
  // Only build assets and files are skipped here; INTL_BYPASS_PATH covers the
  // rest in code (`connect` is a locale-invariant page with its own layout).
  matcher: ["/((?!_next|.*\\..*).*)", "/"],
};
