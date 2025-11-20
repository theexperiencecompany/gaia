import { useEffect } from "react";
import { wsManager } from "@/lib/websocket";
import { useUser } from "@/features/auth/hooks/useUser";

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
        console.error("NEXT_PUBLIC_API_BASE_URL environment variable not set");
        return;
      }

      const wsUrl =
        apiBaseUrl.replace("http://", "ws://").replace("https://", "wss://") +
        "ws/connect";

      wsManager.configure({ url: wsUrl });
      wsManager.connect();

      return () => {
        wsManager.disconnect();
      };
    }
  }, [user?.email]);

  // Handle page visibility changes
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && user?.email) {
        if (!wsManager.isConnected) {
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
