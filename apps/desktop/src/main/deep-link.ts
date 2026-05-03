/**
 * Deep Link Handler Module
 *
 * Processes `gaia://` URLs received from the OS — typically OAuth
 * callbacks triggered after the user authenticates in the system
 * browser.
 *
 * URL format: `gaia://auth/callback?code=<opaque>` (success)
 *             `gaia://auth/callback?error=<message>` (failure)
 *
 * The one-time `code` is exchanged for the sealed session via a POST
 * to `/oauth/exchange-code` so the token never appears in the URL
 * (and therefore never leaks into logs, APM breadcrumbs, or Referer
 * headers). PKCE (RFC 7636) is layered on top: ``preparePkce`` is
 * called by the renderer before opening the system browser, the
 * verifier is held in main-process memory, and the deep-link handler
 * presents it on the exchange so a malicious app that intercepts the
 * `gaia://` redirect cannot complete the swap.
 *
 * @module deep-link
 */

import { createHash, randomBytes } from "node:crypto";
import { type BrowserWindow, session } from "electron";
import { getServerUrl } from "./server";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io/api/v1";

let pendingCodeVerifier: string | null = null;

function base64UrlEncode(buffer: Buffer): string {
  return buffer
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Generate a fresh PKCE verifier/challenge pair for a desktop login.
 *
 * The verifier is held in main-process memory until the matching
 * deep-link callback consumes it. Calling this again before that
 * callback overwrites the prior verifier — a stale browser tab from
 * a previous attempt will fail the exchange, which is the desired
 * behaviour.
 *
 * @returns The base64url-encoded SHA-256 challenge to put in the
 *   `?code_challenge=` query parameter on the login URL.
 */
export function preparePkce(): string {
  const verifier = base64UrlEncode(randomBytes(32));
  const challenge = base64UrlEncode(
    createHash("sha256").update(verifier).digest(),
  );
  pendingCodeVerifier = verifier;
  return challenge;
}

function consumePkceVerifier(): string | null {
  const verifier = pendingCodeVerifier;
  pendingCodeVerifier = null;
  return verifier;
}

/**
 * Derive the API origin from the environment variable.
 *
 * Strips a trailing `/api/v1/` segment so we get the bare origin
 * (e.g. `https://api.heygaia.io`) suitable for cookie storage.
 */
function getApiOrigin(): string {
  return API_BASE_URL.replace(/\/api\/v1\/?$/, "");
}

/**
 * Exchange a one-time code for the sealed WorkOS session token.
 *
 * POSTs the code to /oauth/exchange-code and returns the token string,
 * or null on failure.
 */
async function exchangeCode(
  code: string,
  codeVerifier?: string,
): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/oauth/exchange-code`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, code_verifier: codeVerifier ?? null }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { token?: string };
    return data.token ?? null;
  } catch {
    return null;
  }
}

/**
 * Handle an incoming `gaia://` deep-link URL.
 *
 * Parses the URL, extracts either a one-time `code` or an `error`
 * query parameter, and takes the appropriate action:
 *
 * - **Error** — navigates the main window to `/login?error=…`
 * - **Code** — POSTs the code to `/oauth/exchange-code`, stores the
 *   returned `wos_session` cookie, then navigates to `/c`.
 *
 * @param url - The full `gaia://…` URL received from the OS.
 * @param mainWindow - The main BrowserWindow to navigate.
 */
export async function handleDeepLink(
  url: string,
  mainWindow: BrowserWindow | null,
): Promise<void> {
  console.log("[Main] Deep link received:", url);

  try {
    const urlObj = new URL(url);

    if (urlObj.hostname !== "auth" || urlObj.pathname !== "/callback") return;

    const code = urlObj.searchParams.get("code");
    const error = urlObj.searchParams.get("error");

    if (error) {
      console.log("[Main] Auth error:", error);
      if (mainWindow && !mainWindow.isDestroyed()) {
        const serverUrl = getServerUrl();
        mainWindow.loadURL(
          `${serverUrl}/login?error=${encodeURIComponent(error)}`,
        );
      }
      return;
    }

    if (code) {
      console.log("[Main] Auth code received, exchanging for session token");
      const verifier = consumePkceVerifier();
      const token = await exchangeCode(code, verifier ?? undefined);
      if (!token) {
        console.error("[Main] Failed to exchange code for token");
        if (mainWindow && !mainWindow.isDestroyed()) {
          const serverUrl = getServerUrl();
          mainWindow.loadURL(`${serverUrl}/login?error=exchange_failed`);
        }
        return;
      }

      if (mainWindow && !mainWindow.isDestroyed()) {
        const apiOrigin = getApiOrigin();
        await session.defaultSession.cookies.set({
          url: apiOrigin,
          name: "wos_session",
          value: token,
          httpOnly: true,
          secure: true,
          sameSite: "no_restriction",
          expirationDate: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 7, // 7 days
        });

        // Notify the renderer so it can show a redirecting spinner
        mainWindow.webContents.send("auth-redirecting");

        // Brief pause to let the spinner render before navigating away
        await new Promise((resolve) => setTimeout(resolve, 1200));

        const serverUrl = getServerUrl();
        if (!mainWindow.isDestroyed()) {
          mainWindow.loadURL(`${serverUrl}/c`);
        }
      }
    }
  } catch (err) {
    console.error("[Main] Failed to parse deep link:", err);
  }
}
