import { useQueryClient } from "@tanstack/react-query";
import { del } from "idb-keyval";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { useElectron } from "@/hooks/useElectron";
import { resetUser } from "@/lib/analytics";
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

    resetUser();

    // Fallback redirect if authApi.logout doesn't (no logout_url) — in
    // Electron, (landing) has no ElectronRouteGuard to bounce logged-out
    // users, so desktop goes to the desktop login screen instead of "/".
    router.push(isElectron ? "/desktop-login" : "/");
  }, [clearAllStorage, router, isElectron]);

  return { logout };
};
