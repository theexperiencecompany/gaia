"use client";

import dynamic from "next/dynamic";
import type { ReactNode } from "react";

import { HeroUIProvider } from "@/layouts/HeroUIProvider";

const LoginModal = dynamic(
  () => import("@/features/auth/components/LoginModal"),
  { ssr: false },
);

/**
 * Root-level client providers shared by every route under [locale].
 *
 * HeroUIProvider lives here so HeroUI components work in any route group
 * without each subtree re-mounting it. LoginModal also lives here — it's
 * a singleton driven by a Zustand store, so one mount is enough for the
 * whole app; lazy-loaded so it stays out of the initial bundle.
 *
 * The modal must sit OUTSIDE any LazyMotionProvider (HeroUI's Modal
 * imports the full `motion` API and throws under LazyMotion strict).
 * Root layout has no LazyMotionProvider, so this is naturally safe.
 */
export default function RootProviders({ children }: { children: ReactNode }) {
  return (
    <HeroUIProvider>
      {children}
      <LoginModal />
    </HeroUIProvider>
  );
}
