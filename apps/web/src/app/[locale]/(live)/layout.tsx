import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/Toaster";

/**
 * The full-page live browser a bot link (or the web card's "open") lands on.
 * The link's code or token is the authority, so no web session or app chrome;
 * a capability URL must never be indexed. Toaster: the decision's failure
 * toast, since this group sits outside (main)/(landing), which own theirs.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Live browser",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function LiveLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <Toaster position="top-center" />
    </>
  );
}
