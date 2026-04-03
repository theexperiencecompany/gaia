"use client";

import { useEffect, useRef } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { wsManager } from "@/lib/websocket/WebSocketManager";

/**
 * Hook to initialize and manage the global WebSocket connection
 * Should be called once at the app level (ProvidersLayout)
 */
export function useWebSocketConnection() {
  const user = useUser();

  // Keep user email in a ref so the visibility handler always sees the latest
  // value without needing to re-subscribe the event listener
  // (advanced-event-handler-refs pattern).
  const userEmailRef = useRef(user?.email);
  userEmailRef.current = user?.email;

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

      const wsUrl =
        apiBaseUrl.replace("http://", "ws://").replace("https://", "wss://") +
        "ws/connect";

      console.log("[WebSocket] Configuring connection", {
        apiBaseUrl,
        wsUrl,
        userEmail: user.email,
      });

      wsManager.configure({ url: wsUrl });
      wsManager.connect();

      return () => {
        console.log("[WebSocket] Disconnecting due to unmount or user change");
        wsManager.disconnect();
      };
    } else {
      console.log("[WebSocket] Not connecting - no user email available");
    }
  }, [user?.email]);

  // Handle page visibility changes — subscribe once, read latest email from ref
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && userEmailRef.current) {
        if (!wsManager.isConnected) {
          console.log("[WebSocket] Page became visible, reconnecting...");
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
