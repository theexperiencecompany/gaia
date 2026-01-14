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
 * Clear the stored push token and registration flag
 */
export async function clearStoredPushToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
    await SecureStore.deleteItemAsync("expo_push_token_registered");
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

      // Unregister from backend with retry logic
      const MAX_RETRIES = 3;
      let lastError: unknown = null;

      for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
          await notificationsApi.unregisterDeviceToken(token);
          console.log("[Notifications] Device token unregistered from backend");
          lastError = null;
          break;
        } catch (error) {
          lastError = error;
          console.warn(
            `[Notifications] Unregister attempt ${attempt}/${MAX_RETRIES} failed:`,
            error,
          );
          if (attempt < MAX_RETRIES) {
            await new Promise((r) => setTimeout(r, 500 * attempt)); // Backoff
          }
        }
      }

      if (lastError) {
        // CRITICAL: Token remains in DB - user may still receive notifications
        const maskedToken =
          token.length > 24
            ? `${token.slice(0, 20)}...${token.slice(-4)}`
            : "***";
        console.error(
          "[Notifications] CRITICAL: Failed to unregister device after retries. Token may persist:",
          maskedToken,
        );
        // Continue with logout - don't block user
      }

      // Clear from local storage
      await clearStoredPushToken();
      console.log("[Notifications] Cleared stored push token");
    }
  } catch (error) {
    console.error("[Notifications] Error during device unregistration:", error);
  }
}
