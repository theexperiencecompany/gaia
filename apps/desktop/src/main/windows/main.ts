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
import { app, BrowserWindow, type Event, screen, shell } from "electron";
import { getApiOrigin } from "../api-origin";
import { getServerUrl } from "../server";
import { loadAppRoute } from "./load-url";
import { MAIN_NORMAL_WIDTH, resolveNormalBounds } from "./loader-geometry";
import { classifyNavigation } from "./navigation-policy";
import { closeSplashWindow, getLoaderBounds } from "./splash";

/**
 * Guard top-level navigation of the main window. The renderer shares the
 * privileged preload bridge, so an XSS or rogue redirect to an attacker origin
 * would hand that origin our IPC surface — block navigation outside the app's
 * known-good origins (web server + API origin).
 */
function guardNavigation(event: Event, url: string): void {
  // Web server (dev or embedded prod) and API origin are the only
  // origins that may drive the main window — reuse the exact helpers the
  // loader and cookie logic use so this can never drift from them.
  const allowedOrigins = new Set([
    new URL(getServerUrl()).origin,
    new URL(getApiOrigin()).origin,
  ]);

  const decision = classifyNavigation(url, allowedOrigins);
  if (decision === "allow") return;

  event.preventDefault();

  if (decision === "open-external") {
    shell.openExternal(url).catch((err) => {
      console.error("[Main] Failed to open external URL:", err);
    });
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
 * Create the main application window. Created **hidden** (`show: false`) and
 * polls for the appropriate server (prod or dev, `serverReady` ignored in dev)
 * in the background; once it responds and the page loads, the renderer sends
 * `window-ready`, which triggers {@link showMainWindow}.
 */
export async function createMainWindow(
  serverReady: () => boolean,
): Promise<void> {
  // Start at the splash loader's centered bounds so the reveal is a
  // scale-up from exactly where the loader was (see showMainWindow).
  const { x, y, width, height } = getLoaderBounds();

  mainWindow = new BrowserWindow({
    x,
    y,
    width,
    height,
    minWidth: 640,
    minHeight: 400,
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
 * or by the fallback timeout. The window was created at the splash
 * loader's small centered bounds, so it shows at exactly the loader's
 * spot (no jump), the splash closes, and then it maximises — macOS
 * animates the zoom, which reads as the loader scaling up into the
 * full app. `maximize()` runs AFTER `show()` — on macOS maximising a
 * still-hidden window is a no-op. Minimums are raised to the real
 * 1024×700 only after the scale-up so they never force the small
 * boot bounds larger. The boot maximise happened FROM the loader frame,
 * so the first restore would land on the loader size — a one-shot
 * `unmaximize` handler expands it to the real normal frame instead;
 * later restore cycles keep the user's own frame natively.
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

  mainWindow.show();
  mainWindow.focus();
  console.log("[Main] Main window shown at loader bounds");

  console.log("[Main] About to close splash window");
  closeSplashWindow();

  // Scale up into the full app: raise the minimums first so the maximised
  // size is legal, then zoom. macOS animates maximize() from the small
  // centered bounds shown above.
  mainWindow.setMinimumSize(1024, 700);
  mainWindow.maximize();
  console.log("[Main] Main window scaled to full size");

  // The zoom above maximised FROM the loader frame, so the first restore
  // would land on the loader size instead of the real normal frame. Expand
  // once to the normal bounds on first un-maximise; later cycles keep the
  // user's own frame natively. The width guard keeps a future programmatic
  // resize from ever being shrunk by this handler.
  const win = mainWindow;
  win.once("unmaximize", () => {
    if (win.isDestroyed()) return;
    const [width = 0] = win.getSize();
    if (width >= MAIN_NORMAL_WIDTH) return;
    win.setBounds(resolveNormalBounds(screen.getPrimaryDisplay().workArea));
  });

  return consumePendingDeepLink();
}
