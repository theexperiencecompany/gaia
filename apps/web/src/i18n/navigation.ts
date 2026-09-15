/**
 * Locale-aware navigation helpers (Link, useRouter, usePathname), prepending
 * the active locale prefix for non-default locales (e.g. /fr/pricing).
 *
 * Use these for SEO/landing pages crawled in multiple locales; use
 * next/navigation directly for the authenticated app, which is unindexed and always default-locale.
 */
import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

export const { Link, usePathname, useRouter } = createNavigation(routing);
