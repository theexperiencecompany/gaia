"use client";

import { useEffect } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { wsManager } from "@/lib/websocket";

/**
 * Hook to initialize and manage the global WebSocket connection
 * Should be called once at the app level (ProvidersLayout)
 */
export function useWebSocketConnection() {
  const user = useUser();

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

  // Handle page visibility changes
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && user?.email) {
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
  }, [user?.email]);

  return {
    isConnected: wsManager.isConnected,
  };
}
