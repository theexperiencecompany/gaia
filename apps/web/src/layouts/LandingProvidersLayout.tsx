"use client";

import dynamic from "next/dynamic";
import { type ReactNode, Suspense } from "react";

import { Toaster } from "@/components/ui/Toaster";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

const LoginModal = dynamic(
  () => import("@/features/auth/components/LoginModal"),
  { ssr: false },
);

/**
 * Lightweight provider tree for landing/marketing pages.
 *
 * Includes only the providers that landing pages actually need:
 * - HeroUIProvider: required for HeroUI components used across landing pages
 * - QueryProvider: required by marketplace and use-cases detail pages
 * - GlobalAuth: populates the user store so isAuthenticated works on landing pages
 * - GlobalInterceptor: route-agnostic post-redirect listeners (OAuth toast)
 * - LoginModal: opened by useAuth() from any landing page (marketplace,
 *   use-cases, etc.); lazy-loaded so it stays out of the initial bundle
 * - Toaster: required for toast notifications on interactive landing pages
 *
 * Landing pages and (main) pages never share a layout (route groups are
 * mutually exclusive), so mounting LoginModal here does not duplicate the
 * mount in ProvidersLayout.
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
        <LoginModal />
        {children}
      </QueryProvider>
    </HeroUIProvider>
  );
}
