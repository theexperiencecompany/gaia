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
import { getBridgeHost } from "./bridge/host";
import { applyLaunchAtLogin, launchedHidden } from "./bridge/launch-at-login";
import { registerBridgeLogoutHook } from "./bridge/logout-hook";
import { createBridgeTray } from "./bridge/tray";
import { handleDeepLink } from "./deep-link";
import { registerIpcHandlers } from "./ipc";
import { registerPopupShortcut } from "./popup-shortcut";
import { registerLinuxDevProtocol, registerProtocol } from "./protocol";
import { startNextServer, stopNextServer } from "./server";
import { fixSessionCookies } from "./session";
import { getDesktopSettings } from "./settings";
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

// A console.* write to a pipe whose reader has gone away (terminal closed, parent
// exited) emits EPIPE/EIO, which without a listener crashes the app with a dialog.
// Only those two codes are benign; anything else still surfaces.
const ignoreBrokenPipe = (err: NodeJS.ErrnoException): void => {
  if (err.code === "EPIPE" || err.code === "EIO") return;
  throw err;
};
process.stdout.on("error", ignoreBrokenPipe);
process.stderr.on("error", ignoreBrokenPipe);

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

/** Whether the visible surfaces (splash, Next server, main window) have been
 * booted. A `--hidden` login launch defers this until the user opens GAIA. */
let mainSurfaceBooted = false;

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

/** Delay after the main window appears before spinning up the hidden background
 * surfaces. Each is a full renderer loading its own route; starting them the
 * instant the user first sees the window steals CPU and embedded-server time
 * from the visible window's first interaction (chat load). A short defer keeps
 * that first moment snappy — the popup/wake-word are not needed immediately. */
const BACKGROUND_SURFACES_DELAY_MS = 2_000;

/** Schedule {@link createBackgroundSurfaces} shortly after the main window is on
 * screen, deferred so it does not contend with first interaction. Idempotent via
 * the guard in createBackgroundSurfaces. */
function scheduleBackgroundSurfaces(): void {
  setTimeout(createBackgroundSurfaces, BACKGROUND_SURFACES_DELAY_MS);
}

/**
 * Boot the visible surfaces — splash, embedded Next.js server, main window,
 * popup shortcut, and the splash→main fallback. Idempotent: the normal launch
 * calls it at `ready`, while a `--hidden` login launch defers it until the user
 * opens GAIA from the tray.
 */
function bootMainSurface(): void {
  if (mainSurfaceBooted) return;
  mainSurfaceBooted = true;

  const isProduction =
    process.env["NODE_ENV"] === "production" || app.isPackaged;

  // A hidden launch may have hidden the Dock — restore it now that a window
  // is coming.
  if (process.platform === "darwin") app.dock?.show();

  createSplashWindow();
  applyPersistedAppIcon();

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

  // Safe before the popup windows exist — toggling is a guarded no-op until
  // createBackgroundSurfaces() runs.
  registerPopupShortcut();

  setTimeout(() => {
    if (isSplashAlive()) {
      console.log("[Main] Fallback: showing main window after timeout");
      const pendingUrl = showMainWindow();
      if (pendingUrl) handleDeepLink(pendingUrl, getMainWindow());
    }
    scheduleBackgroundSurfaces();
  }, FALLBACK_SHOW_TIMEOUT_MS);
}

/**
 * Bring the main window to the foreground, booting the visible surfaces first
 * if a `--hidden` launch never created them. Used by the tray's "Open GAIA"
 * and by macOS Dock `activate`.
 */
function openMainSurface(): void {
  const win = getMainWindow();
  if (win && !win.isDestroyed()) {
    // Still booting behind the splash — let the normal ready flow show it.
    if (!isMainWindowShown()) return;
    if (process.platform === "darwin") app.dock?.show();
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    return;
  }
  bootMainSurface();
}

/** If this Mac is paired and auto-start is on, bring the tunnel up on launch so
 * the device comes back online without a manual toggle. */
async function maybeAutoStartBridge(): Promise<void> {
  if (!getDesktopSettings().bridgeAutoStart) return;
  const host = getBridgeHost();
  host.configureStateDir();
  if (!host.status().paired) return;
  try {
    await host.start();
  } catch (err) {
    console.error("[Main] Bridge auto-start failed:", err);
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
      process.env["NODE_ENV"] === "production" || app.isPackaged;

    electronApp.setAppUserModelId("io.heygaia.desktop");

    // Non-blocking setup (runs in every launch mode, hidden included).
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
      scheduleBackgroundSurfaces();
    });

    fixSessionCookies();

    // Boot before the bridge/tray setup below: that does synchronous disk reads and
    // a macOS login-item call, and nothing in it is needed to paint the window.
    // A --hidden login launch stays tray-only: no splash, window, server or Dock icon.
    if (launchedHidden()) {
      if (process.platform === "darwin") app.dock?.hide();
    } else {
      bootMainSurface();
    }

    // Watch the session cookie so signing out tears down the bridge device (R5),
    // and reconcile the stored binding against the current session on launch.
    registerBridgeLogoutHook();

    // Always-on bridge surfaces: the tray, the login item mirrored from the
    // stored preference, and (when paired + enabled) an auto-started tunnel —
    // all independent of whether a window is shown.
    createBridgeTray(openMainSurface);
    applyLaunchAtLogin(getDesktopSettings().launchAtLogin);
    void maybeAutoStartBridge();

    // macOS Dock click / relaunch: open (or re-create) the main window. The
    // hidden background surfaces mean "no windows left" never happens, so this
    // acts on the main window itself.
    app.on("activate", openMainSurface);

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
    // Drop the device offline so the backend sees a clean disconnect.
    getBridgeHost()
      .stop()
      .catch((err) => console.error("[Main] Bridge stop on quit failed:", err));
    stopNextServer().catch(console.error);
  });
}
