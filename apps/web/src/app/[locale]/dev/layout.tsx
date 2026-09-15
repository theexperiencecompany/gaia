import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/Toaster";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

/**
 * Dev-only routes live under [locale]/dev/. The check is on
 * `process.env.NODE_ENV` which Next.js inlines at build time — production
 * bundles drop the children entirely and render a 404 instead.
 *
 * HeroUIProvider and QueryProvider are mounted at the locale root
 * (RootProviders), so dev pages inherit them without re-wrapping here.
 * LazyMotion is added because dev pages render real app components that
 * animate via `motion/react-m`'s `<m.*>`, which stay invisible (stuck at
 * their `initial` props) without it.
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
    <>
      <LazyMotionProvider>{children}</LazyMotionProvider>
      <Toaster position="top-right" />
    </>
  );
}
