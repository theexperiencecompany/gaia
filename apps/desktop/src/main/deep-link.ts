/**
 * Deep Link Handler Module
 *
 * Processes `gaia://` URLs received from the OS — typically OAuth
 * callbacks triggered after the user authenticates in the system
 * browser.
 *
 * URL format: `gaia://auth/callback?token=<jwt>` (success)
 *             `gaia://auth/callback?error=<message>` (failure)
 *
 * @module deep-link
 */

import { type BrowserWindow, session } from "electron";
import { getServerUrl } from "./server";

/**
 * Derive the API origin from the environment variable.
 *
 * Strips a trailing `/api/v1/` segment so we get the bare origin
 * (e.g. `https://api.heygaia.io`) suitable for cookie storage.
 */
function getApiOrigin(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io"
  ).replace(/\/api\/v1\/?$/, "");
}

/**
 * Handle an incoming `gaia://` deep-link URL.
 *
 * Parses the URL, extracts either a session `token` or an `error`
 * query parameter, and takes the appropriate action:
 *
 * - **Error** — navigates the main window to `/login?error=…`
 * - **Token** — stores a `wos_session` cookie on the API origin
 *   and navigates the main window to `/c` (the main chat view).
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

    const token = urlObj.searchParams.get("token");
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

    if (token) {
      console.log("[Main] Auth token received, storing as cookie");
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
