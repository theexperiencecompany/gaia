/**
 * GAIA Desktop — Main Process Entry Point
 *
 * Orchestrates the application startup in a performance-optimised
 * order:
 *
 * 1. Register the `gaia://` protocol (must happen before `app.ready`)
 * 2. Acquire single-instance lock
 * 3. On `app.ready`:
 *    a. Show splash screen **immediately**
 *    b. Register IPC handlers, session fixes, auto-updater
 *    c. Start the Next.js server **and** create the main window
 *       **in parallel** (neither blocks the other)
 * 4. When the renderer signals `window-ready`, swap splash → main
 * 5. Fallback timeout ensures the main window appears even if the
 *    renderer never signals
 *
 * @module index
 */

// Enable V8 code caching for faster subsequent startups (~20-30% improvement)
import "v8-compile-cache";

import { electronApp, optimizer } from "@electron-toolkit/utils";
import { app, BrowserWindow } from "electron";
import { checkForUpdatesAfterDelay, setupAutoUpdater } from "./auto-updater";
import { handleDeepLink } from "./deep-link";
import { registerIpcHandlers } from "./ipc";
import { registerLinuxDevProtocol, registerProtocol } from "./protocol";
import { startNextServer, stopNextServer } from "./server";
import { fixSessionCookies } from "./session";
import {
  createMainWindow,
  createSplashWindow,
  getMainWindow,
  isSplashAlive,
  setPendingDeepLink,
  showMainWindow,
} from "./windows";

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

    // STEP 1 — Splash screen (first thing the user sees)
    createSplashWindow();

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

    // STEP 4 — Fallback timeout (10 s covers server + load + hydration)
    setTimeout(() => {
      if (isSplashAlive()) {
        console.log("[Main] Fallback: showing main window after timeout");
        const pendingUrl = showMainWindow();
        if (pendingUrl) handleDeepLink(pendingUrl, getMainWindow());
      }
    }, 10000);

    // macOS: re-create window when dock icon is clicked
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow(() => serverStarted).catch(console.error);
      }
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

  app.on("before-quit", () => {
    stopNextServer().catch(console.error);
  });
}
