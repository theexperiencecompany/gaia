import createMiddleware from "next-intl/middleware";

import { routing } from "./src/i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Match all paths except Next.js internals, static files, and non-page routes
  matcher: ["/((?!api|_next|_vercel|sitemap|ingest|.*\\..*).*)"],
};
