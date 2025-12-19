"use client";

import { type ReactNode, Suspense } from "react";

import { ElectronRouteGuard } from "@/components/electron";
import KeyboardShortcutsProvider from "@/components/providers/KeyboardShortcutsProvider";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { Toaster } from "@/components/ui/sonner";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useNotificationWebSocket } from "@/features/notification/hooks/useNotificationWebSocket";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";
import { useWebSocketConnection } from "@/lib/websocket";

export default function ProvidersLayout({ children }: { children: ReactNode }) {
  const { addNotification, updateNotification } = useNotifications({
    limit: 100,
  });

  // Initialize global WebSocket connection
  useWebSocketConnection();

  // Subscribe to notification events
  useNotificationWebSocket({
    onNotification: addNotification,
    onUpdate: updateNotification,
  });

  return (
    <HeroUIProvider>
      <QueryProvider>
        <Suspense fallback={<SuspenseLoader />}>
          <GlobalAuth />
        </Suspense>
        <GlobalInterceptor />
        {/* <HydrationManager /> */}
        <Toaster closeButton richColors position="top-right" theme="dark" />
        <ElectronRouteGuard>
          <KeyboardShortcutsProvider>
            {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
            <Suspense fallback={<></>}>{children}</Suspense>
          </KeyboardShortcutsProvider>
        </ElectronRouteGuard>
      </QueryProvider>
    </HeroUIProvider>
  );
}
