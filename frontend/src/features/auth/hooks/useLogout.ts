import { useQueryClient } from "@tanstack/react-query";
import { del } from "idb-keyval";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { authApi } from "@/features/auth/api/authApi";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { db } from "@/lib/db/chatDb";

/**
 * Custom hook for handling user logout with complete cleanup
 * Clears React Query cache, persisted cache, user state, and IndexedDB
 */
export const useLogout = () => {
  const { clearUser } = useUserActions();
  const queryClient = useQueryClient();
  const router = useRouter();

  const logout = useCallback(async () => {
    try {
      // Call backend logout endpoint
      await authApi.logout();

      // Clear all React Query cache
      queryClient.clear();

      // Clear persisted cache from IndexedDB
      try {
        await del("reactQuery");
      } catch (error) {
        console.warn("Failed to clear persisted cache:", error);
      }

      // Clear IndexedDB conversations and messages
      try {
        await db.clearAll();
      } catch (error) {
        console.warn("Failed to clear IndexedDB:", error);
      }

      // Also invalidate all queries to ensure fresh data on next login
      await queryClient.invalidateQueries();

      // Clear sessionStorage (including onboarding state)
      try {
        sessionStorage.clear();
      } catch (error) {
        console.warn("Failed to clear sessionStorage:", error);
      }

      // Clear localStorage items related to onboarding
      try {
        // Clear all personalization dismissal keys (for all users)
        Object.keys(localStorage).forEach((key) => {
          if (key.startsWith("personalization-dismissed-")) {
            localStorage.removeItem(key);
          }
        });
        localStorage.removeItem("gaia-onboarding-state"); // In case it was stored there
      } catch (error) {
        console.warn("Failed to clear localStorage items:", error);
      }

      // Clear user state from Zustand store
      clearUser();

      // Navigate to home page
      router.push("/");
    } catch (error) {
      console.error("Error during logout:", error);

      // Even if API call fails, clear local state
      queryClient.clear();

      // Try to clear persisted cache even on error
      try {
        await del("reactQuery");
      } catch (persistError) {
        console.warn("Failed to clear persisted cache on error:", persistError);
      }

      // Clear sessionStorage even on error
      try {
        sessionStorage.clear();
      } catch (sessionError) {
        console.warn("Failed to clear sessionStorage on error:", sessionError);
      }

      // Clear localStorage items even on error
      try {
        localStorage.removeItem("personalization-card-dismissed");
        localStorage.removeItem("gaia-onboarding-state");
      } catch (localError) {
        console.warn(
          "Failed to clear localStorage items on error:",
          localError,
        );
      }

      clearUser();
      router.push("/");
    }
  }, [queryClient, clearUser, router]);

  return { logout };
};
