import createMiddleware from "next-intl/middleware";

import { routing } from "./src/i18n/routing";

export default createMiddleware(routing);

export const config = {
  matcher: [
    // Locale-prefixed versions of translated routes only
    "/(de|es|fr|ja|ko|pt-BR)/(compare|alternative-to|learn|for|automate)/:path*",
    "/(de|es|fr|ja|ko|pt-BR)/(compare|alternative-to|learn|for|automate)",
    // English routes (for Accept-Language detection and locale cookie)
    "/compare/:path*",
    "/compare",
    "/alternative-to/:path*",
    "/alternative-to",
    "/learn/:path*",
    "/learn",
    "/for/:path*",
    "/for",
    "/automate/:path*",
    "/automate",
  ],
};
