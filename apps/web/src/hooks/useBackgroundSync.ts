import { useEffect, useRef } from "react";

import { batchSyncConversations } from "@/services/syncService";

const MIN_SYNC_INTERVAL = 30000; // 30 seconds between syncs

export const useBackgroundSync = () => {
  const lastSyncTimeRef = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    const runSync = async () => {
      const now = Date.now();
      if (now - lastSyncTimeRef.current < MIN_SYNC_INTERVAL) return;

      try {
        lastSyncTimeRef.current = now;
        await batchSyncConversations();
      } catch (error) {
        // Log error for debugging but don't show to user
        console.error("[BackgroundSync] Sync failed:", error);
      }
    };

    runSync();

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        runSync();
      }
    };

    const handleOnline = () => {
      runSync();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleOnline);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
    };
  }, []);
};
