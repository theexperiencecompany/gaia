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
      } catch {
        // Ignore background sync errors to keep UI responsive
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
