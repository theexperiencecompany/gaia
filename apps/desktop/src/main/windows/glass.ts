/**
 * Liquid Glass Helpers
 *
 * macOS 26 "Tahoe" (Darwin 25) ships the native NSGlassEffectView,
 * exposed to Electron via `electron-liquid-glass`. Windows that want a
 * glass backdrop use these helpers and fall back to vibrancy materials
 * on older macOS versions.
 *
 * Non-key dimming: macOS renders the glass material washed-out for
 * non-key windows (upstream: Meridius-Labs/electron-liquid-glass#64).
 * Measured behaviour (isolated two-panel harness, Electron 39 /
 * macOS 26): `scrimState = 1` freezes the material at its ACTIVE
 * appearance across key transitions, while `subduedState`/`scrimState`
 * = 0 are no-op defaults — pinning those (the old keep-alive approach)
 * never controlled the dimming. `keepActive` applies the scrim pin,
 * re-asserted on the window's own focus lifecycle instead of a polling
 * timer (the 250 ms poke loop was implicated in corner-radius
 * corruption).
 *
 * @module windows/glass
 */

import { createRequire } from "node:module";
import { release } from "node:os";
import type { BrowserWindow } from "electron";

/** First Darwin major version with native liquid glass (macOS 26). */
const LIQUID_GLASS_MIN_DARWIN_MAJOR = 25;

/** Minimal surface of `electron-liquid-glass` that we use. */
interface LiquidGlassModule {
  addView: (
    handle: Buffer,
    options: { cornerRadius?: number; tintColor?: string },
  ) => number;
  unstable_setScrim: (id: number, scrim: number) => void;
}

// `electron-liquid-glass` is an optional native enhancement — the app must
// boot (with the vibrancy fallback) when it isn't installed, so it is
// loaded lazily instead of via a static import. `undefined` = not yet
// attempted, `null` = unavailable.
let liquidGlassModule: LiquidGlassModule | null | undefined;

function loadLiquidGlass(): LiquidGlassModule | null {
  if (liquidGlassModule !== undefined) return liquidGlassModule;
  try {
    const require = createRequire(import.meta.url);
    const loaded = require("electron-liquid-glass");
    liquidGlassModule = (loaded.default ?? loaded) as LiquidGlassModule;
  } catch {
    console.warn(
      "[Main] electron-liquid-glass unavailable — using vibrancy fallback",
    );
    liquidGlassModule = null;
  }
  return liquidGlassModule;
}

/** Whether the current OS (and installed native module) support liquid glass. */
export function supportsLiquidGlass(): boolean {
  return (
    process.platform === "darwin" &&
    Number.parseInt(release().split(".")[0] ?? "0", 10) >=
      LIQUID_GLASS_MIN_DARWIN_MAJOR &&
    loadLiquidGlass() !== null
  );
}

/**
 * Pin the glass material to its active appearance so the window never
 * renders the washed-out non-key state. `scrimState = 1` is a private
 * NSGlassEffectView property — best effort, re-asserted on the
 * window's own focus lifecycle in case AppKit re-evaluates it.
 */
function pinActiveAppearance(
  win: BrowserWindow,
  glass: LiquidGlassModule,
  viewId: number,
): void {
  const pin = () => {
    try {
      glass.unstable_setScrim(viewId, 1);
    } catch {
      // Private API — losing the pin only restores stock dimming.
    }
  };
  pin();
  win.on("focus", pin);
  win.on("blur", pin);
  win.on("show", pin);
}

/**
 * Attach a native glass view behind `win` once its content has loaded.
 *
 * The window must be created with `transparent: true` and WITHOUT a
 * vibrancy material (vibrancy renders on top and washes out the glass).
 *
 * @param win - Target window.
 * @param options - Corner radius / tint passed to the native view, plus
 *   `keepActive` to hold the active material while the window is not key.
 */
export function applyLiquidGlass(
  win: BrowserWindow,
  options: {
    cornerRadius?: number;
    tintColor?: string;
    keepActive?: boolean;
  } = {},
): void {
  const liquidGlass = loadLiquidGlass();
  if (!liquidGlass) return;

  const { keepActive, ...viewOptions } = options;

  win.webContents.once("did-finish-load", () => {
    try {
      const viewId = liquidGlass.addView(
        win.getNativeWindowHandle(),
        viewOptions,
      );
      if (keepActive && viewId >= 0) {
        pinActiveAppearance(win, liquidGlass, viewId);
      }
      console.log("[Main] Liquid glass applied");
    } catch (err) {
      console.error("[Main] Failed to apply liquid glass:", err);
    }
  });
}
