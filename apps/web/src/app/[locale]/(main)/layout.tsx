import type { Metadata } from "next";
import type { ReactNode } from "react";
import { MainLayoutShell } from "@/components/layouts/MainLayoutShell";

/** The signed-in app: robots.txt keeps crawlers out, and a page reached anyway is never indexed. */
export const dynamic = "force-dynamic";

/**
 * Signed-in app routes are per-user, so none of them belongs in a search index.
 * The app is English-only and React-rendered: a browser auto-translating it
 * swapped the wizard's language mid-flow and breaks React's DOM updates.
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
  other: { google: "notranslate" },
};

export default function MainLayout({ children }: { children: ReactNode }) {
  return <MainLayoutShell>{children}</MainLayoutShell>;
}
