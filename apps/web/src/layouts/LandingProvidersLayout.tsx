"use client";

import { type ReactNode, Suspense } from "react";

import { Toaster } from "@/components/ui/Toaster";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import QueryProvider from "@/layouts/QueryProvider";

/**
 * Lightweight provider tree for landing/marketing pages.
 *
 * HeroUIProvider and LoginModal are mounted once at the locale root
 * (see RootProviders) and are available on every route, so this tree
 * only sets up the bits unique to landing pages.
 *
 * Includes:
 * - QueryProvider: required by marketplace and use-cases detail pages
 * - GlobalAuth: populates the user store so isAuthenticated works
 * - GlobalInterceptor: route-agnostic post-redirect listeners (OAuth toast)
 * - Toaster: toast notifications on interactive landing pages
 *
 * Intentionally excludes (app-only concerns):
 * - useAxiosInterceptor (no background-fetch error toasts for anonymous
 *   visitors — see ProvidersLayout)
 * - useNotifications / useNotificationWebSocket / useWebSocketConnection
 * - GlobalIntegrationModal
 * - ElectronRouteGuard
 * - KeyboardShortcutsProvider
 */
export default function LandingProvidersLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <QueryProvider>
      {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
      <Suspense fallback={<></>}>
        <GlobalAuth />
      </Suspense>
      <GlobalInterceptor />
      <Toaster position="bottom-right" />
      {children}
    </QueryProvider>
  );
}
