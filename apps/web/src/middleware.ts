import type { NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";

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
  if (isTranslatedRoute(request.nextUrl.pathname)) {
    return intlMiddleware(request);
  }
  // For non-translated routes: still run middleware (needed for [locale]
  // routing) but force default locale — no locale prefix in URL.
  return intlMiddlewareDefaultOnly(request);
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|sitemap|ingest|.*\\..*).*)", "/"],
};
