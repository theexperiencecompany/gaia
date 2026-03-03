/**
 * Splash Window Module
 *
 * Creates and manages the fullscreen splash screen shown
 * immediately on app launch while the Next.js server and
 * main window initialise in the background.
 *
 * The splash uses `show: true` so it appears instantly —
 * no waiting for `dom-ready` or any other event. On macOS it
 * also enables the `under-window` vibrancy effect.
 *
 * @module windows/splash
 */

import { join } from "node:path";
import { app, BrowserWindow, screen } from "electron";

/** Reference to the current splash window (if any). */
let splashWindow: BrowserWindow | null = null;

/**
 * Create and display the splash screen.
 *
 * This **must** be the very first visual operation in the
 * startup flow — no blocking code should run before it.
 *
 * The window is frameless, transparent, non-resizable, and
 * sized to fill the primary display's work area.
 */
export function createSplashWindow(): void {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  splashWindow = new BrowserWindow({
    width,
    height,
    x: 0,
    y: 0,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: true,
    maximizable: false,
    alwaysOnTop: false,
    skipTaskbar: false,
    focusable: true,
    show: true,
    hasShadow: false,
    vibrancy: process.platform === "darwin" ? "under-window" : undefined,
    visualEffectState: "active",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  const splashPath = app.isPackaged
    ? join(process.resourcesPath, "splash.html")
    : join(__dirname, "../../resources/splash.html");

  splashWindow.loadFile(splashPath);
}

/**
 * Destroy the splash window and release its reference.
 *
 * Uses `destroy()` rather than `close()` to guarantee the
 * window is removed immediately without firing close events.
 */
export function closeSplashWindow(): void {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.destroy();
    splashWindow = null;
    console.log("[Main] Splash window destroyed");
  }
}

/**
 * Check whether the splash window still exists and is not destroyed.
 *
 * @returns `true` if the splash is still visible.
 */
export function isSplashAlive(): boolean {
  return splashWindow !== null && !splashWindow.isDestroyed();
}
