"use client";

import dynamic from "next/dynamic";
import { type ReactNode, Suspense } from "react";

import { ElectronRouteGuard } from "@/components/electron/ElectronRouteGuard";
import KeyboardShortcutsProvider from "@/components/providers/KeyboardShortcutsProvider";
import { Toaster } from "@/components/ui/Toaster";
import { useApprovalDecisionWebSocket } from "@/features/chat/hooks/useApprovalDecisionWebSocket";
import { useBgMessageWebSocket } from "@/features/chat/hooks/useBgMessageWebSocket";
import { useExecutorCancelWebSocket } from "@/features/chat/hooks/useExecutorCancelWebSocket";
import { useExecutorStream } from "@/features/chat/hooks/useExecutorStream";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { useAppSessionEnabled } from "@/features/pricing/hooks/useEntitlement";
import { useTodoWorkflowGlobalListener } from "@/features/todo/hooks/useTodoWorkflowGlobalListener";
import { useUpdatesLiveRefresh } from "@/features/updates/hooks/useUpdatesLiveRefresh";

import useAxiosInterceptor from "@/hooks/api/useAxiosInterceptor";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { useWebSocketConnection } from "@/lib/websocket/useWebSocketConnection";

const GlobalIntegrationModal = dynamic(
  () =>
    import("@/features/integrations/components/GlobalIntegrationModal").then(
      (m) => ({ default: m.GlobalIntegrationModal }),
    ),
  { ssr: false },
);

/**
 * The signed-in app's background requests: realtime sockets, updates,
 * executor streams. All of them are paid-only, so they mount only once the
 * plan is read and allows them; an unpaid account on /onboarding fires none.
 */
function PaidSessionEffects() {
  // Initialize global WebSocket connection
  useWebSocketConnection();

  // Refresh the Updates feed and its badge when GAIA tells the user something
  useUpdatesLiveRefresh();

  // Subscribe to background executor completion messages — inserts new
  // bot messages delivered via WebSocket (executor notifications, queued task results)
  useBgMessageWebSocket();

  // Subscribe to queued executor SSE streams for live tool progress
  useExecutorStream();

  // Subscribe to agent-initiated executor cancellations — clears the stuck
  // executor-pending loading indicator and finalizes in-flight tool cards
  useExecutorCancelWebSocket();

  // Subscribe to ledger approval decisions — settles open cards (and raises
  // revoke tombstones) decided anywhere but this tab, with no reload
  useApprovalDecisionWebSocket();

  // Subscribe to workflow generation events — updates todo store globally
  useTodoWorkflowGlobalListener();

  return null;
}

export default function ProvidersLayout({ children }: { children: ReactNode }) {
  const appSessionEnabled = useAppSessionEnabled();

  // App-shell-only API error handling. Surfaces toasts for 5xx/429/403
  // and auto-opens the login modal on 401. Landing pages mount neither.
  useAxiosInterceptor();

  return (
    <>
      {/* Keep Toaster outside LazyMotion: sileo uses motion.* internally. */}
      <Toaster position="top-right" />
      <LazyMotionProvider>
        {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
        <Suspense fallback={<></>}>
          <GlobalAuth />
        </Suspense>
        <GlobalInterceptor />
        {appSessionEnabled && (
          <>
            <PaidSessionEffects />
            <GlobalIntegrationModal />
          </>
        )}
        <ElectronRouteGuard>
          <KeyboardShortcutsProvider>
            {/** biome-ignore lint/complexity/noUselessFragments: needs empty component */}
            <Suspense fallback={<></>}>{children}</Suspense>
          </KeyboardShortcutsProvider>
        </ElectronRouteGuard>
      </LazyMotionProvider>
    </>
  );
}
