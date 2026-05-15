import { notFound } from "next/navigation";
import type { ReactNode } from "react";

/**
 * Dev-only routes live under [locale]/dev/. The check is on
 * `process.env.NODE_ENV` which Next.js inlines at build time — production
 * bundles drop the children entirely and render a 404 instead.
 *
 * HeroUIProvider is mounted at the locale root (RootProviders), so dev
 * pages inherit it without re-wrapping here.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return <>{children}</>;
}
