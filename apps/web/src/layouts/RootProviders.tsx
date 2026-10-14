"use client";

// Subpath, not the package barrel: the barrel drags recharts + react-markdown +
// react-syntax-highlighter + react-day-picker onto every route (RootProviders is
// global). The heavy OpenUI components load separately in chat. See theme.ts.
import { ThemeProvider } from "@openuidev/react-ui/ThemeProvider";
import dynamic from "next/dynamic";
import type { ReactNode } from "react";

import { gaiaOpenUITheme } from "@/config/openui/theme";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

const LoginModal = dynamic(
  () => import("@/features/auth/components/LoginModal"),
  { ssr: false },
);

/**
 * Root-level client providers shared by every route under [locale].
 * HeroUIProvider avoids remounting per subtree; QueryProvider sits here
 * because the query cache is app-global (`useCurrentUser` reads it above the
 * route-group layouts); LoginModal is a lazy-loaded Zustand-driven singleton.
 * The modal must stay outside any LazyMotionProvider (HeroUI's Modal throws
 * under LazyMotion strict) — root layout has none, so this is safe.
 */
export default function RootProviders({ children }: { children: ReactNode }) {
  return (
    <HeroUIProvider>
      <QueryProvider>
        {/* OpenUI (`@openuidev/react-ui`) components render inside chat and the
            dev playground; ThemeProvider injects the GAIA-mapped `--openui-*`
            tokens and provides the theme context they require. */}
        <ThemeProvider mode="dark" darkTheme={gaiaOpenUITheme}>
          {children}
        </ThemeProvider>
        <LoginModal />
      </QueryProvider>
    </HeroUIProvider>
  );
}
