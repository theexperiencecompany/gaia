import { useQueryClient } from "@tanstack/react-query";
import { del } from "idb-keyval";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { db } from "@/lib";
import { ANALYTICS_EVENTS, resetUser, trackEvent } from "@/lib/analytics";
import { authApi } from "../api/authApi";

export const useLogout = () => {
  const queryClient = useQueryClient();
  const router = useRouter();

  const clearAllStorage = useCallback(async () => {
    // 1. Close all database connections first
    try {
      db.close(); // If your db has a close method
    } catch (error) {
      console.error("Error closing db:", error);
    }

    // 2. Clear React Query (returns promises)
    await Promise.allSettled([
      queryClient.cancelQueries(), // Cancel in-flight queries first
      queryClient.clear(),
      del("reactQuery"),
    ]);

    // 3. Clear chat database
    try {
      await db.clearAll();
    } catch (error) {
      console.error("Error clearing chat db:", error);
    }

    // 4. Clear synchronous storage
    try {
      sessionStorage.clear();
      localStorage.clear();
    } catch (error) {
      console.error("Error clearing storage:", error);
    }

    // 5. Delete all IndexedDB databases
    try {
      const databases = await indexedDB.databases();

      const deletePromises = databases
        .filter((dbInfo) => dbInfo.name) // Filter out undefined names
        .map(
          (dbInfo) =>
            new Promise<void>((resolve, reject) => {
              const request = indexedDB.deleteDatabase(dbInfo.name!);

              request.onerror = () => {
                console.error(`Error deleting database: ${dbInfo.name}`, request.error);
                reject(request.error);
              };

              request.onblocked = () => {
                console.warn(`Blocked deleting database: ${dbInfo.name}`);
                // Still resolve because we tried
                resolve();
              };

              request.onsuccess = () => {
                resolve();
              };
            }),
        );

      await Promise.allSettled(deletePromises);
    } catch (error) {
      console.error("Error deleting IndexedDB databases:", error);
    }
  }, [queryClient]);

  const logout = useCallback(async () => {
    // Track logout event before clearing storage (so we still have user context)
    trackEvent(ANALYTICS_EVENTS.USER_LOGGED_OUT);

    await clearAllStorage();

    // Reset PostHog user identity
    resetUser();

    try {
      await authApi.logout();
    } catch (error) {
      console.error("Logout API error:", error);
    }

    // Redirection will be handled by the authApi.logout method
    // but in case it doesn't (for example, if there's no logout_url),
    // we redirect to the homepage
    router.push("/");
  }, [clearAllStorage, router]);

  return { logout };
};
