/**
 * Assistant Popup Windows Module
 *
 * The Siri-style assistant is TWO frameless windows, each with its own
 * native liquid glass: the composer pill, and the conversation card
 * that appears below it once there are messages. Chat state flows from
 * the composer renderer to the feed renderer over a BroadcastChannel
 * (see apps/web src/features/desktop-popup/sync.ts).
 *
 * Both are created hidden at startup so summoning is instant, and are
 * only ever hidden (never destroyed) on dismissal.
 *
 * @module windows/assistant-popup
 */

import { join } from "node:path";
import { app, BrowserWindow, screen } from "electron";
import { applyLiquidGlass, supportsLiquidGlass } from "./glass";
import { loadAppRoute } from "./load-url";

/** Width of both popup windows, in px. */
const POPUP_WIDTH = 420;

/** Composer pill window height, in px — exactly the 48px input. */
const COMPOSER_HEIGHT = 48;

/** Gap between the composer pill and the conversation card, in px. */
const ISLAND_GAP = 8;

/** Fraction of the work area the popup stack may occupy vertically. */
const MAX_SCREEN_FRACTION = 0.8;

/** Gap between the pill and the screen work-area edges, in px. */
const POPUP_MARGIN = 16;

/** Corner radius of the composer pill (half its height — a capsule). */
const COMPOSER_CORNER_RADIUS = 24;

/** Corner radius of the conversation card. */
const FEED_CORNER_RADIUS = 24;

/** Duration of the window opacity fade, in ms. */
const FADE_DURATION_MS = 160;

/** Opacity animation tick interval, in ms (~60 fps). */
const FADE_TICK_MS = 16;

/** Feed content below this height is treated as "empty" and hidden. */
const FEED_MIN_CONTENT_PX = 40;

/** The composer pill window. */
let composerWindow: BrowserWindow | null = null;

/** The conversation card window. */
let feedWindow: BrowserWindow | null = null;

/** Whether the popup (as a unit) is currently shown. */
let popupShown = false;

/** Whether a dismissal is currently in flight. */
let dismissing = false;

/** Latest content height reported by the feed renderer. */
let feedContentHeight = 0;

/** In-flight opacity fades, keyed per window. */
const fadeTimers = new Map<BrowserWindow, NodeJS.Timeout>();

/** Feed height animation duration, in ms — matches the renderer's
 * POPUP_TRANSITION_SECONDS so window and content move as one. */
const RESIZE_DURATION_MS = 350;

/** In-flight feed height animation. */
let resizeTimer: NodeJS.Timeout | null = null;

/** Quart ease-out — the temporal twin of the renderer's [0.19,1,0.22,1]. */
function easeOutQuart(t: number): number {
  return 1 - (1 - t) ** 4;
}

/**
 * Animate the feed window to `target` with our own easing — the macOS
 * default `setBounds` animation is short, linear-ish, and visibly out
 * of sync with the content's motion.
 */
/**
 * NSPanels with `resizable: false` reject programmatic setBounds height
 * changes — flip resizable around the mutation. The windows are
 * frameless, so users never get resize handles either way.
 */
function setBoundsForced(win: BrowserWindow, bounds: Electron.Rectangle): void {
  win.setResizable(true);
  win.setBounds(bounds);
  win.setResizable(false);
}

function animateFeedBounds(target: Electron.Rectangle): void {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  if (resizeTimer) {
    clearInterval(resizeTimer);
    resizeTimer = null;
  }

  const start = feedWindow.getBounds();
  if (start.height === target.height && start.y === target.y) {
    setBoundsForced(feedWindow, target);
    return;
  }

  const t0 = Date.now();
  resizeTimer = setInterval(() => {
    if (!feedWindow || feedWindow.isDestroyed()) {
      if (resizeTimer) clearInterval(resizeTimer);
      resizeTimer = null;
      return;
    }
    const t = Math.min(1, (Date.now() - t0) / RESIZE_DURATION_MS);
    const e = easeOutQuart(t);
    setBoundsForced(feedWindow, {
      x: target.x,
      y: target.y,
      width: target.width,
      height: Math.round(start.height + (target.height - start.height) * e),
    });
    if (t >= 1 && resizeTimer) {
      clearInterval(resizeTimer);
      resizeTimer = null;
    }
  }, FADE_TICK_MS);
}

function cancelFade(win: BrowserWindow): void {
  const timer = fadeTimers.get(win);
  if (timer) {
    clearInterval(timer);
    fadeTimers.delete(win);
  }
}

/** Animate `win`'s opacity towards `target`, then run `onDone`. */
function fadeTo(win: BrowserWindow, target: number, onDone?: () => void): void {
  cancelFade(win);
  const steps = Math.max(1, Math.round(FADE_DURATION_MS / FADE_TICK_MS));
  const start = win.getOpacity();
  const delta = (target - start) / steps;
  let step = 0;

  const timer = setInterval(() => {
    if (win.isDestroyed()) {
      cancelFade(win);
      return;
    }
    step += 1;
    if (step >= steps) {
      win.setOpacity(target);
      cancelFade(win);
      onDone?.();
      return;
    }
    win.setOpacity(start + delta * step);
  }, FADE_TICK_MS);
  fadeTimers.set(win, timer);
}

/** Shared window options for both popup islands. */
function islandOptions(
  height: number,
  useLiquidGlass: boolean,
  hasShadow: boolean,
): Electron.BrowserWindowConstructorOptions {
  return {
    width: POPUP_WIDTH,
    height,
    show: false,
    frame: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow,
    // NSPanel, like Siri/Spotlight: nonactivating, keeps the ACTIVE
    // glass material regardless of key-window status. Regular windows
    // render the faded inactive material unless focused — the cause of
    // the glass changing when clicking between the islands.
    type: process.platform === "darwin" ? "panel" : undefined,
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
  };
}

function pinToAllSpaces(win: BrowserWindow): void {
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
}

/**
 * Create both popup windows (hidden) and start loading their routes.
 *
 * @param serverReady - Returns `true` once the production server is up.
 */
export function createAssistantPopup(serverReady: () => boolean): void {
  // Liquid glass is the default: only its native view honors the custom
  // capsule cornerRadius (vibrancy windows are stuck with the standard
  // macOS radius). Known tradeoff: the material can still dim for
  // non-key windows (upstream: Meridius-Labs/electron-liquid-glass#64).
  const useLiquidGlass = supportsLiquidGlass();

  // Shadows give both islands their edge definition on glass.
  composerWindow = new BrowserWindow(
    islandOptions(COMPOSER_HEIGHT, useLiquidGlass, true),
  );
  feedWindow = new BrowserWindow(islandOptions(200, useLiquidGlass, true));

  // No blur-dismiss: the popup stays until Esc, the X button, the
  // shortcut toggle, or a renderer-initiated dismissal.
  for (const win of [composerWindow, feedWindow]) {
    pinToAllSpaces(win);
    // Cmd/Ctrl+W (menu "Close Window") targets the focused window — for a
    // popup island that must mean "dismiss", never "destroy": a destroyed
    // window would kill the popup until app restart.
    win.on("close", (event) => {
      event.preventDefault();
      dismissAssistantPopup();
    });
  }
  composerWindow.on("closed", () => {
    composerWindow = null;
  });
  feedWindow.on("closed", () => {
    feedWindow = null;
  });

  if (useLiquidGlass) {
    applyLiquidGlass(composerWindow, {
      cornerRadius: COMPOSER_CORNER_RADIUS,
      tintColor: "#00000022",
    });
    applyLiquidGlass(feedWindow, {
      cornerRadius: FEED_CORNER_RADIUS,
      tintColor: "#00000022",
    });
  }

  loadAppRoute(composerWindow, "/desktop-popup", serverReady).catch(
    console.error,
  );
  loadAppRoute(feedWindow, "/desktop-popup/feed", serverReady).catch(
    console.error,
  );
}

/** Work area of the display the cursor is currently on. */
function activeWorkArea(): Electron.Rectangle {
  return screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
}

/** Top-right pill position within `workArea`. */
function composerBounds(workArea: Electron.Rectangle): Electron.Rectangle {
  return {
    x: workArea.x + workArea.width - POPUP_WIDTH - POPUP_MARGIN,
    y: workArea.y + POPUP_MARGIN,
    width: POPUP_WIDTH,
    height: COMPOSER_HEIGHT,
  };
}

/**
 * Lay out the feed card under the pill, sized to its content up to
 * ~80% of the work area, and show/hide it accordingly.
 *
 * @param animate - Animate the resize (macOS native).
 */
function layoutFeed(animate: boolean): void {
  if (!composerWindow || !feedWindow || feedWindow.isDestroyed()) return;

  const workArea = activeWorkArea();
  const pill = composerBounds(workArea);
  const budget =
    Math.round(workArea.height * MAX_SCREEN_FRACTION) -
    COMPOSER_HEIGHT -
    ISLAND_GAP;
  const height = Math.min(feedContentHeight, budget);
  const hasContent = feedContentHeight >= FEED_MIN_CONTENT_PX;

  if (!popupShown || !hasContent) {
    if (feedWindow.isVisible()) feedWindow.hide();
    return;
  }

  const target = {
    x: pill.x,
    y: pill.y + COMPOSER_HEIGHT + ISLAND_GAP,
    width: POPUP_WIDTH,
    height,
  };

  if (animate && feedWindow.isVisible()) {
    animateFeedBounds(target);
  } else {
    setBoundsForced(feedWindow, target);
  }

  if (!feedWindow.isVisible() && !dismissing) {
    feedWindow.setOpacity(0);
    feedWindow.showInactive();
    fadeTo(feedWindow, 1);
  }
}

/**
 * Update the feed island from its renderer's reported content height.
 *
 * @param contentHeight - Scroll height of the conversation content.
 */
export function resizeAssistantPopup(contentHeight: number): void {
  feedContentHeight = Math.max(0, Math.round(contentHeight));
  layoutFeed(true);
}

/** How the popup was summoned — the renderer scopes the ack sound to voice. */
export type PopupTrigger = "wake-word" | "shortcut";

/**
 * Toggle the popup: dismiss when visible, summon when hidden. Bound to
 * the global shortcut so one chord opens AND closes it.
 */
export function toggleAssistantPopup(): void {
  if (popupShown && !dismissing) {
    dismissAssistantPopup();
  } else {
    showAssistantPopup("shortcut");
  }
}

/**
 * Show the popup stack in the top-right of the active display, fading
 * the pill in and telling its renderer to activate (orb, ack sound).
 *
 * Already visible: just reclaim focus and full opacity — replaying the
 * entrance and acknowledgment on an open popup is jarring.
 */
export function showAssistantPopup(trigger: PopupTrigger = "shortcut"): void {
  if (!composerWindow || composerWindow.isDestroyed()) return;

  dismissing = false;

  if (popupShown && composerWindow.isVisible()) {
    fadeTo(composerWindow, 1);
    if (feedWindow && feedWindow.isVisible()) fadeTo(feedWindow, 1);
    app.focus({ steal: true });
    composerWindow.focus();
    return;
  }

  popupShown = true;
  const workArea = activeWorkArea();
  composerWindow.setBounds(composerBounds(workArea));

  composerWindow.setOpacity(0);
  composerWindow.show();
  // The user just summoned GAIA (voice or shortcut) from wherever they
  // are — take keyboard focus so they can type immediately.
  app.focus({ steal: true });
  composerWindow.focus();
  fadeTo(composerWindow, 1);
  composerWindow.webContents.send("popup-activate", { trigger });

  layoutFeed(false);
  console.log("[Main] Assistant popup shown");
}

/**
 * Dismiss the popup: one seamless fade across both islands, then hide.
 * Renderers keep their content mounted (`popup-deactivate` only stops
 * the voice session) so the close never reads as content-vanishing.
 */
export function dismissAssistantPopup(): void {
  if (!composerWindow || composerWindow.isDestroyed()) return;
  if (dismissing || !popupShown) return;
  dismissing = true;
  popupShown = false;

  composerWindow.webContents.send("popup-deactivate");

  if (feedWindow && !feedWindow.isDestroyed() && feedWindow.isVisible()) {
    fadeTo(feedWindow, 0, () => {
      if (feedWindow && !feedWindow.isDestroyed()) feedWindow.hide();
    });
  }
  fadeTo(composerWindow, 0, () => {
    if (!composerWindow || composerWindow.isDestroyed() || !dismissing) return;
    composerWindow.hide();
    dismissing = false;
    console.log("[Main] Assistant popup hidden");
  });
}

/**
 * Destroy both popup windows on app quit. `destroy()` skips the `close`
 * event, bypassing the dismiss-instead-of-close guard that would otherwise
 * block quitting.
 */
export function destroyAssistantPopup(): void {
  if (composerWindow && !composerWindow.isDestroyed()) composerWindow.destroy();
  if (feedWindow && !feedWindow.isDestroyed()) feedWindow.destroy();
}
