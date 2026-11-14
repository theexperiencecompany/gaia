import { useEffect, useRef, useState } from "react";
import { create } from "zustand";

import { wsManager } from "@/lib/websocket/WebSocketManager";
import { batchSyncConversations } from "@/services/syncService";

const MIN_SYNC_INTERVAL = 30000; // 30 seconds between syncs

/** The push the server sends after a conversation's list row (title, activity, unread, star) changed. */
export const CONVERSATION_LIST_CHANGED_EVENT = "conversation.list_changed";

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

/** Keep the local conversation cache in sync with the server while enabled: on mount, focus, reconnect and every list push. */
export const useBackgroundSync = (enabled: boolean) => {
  const lastSyncTimeRef = useRef(0);
  const initialSyncCompleted = useSyncStatusStore(
    (state) => state.initialSyncCompleted,
  );
  const setInitialSyncCompleted = useSyncStatusStore(
    (state) => state.setInitialSyncCompleted,
  );
  const setSyncError = useSyncStatusStore((state) => state.setSyncError);
  const [isSyncing, setIsSyncing] = useState(!initialSyncCompleted);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (
      !enabled ||
      typeof window === "undefined" ||
      typeof document === "undefined"
    ) {
      return;
    }

    // Guards the post-await writes below: a sync that resolves after this
    // effect cleaned up must not touch component state. Store flags stay
    // unconditional — they record global sync facts that outlive this component.
    let cancelled = false;

    const runSync = async () => {
      const now = Date.now();
      if (now - lastSyncTimeRef.current < MIN_SYNC_INTERVAL) return;

      try {
        lastSyncTimeRef.current = now;
        setIsSyncing(true);
        setError(null);
        setSyncError(null);
        // Mount, focus, reconnect and pushes all fire with no user action.
        await batchSyncConversations({ background: true });
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to sync conversations";
        console.error("[BackgroundSync] Sync failed:", err);
        setSyncError(errorMessage);
        if (!cancelled) setError(errorMessage);
      } finally {
        if (!cancelled) setIsSyncing(false);
        setInitialSyncCompleted(true);
      }
    };

    // Initial sync on mount
    runSync();

    // A push is never throttled: it means the list changed now. Pushes that land
    // while a sync runs coalesce into one more sync after it.
    let pushSync: Promise<void> | null = null;
    let pushedDuringSync = false;
    const handleListChanged = () => {
      if (pushSync) {
        pushedDuringSync = true;
        return;
      }
      pushSync = (async () => {
        do {
          pushedDuringSync = false;
          await batchSyncConversations({ background: true });
        } while (pushedDuringSync && !cancelled);
      })().finally(() => {
        pushSync = null;
      });
    };

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
    wsManager.on(CONVERSATION_LIST_CHANGED_EVENT, handleListChanged);
    // A socket that dropped may have missed pushes.
    wsManager.onConnect(runSync);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
      wsManager.off(CONVERSATION_LIST_CHANGED_EVENT, handleListChanged);
      wsManager.offConnect(runSync);
    };
  }, [enabled, setInitialSyncCompleted, setSyncError]);

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
