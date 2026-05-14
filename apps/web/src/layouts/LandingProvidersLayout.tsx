"use client";

import { type ReactNode, Suspense } from "react";

import { Toaster } from "@/components/ui/Toaster";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

/**
 * Lightweight provider tree for landing/marketing pages.
 *
 * Includes only the providers that landing pages actually need:
 * - HeroUIProvider: required for HeroUI components used across landing pages
 * - QueryProvider: required by marketplace and use-cases detail pages
 * - GlobalAuth: populates the user store so isAuthenticated works on landing pages
 * - GlobalInterceptor: sets up axios auth interceptors for API calls
 * - Toaster: required for toast notifications on interactive landing pages
 *
 * LoginModal is mounted per-page on the landing routes that actually trigger it
 * (marketplace/[slug], use-cases/[slug], use-cases listing) instead of globally
 * — keeps the marketing initial bundle leaner and avoids a duplicate mount with
 * the (main) provider tree.
 *
 * Intentionally excludes (app-only concerns):
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
    <HeroUIProvider>
      <QueryProvider>
        {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
        <Suspense fallback={<></>}>
          <GlobalAuth />
        </Suspense>
        <GlobalInterceptor />
        <Toaster position="bottom-right" />
        {children}
      </QueryProvider>
    </HeroUIProvider>
  );
}
