"use client";

import dynamic from "next/dynamic";
import { type ReactNode, Suspense } from "react";

import { ElectronRouteGuard } from "@/components/electron/ElectronRouteGuard";
import KeyboardShortcutsProvider from "@/components/providers/KeyboardShortcutsProvider";
import { Toaster } from "@/components/ui/Toaster";
import { useBgMessageWebSocket } from "@/features/chat/hooks/useBgMessageWebSocket";
import { useExecutorStream } from "@/features/chat/hooks/useExecutorStream";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useNotificationWebSocket } from "@/features/notification/hooks/useNotificationWebSocket";
import { useTodoWorkflowGlobalListener } from "@/features/todo/hooks/useTodoWorkflowGlobalListener";

import useAxiosInterceptor from "@/hooks/api/useAxiosInterceptor";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import QueryProvider from "@/layouts/QueryProvider";
import { useWebSocketConnection } from "@/lib/websocket/useWebSocketConnection";

const GlobalIntegrationModal = dynamic(
  () =>
    import("@/features/integrations/components/GlobalIntegrationModal").then(
      (m) => ({ default: m.GlobalIntegrationModal }),
    ),
  { ssr: false },
);

export default function ProvidersLayout({ children }: { children: ReactNode }) {
  // Populate the notification store on app load
  useNotifications({ limit: 100 });

  // Initialize global WebSocket connection
  useWebSocketConnection();

  // Subscribe to notification events — updates the shared store directly
  useNotificationWebSocket();

  // Subscribe to background executor completion messages — inserts new
  // bot messages delivered via WebSocket (executor notifications, queued task results)
  useBgMessageWebSocket();

  // Subscribe to queued executor SSE streams for live tool progress
  useExecutorStream();

  // Subscribe to workflow generation events — updates todo store globally
  useTodoWorkflowGlobalListener();

  // App-shell-only API error handling. Surfaces toasts for 5xx/429/403
  // and auto-opens the login modal on 401. Landing pages mount neither.
  useAxiosInterceptor();

  return (
    <>
      {/* Keep Toaster outside LazyMotion: sileo uses motion.* internally. */}
      <Toaster position="top-right" />
      <LazyMotionProvider>
        <QueryProvider>
          {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
          <Suspense fallback={<></>}>
            <GlobalAuth />
          </Suspense>
          <GlobalInterceptor />
          <GlobalIntegrationModal />
          <ElectronRouteGuard>
            <KeyboardShortcutsProvider>
              {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
              <Suspense fallback={<></>}>{children}</Suspense>
            </KeyboardShortcutsProvider>
          </ElectronRouteGuard>
        </QueryProvider>
      </LazyMotionProvider>
    </>
  );
}
