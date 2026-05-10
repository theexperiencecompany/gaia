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
  // Prefer the dedicated Google OAuth endpoint when the API has it deployed;
  // fall back to the WorkOS authkit endpoint with provider rewrite for older
  // API versions. The fallback shows a brief WorkOS "invalid redirect" flash
  // before completing — harmless but visible until the API ships.
  const googleUrl = `${API_BASE_URL}/oauth/login/google/mobile?redirect_uri=${encodeURIComponent(callbackUri)}`;
  const workosUrl = `${API_BASE_URL}/oauth/login/workos/mobile?redirect_uri=${encodeURIComponent(callbackUri)}`;

  try {
    const googleResp = await fetch(googleUrl);
    if (googleResp.ok) {
      const data: LoginUrlResponse = await googleResp.json();
      return data.url;
    }

    const workosResp = await fetch(workosUrl);
    if (!workosResp.ok) {
      throw new Error("Failed to get login URL");
    }
    const data: LoginUrlResponse = await workosResp.json();
    return data.url.replace("provider=authkit", "provider=GoogleOAuth");
  } catch (error) {
    console.error("Error getting login URL:", error);
    throw new Error("Failed to initiate login");
  }
}

/**
 * Starts the OAuth flow and returns the auth token.
 * Returns `null` when the user aborts (cancel/dismiss) — callers should
 * silently ignore that case rather than show an error.
 */
export async function startOAuthFlow(): Promise<string | null> {
  try {
    const authUrl = await getLoginUrl(redirectUri);
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);

    if (result.type === "success" && result.url) {
      const parsed = Linking.parse(result.url);
      const token = parsed.queryParams?.token as string | undefined;

      if (!token) {
        throw new Error("No token received from authentication");
      }
      return token;
    }
    if (result.type === "cancel" || result.type === "dismiss") {
      return null;
    }
    throw new Error("Authentication failed");
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
