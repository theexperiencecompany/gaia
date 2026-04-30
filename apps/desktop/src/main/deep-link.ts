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
 * headers).
 *
 * @module deep-link
 */

import { type BrowserWindow, session } from "electron";
import { getServerUrl } from "./server";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io/api/v1";

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
      const token = await exchangeCode(code);
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
