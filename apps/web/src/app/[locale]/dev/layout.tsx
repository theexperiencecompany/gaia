import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/Toaster";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import QueryProvider from "@/layouts/QueryProvider";

/**
 * Dev-only routes live under [locale]/dev/. The check is on
 * `process.env.NODE_ENV` which Next.js inlines at build time — production
 * bundles drop the children entirely and render a 404 instead.
 *
 * HeroUIProvider is mounted at the locale root (RootProviders), so dev
 * pages inherit it without re-wrapping here. QueryProvider is NOT — it lives
 * in the authenticated (main) layout, which /dev sits outside of — so we add
 * it here, since dev pages render real app components (chat bubbles, link
 * previews via useUrlMetadata) that depend on react-query. LazyMotion is added
 * for the same reason — real components animate via `motion/react-m`'s `<m.*>`,
 * which stay invisible (stuck at their `initial` props) without it.
 *
 * The (main)/(landing) provider layouts also own the app's Toaster, but /dev
 * is a sibling segment — so we mount one here too, for the toast playground
 * and any dev page that fires toasts.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return (
    <QueryProvider>
      <LazyMotionProvider>{children}</LazyMotionProvider>
      <Toaster position="top-right" />
    </QueryProvider>
  );
}
