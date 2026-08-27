import { useQueryClient } from "@tanstack/react-query";
import { del } from "idb-keyval";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { useElectron } from "@/hooks/useElectron";
import { ANALYTICS_EVENTS, resetUser, trackEvent } from "@/lib/analytics";
import { db } from "@/lib/db/chatDb";
import { authApi } from "../api/authApi";

export const useLogout = () => {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { isElectron } = useElectron();

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

      const deletePromises: Promise<void>[] = [];
      for (const dbInfo of databases) {
        const name = dbInfo.name;
        if (!name) continue; // Filter out undefined names

        deletePromises.push(
          new Promise<void>((resolve, reject) => {
            const request = indexedDB.deleteDatabase(name);

            request.onerror = () => {
              console.error(`Error deleting database: ${name}`, request.error);
              reject(request.error);
            };

            request.onblocked = () => {
              console.warn(`Blocked deleting database: ${name}`);
              // Still resolve because we tried
              resolve();
            };

            request.onsuccess = () => {
              resolve();
            };
          }),
        );
      }

      await Promise.allSettled(deletePromises);
    } catch (error) {
      console.error("Error deleting IndexedDB databases:", error);
    }
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error("Logout API error:", error);
    }

    await clearAllStorage();

    // Capture before resetting so the event stays attributed to the user
    // who logged out, then reset the PostHog identity.
    trackEvent(ANALYTICS_EVENTS.USER_LOGGED_OUT);
    resetUser();

    // Redirection will be handled by the authApi.logout method
    // but in case it doesn't (for example, if there's no logout_url),
    // we redirect to the post-logout landing. In Electron the marketing
    // homepage lives in the (landing) group, which has no ElectronRouteGuard
    // to bounce logged-out users — so send desktop users straight to the
    // desktop login screen instead of the public landing page.
    router.push(isElectron ? "/desktop-login" : "/");
  }, [clearAllStorage, router, isElectron]);

  return { logout };
};
