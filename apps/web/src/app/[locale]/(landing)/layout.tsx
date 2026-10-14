import type { ReactNode } from "react";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";
import { configuredInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";

export default function LocaleLandingLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <LandingLayoutShell instanceAuthMode={configuredInstanceAuthMode()}>
      {children}
    </LandingLayoutShell>
  );
}
