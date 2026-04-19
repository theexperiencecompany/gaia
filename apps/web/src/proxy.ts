import type { NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";
import { createLLmsTxt, isLLMsTxtPath } from "next-llms-txt";

import { routing } from "./i18n/routing";

const { GET: handleLLmsTxt } = createLLmsTxt({
  autoDiscovery: {
    appDir: "src/app/[locale]/(landing)",
    rootDir: process.cwd(),
  },
});

// Routes that have actual translations — only these get locale-prefixed URLs
const translatedPrefixes = [
  "/learn",
  "/automate",
  "/compare",
  "/alternative-to",
  "/for",
];

function isTranslatedRoute(pathname: string): boolean {
  // Strip locale prefix if present (e.g. /de/learn → /learn)
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

export default async function proxy(request: NextRequest) {
  if (isLLMsTxtPath(request.nextUrl.pathname)) {
    return await handleLLmsTxt(request);
  }
  if (isTranslatedRoute(request.nextUrl.pathname)) {
    return intlMiddleware(request);
  }
  // For non-translated routes: still run middleware (needed for [locale] routing)
  // but force default locale — no locale prefix in URL
  return intlMiddlewareDefaultOnly(request);
}

export const config = {
  matcher: [
    "/((?!api|_next|_vercel|sitemap|ingest|.*\\..*).*)",
    "/(.*\\.html\\.md)",
    "/",
  ],
};
