/**
 * Liquid Glass Helpers
 *
 * macOS 26 "Tahoe" (Darwin 25) ships the native NSGlassEffectView,
 * exposed to Electron via `electron-liquid-glass`. Windows that want a
 * glass backdrop use these helpers and fall back to vibrancy materials
 * on older macOS versions.
 *
 * @module windows/glass
 */

import { release } from "node:os";
import type { BrowserWindow } from "electron";
import liquidGlass from "electron-liquid-glass";

/** First Darwin major version with native liquid glass (macOS 26). */
const LIQUID_GLASS_MIN_DARWIN_MAJOR = 25;

/** Whether the current OS supports native liquid glass. */
export function supportsLiquidGlass(): boolean {
  return (
    process.platform === "darwin" &&
    Number.parseInt(release().split(".")[0] ?? "0", 10) >=
      LIQUID_GLASS_MIN_DARWIN_MAJOR
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
  win.webContents.once("did-finish-load", () => {
    try {
      const viewId = liquidGlass.addView(win.getNativeWindowHandle(), options);
      // Pin the glass to its active appearance — macOS subdues the
      // material when the window isn't key, which makes the popup's two
      // islands (only one can be focused) render visibly different.
      liquidGlass.unstable_setSubdued(viewId, 0);
      console.log("[Main] Liquid glass applied");
    } catch (err) {
      console.error("[Main] Failed to apply liquid glass:", err);
    }
  });
}
