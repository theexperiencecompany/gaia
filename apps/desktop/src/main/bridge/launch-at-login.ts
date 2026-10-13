// Login-item control for the always-on device bridge. When enabled, macOS
// relaunches the app hidden (tray-only) at login so a paired device comes back
// online unattended, without popping a window in the user's face.

import { app } from "electron";

/** CLI flag that puts the app into tray-only (no splash/main window) mode. */
export const HIDDEN_ARG = "--hidden";

/**
 * True when this process should run headless in the tray: either launched with
 * `--hidden` (our login item passes it) or opened by macOS at login. The latter
 * is the reliable macOS signal since custom login-item args aren't guaranteed
 * to survive the relaunch.
 */
export function launchedHidden(): boolean {
  if (process.argv.includes(HIDDEN_ARG)) return true;
  return app.getLoginItemSettings().wasOpenedAtLogin === true;
}

/** Register or clear the OS login item, mirroring the stored preference. A
 * login item records the current executable's path; for an unpackaged dev
 * binary that path is meaningless and macOS rejects it ("Operation not
 * permitted"), so only real packaged builds own a login item. */
export function applyLaunchAtLogin(enabled: boolean): void {
  if (!app.isPackaged) return;
  app.setLoginItemSettings({ openAtLogin: enabled, args: [HIDDEN_ARG] });
}
