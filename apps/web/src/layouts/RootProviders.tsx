"use client";

import { ThemeProvider } from "@openuidev/react-ui";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";

import { gaiaOpenUITheme } from "@/config/openui/theme";
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
      {/* OpenUI (`@openuidev/react-ui`) components render inside chat and the
          dev playground; ThemeProvider injects the GAIA-mapped `--openui-*`
          tokens and provides the theme context they require. */}
      <ThemeProvider mode="dark" darkTheme={gaiaOpenUITheme}>
        {children}
      </ThemeProvider>
      <LoginModal />
    </HeroUIProvider>
  );
}
