"use client";

import { useEffect, useRef } from "react";

import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { wsManager } from "@/lib/websocket/WebSocketManager";

/**
 * Hook to initialize and manage the global WebSocket connection
 * Should be called once at the app level (ProvidersLayout)
 */
export function useWebSocketConnection() {
  const user = useCurrentUser();

  // Keep user email in a ref so the visibility handler always sees the latest
  // value without needing to re-subscribe the event listener
  // (advanced-event-handler-refs pattern).
  const userEmailRef = useRef(user?.email);
  useEffect(() => {
    userEmailRef.current = user?.email;
  });

  // Initialize WebSocket connection
  useEffect(() => {
    if (user?.email) {
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      if (!apiBaseUrl) {
        console.error(
          "[WebSocket] NEXT_PUBLIC_API_BASE_URL environment variable not set",
        );
        return;
      }

      // The base may be same-origin ("/api/v1/" on self-host), so resolve it
      // against the page before switching the scheme to ws/wss.
      const wsUrl = new URL(
        "ws/connect",
        new URL(apiBaseUrl, window.location.href),
      );
      wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";

      wsManager.configure({ url: wsUrl.href });
      wsManager.connect();

      return () => {
        wsManager.disconnect();
      };
    }
    // No signed-in user: nothing to connect, so no cleanup either.
    return undefined;
  }, [user?.email]);

  // Handle page visibility changes — subscribe once, read latest email from ref
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && userEmailRef.current) {
        if (!wsManager.isConnected) {
          wsManager.connect();
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return {
    isConnected: wsManager.isConnected,
  };
}
