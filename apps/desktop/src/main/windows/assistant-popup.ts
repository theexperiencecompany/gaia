/**
 * Assistant Popup Window Module
 *
 * A Siri-style glassy panel pinned to the top-right of the screen,
 * summoned by the "Hey GAIA" wake word (or the global shortcut).
 *
 * The window is created hidden at startup so showing it is instant,
 * and it is only ever hidden (never destroyed) on dismissal. It uses
 * the frameless macOS vibrancy recipe — `vibrancy: "hud"` on a
 * non-transparent frameless window — so macOS rounds the corners and
 * blurs the desktop behind it edge-to-edge.
 *
 * @module windows/assistant-popup
 */

import { release } from "node:os";
import { join } from "node:path";
import { app, BrowserWindow, screen } from "electron";
import liquidGlass from "electron-liquid-glass";
import { loadAppRoute } from "./load-url";

/** Popup panel width, in px. */
const POPUP_WIDTH = 420;

/** Popup panel height, in px. */
const POPUP_HEIGHT = 620;

/** Gap between the panel and the screen work-area edges, in px. */
const POPUP_MARGIN = 16;

/** Corner radius of the liquid-glass panel, in px. */
const POPUP_CORNER_RADIUS = 28;

/** Duration of the window opacity fade, in ms. */
const FADE_DURATION_MS = 160;

/** Opacity animation tick interval, in ms (~60 fps). */
const FADE_TICK_MS = 16;

/** How long the renderer's exit animation runs before hiding, in ms. */
const EXIT_ANIMATION_MS = 220;

/** Reference to the popup window (if created). */
let popupWindow: BrowserWindow | null = null;

/** Whether a dismissal is currently in flight. */
let dismissing = false;

/** Handle of the in-flight opacity fade, if any. */
let fadeTimer: NodeJS.Timeout | null = null;

/**
 * Get the current assistant popup window reference.
 *
 * @returns The popup `BrowserWindow`, or `null` if not yet created.
 */
export function getAssistantPopup(): BrowserWindow | null {
  return popupWindow;
}

function cancelFade(): void {
  if (fadeTimer) {
    clearInterval(fadeTimer);
    fadeTimer = null;
  }
}

/** Animate the window opacity towards `target`, then run `onDone`. */
function fadeTo(win: BrowserWindow, target: number, onDone?: () => void): void {
  cancelFade();
  const steps = Math.max(1, Math.round(FADE_DURATION_MS / FADE_TICK_MS));
  const start = win.getOpacity();
  const delta = (target - start) / steps;
  let step = 0;

  fadeTimer = setInterval(() => {
    if (win.isDestroyed()) {
      cancelFade();
      return;
    }
    step += 1;
    if (step >= steps) {
      win.setOpacity(target);
      cancelFade();
      onDone?.();
      return;
    }
    win.setOpacity(start + delta * step);
  }, FADE_TICK_MS);
}

/**
 * Create the assistant popup window (hidden) and start loading the
 * `/desktop-popup` route in the background.
 *
 * @param serverReady - Returns `true` once the production server is up.
 */
export function createAssistantPopup(serverReady: () => boolean): void {
  // macOS 26 "Tahoe" (Darwin 25) ships native liquid glass; older macOS
  // falls back to the HUD vibrancy material.
  const useLiquidGlass =
    process.platform === "darwin" &&
    Number.parseInt(release().split(".")[0] ?? "0", 10) >= 25;

  popupWindow = new BrowserWindow({
    width: POPUP_WIDTH,
    height: POPUP_HEIGHT,
    show: false,
    frame: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: true,
    // Liquid glass needs a fully transparent window with NO vibrancy —
    // the native NSGlassEffectView is attached after the page loads.
    transparent: useLiquidGlass,
    backgroundColor: "#00000000",
    vibrancy:
      process.platform === "darwin" && !useLiquidGlass ? "hud" : undefined,
    visualEffectState: "active",
    roundedCorners: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (useLiquidGlass) {
    const win = popupWindow;
    win.webContents.once("did-finish-load", () => {
      try {
        liquidGlass.addView(win.getNativeWindowHandle(), {
          cornerRadius: POPUP_CORNER_RADIUS,
          tintColor: "#00000022",
        });
        console.log("[Main] Liquid glass applied to assistant popup");
      } catch (err) {
        console.error("[Main] Failed to apply liquid glass:", err);
      }
    });
  }

  // Float above fullscreen apps and follow the user across Spaces.
  popupWindow.setAlwaysOnTop(true, "screen-saver");
  popupWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // Clicking anywhere outside dismisses the popup, like Siri.
  popupWindow.on("blur", () => {
    if (popupWindow?.isVisible()) dismissAssistantPopup();
  });

  popupWindow.on("closed", () => {
    popupWindow = null;
  });

  loadAppRoute(popupWindow, "/desktop-popup", serverReady).catch(console.error);
}

/**
 * Show the popup in the top-right of the display the cursor is on,
 * fading the window in and telling the renderer to play its entrance
 * animation (`popup-activate`).
 *
 * If the popup is already visible, the renderer is re-activated so the
 * orb returns to its listening state.
 */
export function showAssistantPopup(): void {
  if (!popupWindow || popupWindow.isDestroyed()) return;

  dismissing = false;

  if (popupWindow.isVisible()) {
    app.focus({ steal: true });
    popupWindow.focus();
    popupWindow.webContents.send("popup-activate");
    return;
  }

  const { workArea } = screen.getDisplayNearestPoint(
    screen.getCursorScreenPoint(),
  );
  popupWindow.setPosition(
    workArea.x + workArea.width - POPUP_WIDTH - POPUP_MARGIN,
    workArea.y + POPUP_MARGIN,
  );

  popupWindow.setOpacity(0);
  popupWindow.show();
  // The user just summoned GAIA (voice or shortcut) from wherever they
  // are — take keyboard focus so they can type immediately.
  app.focus({ steal: true });
  popupWindow.focus();
  fadeTo(popupWindow, 1);
  popupWindow.webContents.send("popup-activate");
  console.log("[Main] Assistant popup shown");
}

/**
 * Dismiss the popup: let the renderer play its exit animation
 * (`popup-deactivate`), then fade the window out and hide it.
 */
export function dismissAssistantPopup(): void {
  if (!popupWindow || popupWindow.isDestroyed()) return;
  if (dismissing || !popupWindow.isVisible()) return;
  dismissing = true;

  popupWindow.webContents.send("popup-deactivate");

  setTimeout(() => {
    if (!popupWindow || popupWindow.isDestroyed() || !dismissing) return;
    fadeTo(popupWindow, 0, () => {
      if (!popupWindow || popupWindow.isDestroyed() || !dismissing) return;
      popupWindow.hide();
      dismissing = false;
      console.log("[Main] Assistant popup hidden");
    });
  }, EXIT_ANIMATION_MS);
}
