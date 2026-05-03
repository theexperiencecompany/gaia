import * as Crypto from "expo-crypto";
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

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function generatePkcePair(): Promise<{
  verifier: string;
  challenge: string;
}> {
  // 32 random bytes -> 43-char base64url verifier (RFC 7636 length range).
  const randomBytes = await Crypto.getRandomBytesAsync(32);
  const verifier = base64UrlEncode(randomBytes);
  const digestB64 = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 },
  );
  const challenge = digestB64
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return { verifier, challenge };
}

export async function getLoginUrl(
  callbackUri: string,
  codeChallenge?: string,
): Promise<string> {
  const params = new URLSearchParams({ redirect_uri: callbackUri });
  if (codeChallenge) params.set("code_challenge", codeChallenge);
  const url = `${API_BASE_URL}/oauth/login/workos/mobile?${params.toString()}`;
  console.log("[Auth] Fetching login URL:", url);
  try {
    const response = await fetch(url);

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
    // PKCE (H11) defends against on-device URL-handler interception. A
    // malicious app registered for our scheme can capture the one-time
    // code but cannot present the verifier we kept locally.
    const { verifier, challenge } = await generatePkcePair();
    const authUrl = await getLoginUrl(redirectUri, challenge);
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);

    if (result.type === "success" && result.url) {
      const parsed = Linking.parse(result.url);
      const code = parsed.queryParams?.code as string | undefined;

      if (!code) {
        throw new Error("No code received from authentication");
      }

      const exchangeRes = await fetch(`${API_BASE_URL}/oauth/exchange-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, code_verifier: verifier }),
      });

      if (!exchangeRes.ok) {
        throw new Error("Failed to exchange authentication code");
      }

      const data = (await exchangeRes.json()) as { token?: string };
      if (!data.token) {
        throw new Error("No token in exchange response");
      }
      return data.token;
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
