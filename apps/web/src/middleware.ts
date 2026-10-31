import type { NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { selfhostHomeRedirect } from "./features/auth/api/selfhostHomeRedirect";
import { stripLocalePrefix } from "./i18n/config";
import { routing } from "./i18n/routing";
import { isTranslatedPath } from "./i18n/translatedRoutes";

// Renamed from proxy.ts to middleware.ts: Next 16's proxy.ts convention is hard-coded to Node
// runtime, but OpenNext-CF only accepts edge middleware (opennextjs-cloudflare#972); classic
// middleware.ts still works (deprecation warning only) and defaults to edge, which CF requires.

// next-llms-txt's middleware path matching was dropped: it calls process.cwd() at module load,
// which breaks on edge. /llms.txt is served instead by src/app/llms.txt/route.ts.

function isTranslatedRoute(pathname: string): boolean {
  return isTranslatedPath(stripLocalePrefix(pathname));
}

/** Only the production hosts are indexable; any other host the Worker is reached on (previews, aliases) is not. */
const INDEXABLE_HOSTS = new Set(["heygaia.io", "www.heygaia.io"]);

function isIndexableHost(host: string | null): boolean {
  return host !== null && INDEXABLE_HOSTS.has(host.split(":")[0].toLowerCase());
}

const intlMiddleware = createMiddleware(routing);

const intlMiddlewareDefaultOnly = createMiddleware({
  ...routing,
  localePrefix: "never",
  localeDetection: false,
});

/** next-intl's CookieAttributes type omits HttpOnly, so harden its Set-Cookie here. */
function hardenLocaleCookie(response: NextResponse): NextResponse {
  const cookies = response.headers.getSetCookie();
  if (!cookies.some((cookie) => cookie.startsWith("NEXT_LOCALE="))) {
    return response;
  }
  response.headers.delete("set-cookie");
  for (const cookie of cookies) {
    response.headers.append(
      "set-cookie",
      cookie.startsWith("NEXT_LOCALE=") ? `${cookie}; HttpOnly` : cookie,
    );
  }
  return response;
}

function localeResponse(request: NextRequest): NextResponse {
  if (isTranslatedRoute(request.nextUrl.pathname)) {
    return hardenLocaleCookie(intlMiddleware(request));
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

export default async function middleware(request: NextRequest) {
  // A self-hosted instance has no landing page: "/" goes into the product.
  if (request.nextUrl.pathname === "/") {
    const selfhostHome = await selfhostHomeRedirect(request);
    if (selfhostHome) return selfhostHome;
  }
  const response = localeResponse(request);
  if (!isIndexableHost(request.headers.get("host"))) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }
  return response;
}

export const config = {
  // `connect` and `feed` are route handlers outside [locale]; next-intl must
  // not rewrite them (feed.xml 301s to /feed, which must resolve).
  matcher: [
    "/((?!api|connect|feed|_next|_vercel|sitemap|ingest|.*\\..*).*)",
    "/",
  ],
};
