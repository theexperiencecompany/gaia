import type { ReactNode } from "react";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";
import { isSelfhostWeb } from "@/lib/selfhost";

/** The public site's noindex pages (sign-in, checkout, share cards): its chrome, without the Organization and WebSite schema meant for indexed pages. */
export default function UnindexedLayout({ children }: { children: ReactNode }) {
  return (
    <LandingLayoutShell selfhost={isSelfhostWeb()}>
      {children}
    </LandingLayoutShell>
  );
}
