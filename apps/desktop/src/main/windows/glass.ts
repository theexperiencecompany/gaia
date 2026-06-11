/**
 * Liquid Glass Helpers
 *
 * macOS 26 "Tahoe" (Darwin 25) ships the native NSGlassEffectView,
 * exposed to Electron via `electron-liquid-glass`. Windows that want a
 * glass backdrop use these helpers and fall back to vibrancy materials
 * on older macOS versions.
 *
 * Known limitation: macOS renders the glass material slightly dimmed
 * for non-key windows and offers no public override. Private-property
 * pokes don't control it and destabilize the view (corner radius
 * corruption); tracked upstream at Meridius-Labs/electron-liquid-glass#64.
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
 * Attach a native glass view behind `win` once its content has loaded.
 *
 * The window must be created with `transparent: true` and WITHOUT a
 * vibrancy material (vibrancy renders on top and washes out the glass).
 *
 * @param win - Target window.
 * @param options - Corner radius / tint passed to the native view.
 */
export function applyLiquidGlass(
  win: BrowserWindow,
  options: { cornerRadius?: number; tintColor?: string } = {},
): void {
  const liquidGlass = loadLiquidGlass();
  if (!liquidGlass) return;

  win.webContents.once("did-finish-load", () => {
    try {
      liquidGlass.addView(win.getNativeWindowHandle(), options);
      console.log("[Main] Liquid glass applied");
    } catch (err) {
      console.error("[Main] Failed to apply liquid glass:", err);
    }
  });
}
