import type { ReactNode } from "react";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";
import { isSelfhostWeb } from "@/features/auth/api/serverSetupStatusApi";

export default function LocaleLandingLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <LandingLayoutShell selfhost={isSelfhostWeb()}>
      {children}
    </LandingLayoutShell>
  );
}
