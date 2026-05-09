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
  return intlMiddlewareDefaultOnly(request);
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|sitemap|ingest|.*\\..*).*)", "/"],
};
