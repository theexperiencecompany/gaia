/**
 * Splash Window Module
 *
 * Creates and manages the splash screen shown immediately on app
 * launch while the Next.js server and main window initialise in
 * the background.
 *
 * The splash is a compact, centered, normal-sized window — not
 * fullscreen. It uses `show: true` so it appears instantly — no
 * waiting for `dom-ready` or any other event. On macOS it renders
 * native liquid glass (macOS 26+) with an `under-window` vibrancy
 * fallback on older versions.
 *
 * @module windows/splash
 */

import { join } from "node:path";
import { app, BrowserWindow } from "electron";
import { applyLiquidGlass, supportsLiquidGlass } from "./glass";

/** Splash window width, in px — a normal window, not fullscreen. */
const SPLASH_WIDTH = 560;

/** Splash window height, in px. */
const SPLASH_HEIGHT = 400;

/** Corner radius of the splash card — must match splash.html. */
const SPLASH_CORNER_RADIUS = 28;

/** Reference to the current splash window (if any). */
let splashWindow: BrowserWindow | null = null;

/**
 * Create and display the splash screen.
 *
 * This **must** be the very first visual operation in the
 * startup flow — no blocking code should run before it.
 *
 * The window is frameless, transparent, non-resizable, and
 * centered on the primary display at a fixed compact size.
 */
export function createSplashWindow(): void {
  const useLiquidGlass = supportsLiquidGlass();

  splashWindow = new BrowserWindow({
    width: SPLASH_WIDTH,
    height: SPLASH_HEIGHT,
    center: true,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    minimizable: true,
    maximizable: false,
    alwaysOnTop: false,
    skipTaskbar: false,
    focusable: true,
    show: true,
    hasShadow: true,
    // Native liquid glass replaces vibrancy on macOS 26+ (see glass.ts).
    vibrancy:
      process.platform === "darwin" && !useLiquidGlass
        ? "under-window"
        : undefined,
    visualEffectState: "active",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  if (useLiquidGlass) {
    applyLiquidGlass(splashWindow, { cornerRadius: SPLASH_CORNER_RADIUS });
  }

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
