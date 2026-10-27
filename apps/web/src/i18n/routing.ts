import { defineRouting } from "next-intl/routing";

import { defaultLocale, locales } from "./config";

export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: "as-needed",
  // Not HttpOnly: next-intl rewrites this cookie from document.cookie on locale
  // switch, and it holds only the last locale — the URL prefix is authoritative.
  localeCookie: {
    name: "NEXT_LOCALE",
    secure: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
  },
});
