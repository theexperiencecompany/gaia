import { useEffect, useRef, useState } from "react";

import { batchSyncConversations } from "@/services/syncService";

const MIN_SYNC_INTERVAL = 30000; // 30 seconds between syncs
const PERIODIC_SYNC_INTERVAL = 10 * 60 * 1000; // 10 minutes

// Track if initial sync has completed (shared across hook instances)
let initialSyncCompleted = false;

export const useBackgroundSync = () => {
  const lastSyncTimeRef = useRef(0);
  const [isSyncing, setIsSyncing] = useState(!initialSyncCompleted);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    const runSync = async () => {
      const now = Date.now();
      if (now - lastSyncTimeRef.current < MIN_SYNC_INTERVAL) return;

      try {
        lastSyncTimeRef.current = now;
        setIsSyncing(true);
        await batchSyncConversations();
      } catch (error) {
        // Log error for debugging but don't show to user
        console.error("[BackgroundSync] Sync failed:", error);
      } finally {
        setIsSyncing(false);
        initialSyncCompleted = true;
      }
    };

    // Initial sync on mount
    runSync();

    // Periodic sync every 10 minutes
    const intervalId = setInterval(runSync, PERIODIC_SYNC_INTERVAL);

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
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
    };
  }, []);

  return { isSyncing };
};

// Hook to check sync status without triggering sync
export const useSyncStatus = () => {
  return { initialSyncCompleted };
};
