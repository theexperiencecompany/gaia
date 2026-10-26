import type { Metadata } from "next";
import type { ReactNode } from "react";

import MainAppShell from "@/layouts/MainAppShell";

export const dynamic = "force-dynamic";

/** Signed-in app routes are per-user, so none of them belongs in a search index. */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function MainLayout({ children }: { children: ReactNode }) {
  return <MainAppShell>{children}</MainAppShell>;
}
