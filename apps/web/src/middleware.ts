import { type NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

// heygaia.link is a display-only alias domain served by THIS same app (added as
// a Vercel domain alias at deploy time — infra, not code). Session cookies are
// scoped to heygaia.io and are NOT sent cross-domain to heygaia.link, so a short
// link can only be resolved (viewer-scoped, auth-required) on heygaia.io. Every
// heygaia.link/<slug> is therefore 307'd to heygaia.io/l/<slug>, where the
// viewer's session lives; that host-based bounce is the only special rule.
const SHORTLINK_HOST = process.env.NEXT_PUBLIC_SHORTLINK_HOST ?? "heygaia.link";
const SHORTLINK_RESOLVE_ORIGIN =
  process.env.NEXT_PUBLIC_APP_ORIGIN ?? "https://heygaia.io";

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

export default function middleware(request: NextRequest) {
  // Short-link alias host: bounce heygaia.link/<slug> → heygaia.io/l/<slug>
  // before any locale handling, so resolution runs where the session cookie is.
  if (request.headers.get("host") === SHORTLINK_HOST) {
    const target = new URL(
      `/l${request.nextUrl.pathname}${request.nextUrl.search}`,
      SHORTLINK_RESOLVE_ORIGIN,
    );
    return NextResponse.redirect(target, 307);
  }

  if (isTranslatedRoute(request.nextUrl.pathname)) {
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
  return response;
}

export const config = {
  // `connect` is the locale-invariant connect-link redirect route handler
  // (src/app/connect/[code]/route.ts) — exclude it like `api` so next-intl
  // doesn't rewrite it into the [locale] tree.
  matcher: ["/((?!api|connect|_next|_vercel|sitemap|ingest|.*\\..*).*)", "/"],
};
