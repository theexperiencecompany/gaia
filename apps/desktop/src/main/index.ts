/**
 * GAIA Desktop — Main Process Entry Point
 *
 * Orchestrates the application startup in a performance-optimised
 * order:
 *
 * 1. Register the `gaia://` protocol (must happen before `app.ready`)
 * 2. Acquire single-instance lock
 * 3. On `app.ready`:
 *    a. Show splash screen **immediately** (with the persisted Dock icon)
 *    b. Register IPC handlers, session fixes, auto-updater
 *    c. Start the Next.js server **and** create the main window
 *       **in parallel** (neither blocks the other)
 * 4. When the renderer signals `window-ready`, swap splash → main
 * 5. Only then create the hidden background surfaces (assistant popup,
 *    wake-word listener) — two extra renderers competing with the main
 *    window during boot would keep the splash up longer
 * 6. Fallback timeout ensures the main window appears even if the
 *    renderer never signals
 *
 * @module index
 */

// Enable V8 code caching for faster subsequent startups (~20-30% improvement)
import "v8-compile-cache";

import { electronApp, optimizer } from "@electron-toolkit/utils";
import { app, globalShortcut } from "electron";
import { applyPersistedAppIcon } from "./app-icon";
import { checkForUpdatesAfterDelay, setupAutoUpdater } from "./auto-updater";
import { handleDeepLink } from "./deep-link";
import { registerIpcHandlers } from "./ipc";
import { registerPopupShortcut } from "./popup-shortcut";
import { registerLinuxDevProtocol, registerProtocol } from "./protocol";
import { startNextServer, stopNextServer } from "./server";
import { fixSessionCookies } from "./session";
import {
  createAssistantPopup,
  destroyAssistantPopup,
} from "./windows/assistant-popup";
import {
  createMainWindow,
  getMainWindow,
  isMainWindowShown,
  setPendingDeepLink,
  showMainWindow,
} from "./windows/main";
import { createSplashWindow, isSplashAlive } from "./windows/splash";
import {
  createWakeListenerWindow,
  destroyWakeListenerWindow,
} from "./windows/wake-listener";

// ---------------------------------------------------------------------------
// Pre-ready setup (must run before app.ready)
// ---------------------------------------------------------------------------

/** GPU acceleration and performance flags. */
app.commandLine.appendSwitch("enable-gpu-rasterization");
app.commandLine.appendSwitch("enable-zero-copy");
app.commandLine.appendSwitch("disable-renderer-backgrounding");

/** Register gaia:// protocol handler. */
registerProtocol();
registerLinuxDevProtocol();

// ---------------------------------------------------------------------------
// Single-instance lock
// ---------------------------------------------------------------------------

/** Whether the embedded Next.js server has finished starting. */
let serverStarted = false;

/** Whether the hidden background surfaces have been created. */
let backgroundSurfacesCreated = false;

/** Grace period before the splash is force-swapped if the renderer never
 * signals ready (covers server start + page load + hydration). */
const FALLBACK_SHOW_TIMEOUT_MS = 10_000;

/**
 * Create the hidden background surfaces (assistant popup + wake-word
 * listener). Deferred until the main window is on screen: each is a
 * full renderer process loading its own app route, and spinning them
 * up during boot competes with the main window for CPU and server
 * time — directly extending how long the splash stays visible.
 */
function createBackgroundSurfaces(): void {
  if (backgroundSurfacesCreated) return;

  try {
    createAssistantPopup(() => serverStarted);
    createWakeListenerWindow(() => serverStarted).catch(console.error);
    // Mark created only after construction succeeds — otherwise a synchronous
    // failure would latch the flag and leave the popup permanently absent,
    // turning the global shortcut into a silent no-op for the whole session.
    backgroundSurfacesCreated = true;
  } catch (err) {
    console.error("[Main] Failed to create background surfaces:", err);
  }
}

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  // Windows/Linux: a second instance was launched (e.g. via deep link)
  app.on("second-instance", (_event, commandLine) => {
    console.log("[Main] Second instance detected, command line:", commandLine);

    const url = commandLine.find((arg) => arg.startsWith("gaia://"));
    if (url) handleDeepLink(url, getMainWindow());

    const win = getMainWindow();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  // macOS: deep link while the app is already running
  app.on("open-url", (event, url) => {
    event.preventDefault();
    console.log("[Main] open-url event:", url);

    const win = getMainWindow();
    if (win && !win.isDestroyed()) {
      handleDeepLink(url, win);
    } else {
      setPendingDeepLink(url);
    }
  });

  // -----------------------------------------------------------------------
  // Main startup sequence
  // -----------------------------------------------------------------------

  app.whenReady().then(() => {
    const isProduction =
      process.env.NODE_ENV === "production" || app.isPackaged;

    electronApp.setAppUserModelId("io.heygaia.desktop");

    // STEP 1 — Splash screen (first thing the user sees), with the
    // persisted custom Dock icon applied before anything else renders
    // so the Dock is correct from the very first frame.
    createSplashWindow();
    applyPersistedAppIcon();

    // STEP 2 — Non-blocking setup
    if (isProduction) {
      setupAutoUpdater();
      checkForUpdatesAfterDelay();
    }

    app.on("browser-window-created", (_, window) => {
      optimizer.watchWindowShortcuts(window);
    });

    registerIpcHandlers(() => {
      const pendingUrl = showMainWindow();
      if (pendingUrl) handleDeepLink(pendingUrl, getMainWindow());
      createBackgroundSurfaces();
    });

    fixSessionCookies();

    // STEP 3 — Server + window creation in PARALLEL
    if (isProduction) {
      startNextServer()
        .then(() => {
          serverStarted = true;
          console.log("[Main] Next.js server started");
        })
        .catch((error) => {
          console.error("[Main] Failed to start Next.js server:", error);
          serverStarted = true; // allow window to attempt loading for error recovery
        });
    }

    createMainWindow(() => serverStarted).catch(console.error);

    // The shortcut is safe to register before the popup windows exist —
    // toggling is a guarded no-op until createBackgroundSurfaces() runs.
    registerPopupShortcut();

    // STEP 4 — Fallback timeout (10 s covers server + load + hydration)
    setTimeout(() => {
      if (isSplashAlive()) {
        console.log("[Main] Fallback: showing main window after timeout");
        const pendingUrl = showMainWindow();
        if (pendingUrl) handleDeepLink(pendingUrl, getMainWindow());
      }
      createBackgroundSurfaces();
    }, FALLBACK_SHOW_TIMEOUT_MS);

    // macOS: Dock icon clicked. The hidden background surfaces (popup,
    // wake listener) always exist, so "no windows left" never happens —
    // act on the main window itself: refocus it when shown, re-create it
    // when closed, and leave it alone while it is still booting behind
    // the splash.
    app.on("activate", () => {
      const win = getMainWindow();
      if (win && !win.isDestroyed()) {
        if (!isMainWindowShown()) return;
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
        return;
      }
      createMainWindow(() => serverStarted).catch(console.error);
    });

    // Check for deep link in launch args (Windows/Linux cold start)
    const deepLinkArg = process.argv.find((arg) => arg.startsWith("gaia://"));
    if (deepLinkArg) {
      console.log("[Main] Deep link from command line:", deepLinkArg);
      setPendingDeepLink(deepLinkArg);
    }
  });

  // -----------------------------------------------------------------------
  // App lifecycle
  // -----------------------------------------------------------------------

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
  });

  app.on("before-quit", () => {
    destroyAssistantPopup();
    destroyWakeListenerWindow();
    stopNextServer().catch(console.error);
  });
}
