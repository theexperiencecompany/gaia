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
import { app, BrowserWindow, shell } from "electron";
import { loadAppRoute } from "./load-url";
import { closeSplashWindow } from "./splash";

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
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
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
