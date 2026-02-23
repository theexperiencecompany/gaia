import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { API_BASE_URL } from "../../../lib/constants";

WebBrowser.maybeCompleteAuthSession();

const redirectUri = Linking.createURL("auth/callback");

export interface LoginUrlResponse {
  url: string;
}

export interface UserInfoResponse {
  name: string;
  email: string;
  picture?: string;
  user_id?: string;
}

export async function getLoginUrl(callbackUri: string): Promise<string> {
  try {
    const response = await fetch(
      `${API_BASE_URL}/oauth/login/workos/mobile?redirect_uri=${encodeURIComponent(callbackUri)}`,
    );

    if (!response.ok) {
      throw new Error("Failed to get login URL");
    }

    const data: LoginUrlResponse = await response.json();
    return data.url;
  } catch (error) {
    console.error("Error getting login URL:", error);
    throw new Error("Failed to initiate login");
  }
}

export async function startOAuthFlow(): Promise<string> {
  try {
    const authUrl = await getLoginUrl(redirectUri);
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);

    if (result.type === "success" && result.url) {
      const url = new URL(result.url);
      const token = url.searchParams.get("token");

      if (!token) {
        throw new Error("No token received from authentication");
      }
      return token;
    } else if (result.type === "cancel") {
      throw new Error("Authentication was cancelled");
    } else {
      throw new Error("Authentication failed");
    }
  } catch (error) {
    console.error("OAuth flow error:", error);
    throw error;
  }
}

export async function fetchUserInfo(token: string): Promise<UserInfoResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/user/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      throw new Error("Failed to fetch user info");
    }

    const data = await response.json();
    return {
      name: data.name || "",
      email: data.email || "",
      picture: data.picture,
      user_id: data.user_id,
    };
  } catch (error) {
    console.error("Error fetching user info:", error);
    throw new Error("Failed to fetch user information");
  }
}

export async function logout(token: string): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/oauth/logout`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  } catch (error) {
    console.error("Error during logout:", error);
  }
}

export const authApi = {
  getLoginUrl,
  startOAuthFlow,
  fetchUserInfo,
  logout,
};
