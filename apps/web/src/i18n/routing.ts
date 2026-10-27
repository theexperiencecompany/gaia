import { defineRouting } from "next-intl/routing";

import { defaultLocale, locales } from "./config";

export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: "as-needed",
  // Not HttpOnly on purpose: next-intl rewrites this cookie from document.cookie
  // on client locale switches (navigation/shared/syncLocaleCookie). It holds no
  // secret — only the last locale — so HttpOnly would buy nothing and break that
  // write. Secure + SameSite still apply, and the URL prefix is the source of truth.
  localeCookie: {
    name: "NEXT_LOCALE",
    secure: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
  },
});
