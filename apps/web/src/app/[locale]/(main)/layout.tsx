import type { Metadata } from "next";
import type { ReactNode } from "react";
import { MainLayoutShell } from "@/components/layouts/MainLayoutShell";

/** The signed-in app: robots.txt keeps crawlers out, and a page reached anyway is never indexed. */
export const dynamic = "force-dynamic";

/** Signed-in app routes are per-user, so none of them belongs in a search index. */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function MainLayout({ children }: { children: ReactNode }) {
  return <MainLayoutShell>{children}</MainLayoutShell>;
}
