import { defineRouting } from "next-intl/routing";

import { defaultLocale, locales } from "./config";

export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: "as-needed",
  // Not HttpOnly: next-intl rewrites this cookie from document.cookie on client
  // locale switches (navigation/shared/syncLocaleCookie), so its config omits the flag.
  localeCookie: { secure: true },
});
