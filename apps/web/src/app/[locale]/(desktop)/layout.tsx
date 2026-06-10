import type { Metadata } from "next";
import type { ReactNode } from "react";

/**
 * Routes in this group are loaded exclusively by the Electron desktop
 * shell's auxiliary windows (assistant popup, wake-word listener).
 * They render no marketing chrome and must never be indexed.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function DesktopLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
