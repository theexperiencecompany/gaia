/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
export const useBackgroundSync = (): {
  isSyncing: boolean;
  error: string | null;
} => ({ isSyncing: false, error: null });

export const useSyncStatus = (): {
  initialSyncCompleted: boolean;
  syncError: string | null;
} => ({ initialSyncCompleted: true, syncError: null });
