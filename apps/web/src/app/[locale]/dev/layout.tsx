import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/Toaster";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

/**
 * Dev-only routes live under [locale]/dev/, gated on build-time NODE_ENV.
 *
 * Production inlines the check and drops the children, 404-ing instead.
 * HeroUIProvider/QueryProvider come from the locale root already; LazyMotion
 * is required for dev pages' `motion/react-m` `<m.*>` to animate; Toaster is
 * mounted here too since /dev is a sibling of (main)/(landing), which own theirs.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return (
    <>
      <LazyMotionProvider>{children}</LazyMotionProvider>
      <Toaster position="top-right" />
    </>
  );
}
