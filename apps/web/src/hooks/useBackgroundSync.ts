import { useEffect, useRef, useState } from "react";
import { create } from "zustand";

import { batchSyncConversations } from "@/services/syncService";

const MIN_SYNC_INTERVAL = 30000; // 30 seconds between syncs
const PERIODIC_SYNC_INTERVAL = 10 * 60 * 1000; // 10 minutes

// Tiny Zustand store for reactive sync status
interface SyncStatusState {
  initialSyncCompleted: boolean;
  syncError: string | null;
  setInitialSyncCompleted: (completed: boolean) => void;
  setSyncError: (error: string | null) => void;
}

const useSyncStatusStore = create<SyncStatusState>((set) => ({
  initialSyncCompleted: false,
  syncError: null,
  setInitialSyncCompleted: (completed) =>
    set({ initialSyncCompleted: completed }),
  setSyncError: (error) => set({ syncError: error }),
}));

export const useBackgroundSync = () => {
  const lastSyncTimeRef = useRef(0);
  const { initialSyncCompleted, setInitialSyncCompleted, setSyncError } =
    useSyncStatusStore();
  const [isSyncing, setIsSyncing] = useState(!initialSyncCompleted);
  const [error, setError] = useState<string | null>(null);

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
        setError(null);
        setSyncError(null);
        await batchSyncConversations();
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to sync conversations";
        console.error("[BackgroundSync] Sync failed:", err);
        setSyncError(errorMessage);
        setError(errorMessage);
      } finally {
        setIsSyncing(false);
        setInitialSyncCompleted(true);
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
  }, [setInitialSyncCompleted, setSyncError]);

  return { isSyncing, error };
};

// Hook to check sync status without triggering sync - now reactive via Zustand
export const useSyncStatus = () => {
  const initialSyncCompleted = useSyncStatusStore(
    (state) => state.initialSyncCompleted,
  );
  const syncError = useSyncStatusStore((state) => state.syncError);
  return { initialSyncCompleted, syncError };
};
