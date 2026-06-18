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
import { IPC } from "../ipc-channels";
import { getApiOrigin, isApiOriginSecure } from "./api-origin";
import { getServerUrl } from "./server";

/** Pause after storing the session cookie so the renderer's redirect
 * spinner paints before the main window navigates away. */
const AUTH_SPINNER_DELAY_MS = 1200;

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
    if (!mainWindow || mainWindow.isDestroyed()) return;

    const token = urlObj.searchParams.get("token");
    const error = urlObj.searchParams.get("error");

    if (error) {
      console.log("[Main] Auth error:", error);
      const serverUrl = getServerUrl();
      mainWindow.loadURL(
        `${serverUrl}/login?error=${encodeURIComponent(error)}`,
      );
      return;
    }

    if (token) {
      await storeSessionAndRedirect(token, mainWindow);
    }
  } catch (err) {
    console.error("[Main] Failed to parse deep link:", err);
  }
}

/**
 * Store the session cookie on the API origin, flash the redirect spinner,
 * then navigate the main window to the chat view. The window can be torn
 * down during the spinner pause, so re-check before navigating.
 */
async function storeSessionAndRedirect(
  token: string,
  mainWindow: BrowserWindow,
): Promise<void> {
  console.log("[Main] Auth token received, storing as cookie");

  const apiOrigin = getApiOrigin();
  const secure = isApiOriginSecure();
  await session.defaultSession.cookies.set({
    url: apiOrigin,
    name: "wos_session",
    value: token,
    httpOnly: true,
    // SameSite=None requires Secure; over http (localhost dev) the
    // renderer and API are same-site anyway, so Lax suffices.
    secure,
    sameSite: secure ? "no_restriction" : "lax",
    expirationDate: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 7, // 7 days
  });

  // Notify the renderer so it can show a redirecting spinner.
  mainWindow.webContents.send(IPC.authRedirecting);

  // Brief pause to let the spinner render before navigating away.
  await new Promise((resolve) => setTimeout(resolve, AUTH_SPINNER_DELAY_MS));

  const serverUrl = getServerUrl();
  if (!mainWindow.isDestroyed()) {
    mainWindow.loadURL(`${serverUrl}/c`);
  }
}
