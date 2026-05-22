/**
 * Locale-aware navigation helpers (Link, useRouter, usePathname, redirect).
 *
 * These wrap next/navigation to automatically prepend the active locale prefix
 * for non-default locales (e.g. /fr/pricing, /ja/blog).
 *
 * WHEN TO USE THESE:
 *   - SEO / landing / marketing pages under (landing)/ that are crawled in multiple locales
 *   - Any public page where the URL must reflect the user's locale
 *
 * WHEN TO USE next/navigation DIRECTLY:
 *   - The authenticated app under (main)/ — chat, onboarding, settings, todos, etc.
 *   - These routes are not indexed by search engines and always run in the default locale
 *   - Using next/navigation here is simpler and consistent with the rest of the app
 */
import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

export const { Link, redirect, usePathname, useRouter } =
  createNavigation(routing);
