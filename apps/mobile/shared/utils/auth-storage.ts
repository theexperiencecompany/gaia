/**
 * Auth Storage Utility
 * Handles secure storage of authentication tokens using Expo SecureStore
 */

import * as SecureStore from "expo-secure-store";

const AUTH_TOKEN_KEY = "gaia_auth_token";
const USER_INFO_KEY = "gaia_user_info";

export interface UserInfo {
  name: string;
  email: string;
  picture?: string;
}

/**
 * Store authentication token securely
 */
export async function storeAuthToken(token: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(AUTH_TOKEN_KEY, token);
  } catch (error) {
    console.error("Failed to store auth token:", error);
    throw new Error("Failed to store authentication token");
  }
}

/**
 * Retrieve authentication token
 */
export async function getAuthToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(AUTH_TOKEN_KEY);
  } catch (error) {
    console.error("Failed to retrieve auth token:", error);
    return null;
  }
}

/**
 * Remove authentication token
 */
export async function removeAuthToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(AUTH_TOKEN_KEY);
  } catch (error) {
    console.error("Failed to remove auth token:", error);
  }
}

/**
 * Store user information
 */
export async function storeUserInfo(userInfo: UserInfo): Promise<void> {
  try {
    await SecureStore.setItemAsync(USER_INFO_KEY, JSON.stringify(userInfo));
  } catch (error) {
    console.error("Failed to store user info:", error);
    throw new Error("Failed to store user information");
  }
}

/**
 * Retrieve user information
 */
export async function getUserInfo(): Promise<UserInfo | null> {
  try {
    const userInfoString = await SecureStore.getItemAsync(USER_INFO_KEY);
    return userInfoString ? JSON.parse(userInfoString) : null;
  } catch (error) {
    console.error("Failed to retrieve user info:", error);
    return null;
  }
}

/**
 * Remove user information
 */
export async function removeUserInfo(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(USER_INFO_KEY);
  } catch (error) {
    console.error("Failed to remove user info:", error);
  }
}

/**
 * Check if user is authenticated
 */
export async function isAuthenticated(): Promise<boolean> {
  const token = await getAuthToken();
  return token !== null;
}

/**
 * Clear all authentication data
 */
export async function clearAuthData(): Promise<void> {
  await removeAuthToken();
  await removeUserInfo();
}
