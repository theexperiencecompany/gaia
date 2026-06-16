import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/Toaster";

/**
 * Dev-only routes live under [locale]/dev/. The check is on
 * `process.env.NODE_ENV` which Next.js inlines at build time — production
 * bundles drop the children entirely and render a 404 instead.
 *
 * HeroUIProvider is mounted at the locale root (RootProviders), so dev
 * pages inherit it without re-wrapping here. The (main)/(landing) provider
 * layouts own the app's Toaster, but /dev is a sibling segment — so we mount
 * one here too, for the toast playground and any dev page that fires toasts.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return (
    <>
      {children}
      <Toaster position="top-right" />
    </>
  );
}
