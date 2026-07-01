/**
 * Main Window Module
 *
 * Creates the primary application window and manages its
 * visibility lifecycle. The window starts **hidden** and is
 * only shown once the renderer signals readiness via IPC,
 * ensuring a smooth transition from the splash screen.
 *
 * In production the window polls for the embedded Next.js
 * server to become available; in development it polls for
 * the external dev server on `localhost:3000`.
 *
 * @module windows/main
 */

import { join } from "node:path";
import { app, BrowserWindow, type Event, shell } from "electron";
import { getApiOrigin } from "../api-origin";
import { getServerUrl } from "../server";
import { loadAppRoute } from "./load-url";
import { closeSplashWindow } from "./splash";

/**
 * Guard top-level navigation of the main window.
 *
 * The renderer shares the privileged preload bridge, so any XSS or
 * rogue redirect that navigates the window to an attacker origin would
 * hand that origin our IPC surface. We therefore block navigation to any
 * origin outside the app's known-good set (web server + API origin).
 *
 * @param event - The `will-navigate` / `will-redirect` event.
 * @param url - The target URL being navigated to.
 */
function guardNavigation(event: Event, url: string): void {
  // Web server (dev or embedded prod) and API origin are the only
  // origins that may drive the main window — reuse the exact helpers the
  // loader and cookie logic use so this can never drift from them.
  const allowedOrigins = new Set([
    new URL(getServerUrl()).origin,
    new URL(getApiOrigin()).origin,
  ]);

  let targetOrigin: string;
  try {
    targetOrigin = new URL(url).origin;
  } catch {
    event.preventDefault();
    return;
  }

  if (allowedOrigins.has(targetOrigin)) return;

  event.preventDefault();

  if (url.startsWith("https://") || url.startsWith("http://")) {
    shell.openExternal(url);
  }
}

/** Reference to the current main window (if any). */
let mainWindow: BrowserWindow | null = null;

/** Whether the main window has already been shown. */
let windowShown = false;

/** Deep-link URL queued while the window was not yet ready. */
let pendingDeepLink: string | null = null;

/**
 * Get the current main window reference.
 *
 * @returns The main `BrowserWindow`, or `null` if not yet created.
 */
export function getMainWindow(): BrowserWindow | null {
  return mainWindow;
}

/**
 * Whether the main window has been shown (splash already swapped).
 *
 * @returns `true` once {@link showMainWindow} has run for the
 *   currently alive window.
 */
export function isMainWindowShown(): boolean {
  return windowShown;
}

/**
 * Store a deep-link URL to be processed once the window is shown.
 *
 * @param url - The `gaia://…` URL to queue.
 */
export function setPendingDeepLink(url: string | null): void {
  pendingDeepLink = url;
}

/**
 * Retrieve and clear the pending deep-link URL (if any).
 *
 * @returns The queued URL, or `null`.
 */
export function consumePendingDeepLink(): string | null {
  const url = pendingDeepLink;
  pendingDeepLink = null;
  return url;
}

/**
 * Create the main application window.
 *
 * The window is created **hidden** (`show: false`) and starts
 * polling for the appropriate server (production or dev) in the
 * background. Once the server responds and the page loads, the
 * renderer is expected to send a `window-ready` IPC message
 * which triggers {@link showMainWindow}.
 *
 * @param serverReady - Callback returning `true` when the production
 *   server is up. Ignored in development mode.
 */
export async function createMainWindow(
  serverReady: () => boolean,
): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: "#000000",
    icon: app.isPackaged
      ? join(process.resourcesPath, "icons/256x256.png")
      : join(__dirname, "../../resources/icons/256x256.png"),
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Closing the main window must reset the shown flag so a window
  // re-created from the Dock (macOS `activate`) can be shown again —
  // showMainWindow is one-shot per window.
  mainWindow.on("closed", () => {
    mainWindow = null;
    windowShown = false;
  });

  mainWindow.webContents.setWindowOpenHandler((details) => {
    if (
      details.url.startsWith("https://") ||
      details.url.startsWith("http://")
    ) {
      shell.openExternal(details.url);
    }
    return { action: "deny" };
  });

  // Block top-level navigation and redirects to untrusted origins, and
  // forbid embedding webviews — either would expose the preload bridge.
  mainWindow.webContents.on("will-navigate", guardNavigation);
  mainWindow.webContents.on("will-redirect", guardNavigation);
  mainWindow.webContents.on("will-attach-webview", (event) => {
    event.preventDefault();
  });

  loadAppRoute(mainWindow, "/desktop-login", serverReady).catch(console.error);
}

/**
 * Show the main window and close the splash screen.
 *
 * Called when the renderer sends the `window-ready` IPC signal,
 * or by the fallback timeout. Maximises the window for a
 * fullscreen-like experience.
 *
 * @returns The pending deep-link URL that should be processed
 *   after the window is visible, or `null`.
 */
export function showMainWindow(): string | null {
  if (windowShown) return null;
  windowShown = true;

  console.log("[Main] showMainWindow called");

  if (!mainWindow || mainWindow.isDestroyed()) {
    console.log("[Main] Main window not available");
    return null;
  }

  mainWindow.maximize();
  mainWindow.show();
  mainWindow.focus();
  console.log("[Main] Main window shown and focused");

  console.log("[Main] About to close splash window");
  closeSplashWindow();

  return consumePendingDeepLink();
}
