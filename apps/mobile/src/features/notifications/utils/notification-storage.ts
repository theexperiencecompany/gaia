// ============================================================================
// Notification Utilities
// ============================================================================

import * as SecureStore from "expo-secure-store";
import { notificationsApi } from "../api";

const PUSH_TOKEN_KEY = "expo_push_token";

/**
 * Get the stored push token
 */
export async function getStoredPushToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(PUSH_TOKEN_KEY);
  } catch (error) {
    console.error("[Notifications] Failed to get stored push token:", error);
    return null;
  }
}

/**
 * Clear the stored push token
 */
export async function clearStoredPushToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
  } catch (error) {
    console.error("[Notifications] Failed to clear stored push token:", error);
  }
}

/**
 * Unregister device token from backend and clear from storage
 * Call this when user logs out
 */
export async function unregisterDeviceOnLogout(): Promise<void> {
  try {
    const token = await getStoredPushToken();

    if (token) {
      console.log("[Notifications] Unregistering device token on logout");

      // Unregister from backend
      try {
        await notificationsApi.unregisterDeviceToken(token);
        console.log("[Notifications] Device token unregistered from backend");
      } catch (error) {
        console.error(
          "[Notifications] Failed to unregister from backend:",
          error,
        );
        // Continue even if backend call fails
      }

      // Clear from local storage
      await clearStoredPushToken();
      console.log("[Notifications] Cleared stored push token");
    }
  } catch (error) {
    console.error("[Notifications] Error during device unregistration:", error);
  }
}
