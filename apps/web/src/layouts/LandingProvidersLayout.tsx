"use client";

import { type ReactNode, Suspense } from "react";

import { Toaster } from "@/components/ui/Toaster";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";

/**
 * Lightweight provider tree for landing/marketing pages — HeroUIProvider,
 * QueryProvider and LoginModal are already mounted once at the locale root
 * (RootProviders), so this only adds GlobalAuth, GlobalInterceptor, and
 * Toaster. Intentionally excludes app-only concerns: interceptor toasts,
 * notifications/websocket, GlobalIntegrationModal, ElectronRouteGuard, KeyboardShortcutsProvider.
 */
export default function LandingProvidersLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <>
      {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
      <Suspense fallback={<></>}>
        <GlobalAuth />
      </Suspense>
      {/* GlobalInterceptor reads useSearchParams() (via useOAuthSuccessToast) —
          it MUST be inside a Suspense boundary, otherwise it deopts the whole
          statically-generated page to client-side rendering (the hero + every
          section vanish from the SSR HTML, killing LCP). */}
      <Suspense fallback={null}>
        <GlobalInterceptor />
      </Suspense>
      <Toaster position="bottom-right" />
      {children}
    </>
  );
}
