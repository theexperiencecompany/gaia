import type { ReactNode } from "react";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";

export default function LocaleLandingLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <LandingLayoutShell>{children}</LandingLayoutShell>;
}
