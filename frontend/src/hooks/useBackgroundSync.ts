import { useEffect } from "react";

import { batchSyncConversations } from "@/services/syncService";

export const useBackgroundSync = () => {
  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    const runSync = async () => {
      try {
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
