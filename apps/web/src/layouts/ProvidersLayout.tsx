"use client";

import { type ReactNode, Suspense } from "react";

import { ElectronRouteGuard } from "@/components/electron";
import KeyboardShortcutsProvider from "@/components/providers/KeyboardShortcutsProvider";
import { Toaster } from "@/components/ui/Toaster";
import LoginModal from "@/features/auth/components/LoginModal";
import { GlobalIntegrationModal } from "@/features/integrations/components/GlobalIntegrationModal";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useNotificationWebSocket } from "@/features/notification/hooks/useNotificationWebSocket";

import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";
import { useWebSocketConnection } from "@/lib/websocket";

export default function ProvidersLayout({ children }: { children: ReactNode }) {
  // Populate the notification store on app load
  useNotifications({ limit: 100 });

  // Initialize global WebSocket connection
  useWebSocketConnection();

  // Subscribe to notification events — updates the shared store directly
  useNotificationWebSocket();

  return (
    <HeroUIProvider>
      <LazyMotionProvider>
        <QueryProvider>
          {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
          <Suspense fallback={<></>}>
            <GlobalAuth />
          </Suspense>
          <GlobalInterceptor />
          {/* <HydrationManager /> */}
          <Toaster />
          <LoginModal />
          <GlobalIntegrationModal />
          <ElectronRouteGuard>
            <KeyboardShortcutsProvider>
              {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
              <Suspense fallback={<></>}>{children}</Suspense>
            </KeyboardShortcutsProvider>
          </ElectronRouteGuard>
        </QueryProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
