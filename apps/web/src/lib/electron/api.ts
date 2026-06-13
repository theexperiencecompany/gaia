/**
 * Electron preload API typing and access — the single source of truth for
 * `window.api` on the web side. Plain module (no "use client") so both React
 * hooks and non-React modules (axios client, stream handlers) can use it.
 */

import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  DesktopSettingsSnapshot,
  DesktopShortcutUpdateResult,
  DesktopToolRequest,
  DesktopToolResult,
} from "@shared/desktop-tools";

/** The API surface exposed by the desktop app's preload script. */
export interface ElectronAPI {
  getPlatform: () => Promise<NodeJS.Platform>;
  getVersion: () => Promise<string>;
  isElectron: boolean;
  signalReady: () => void;
  openExternal: (url: string) => void;
  onAuthRedirecting: (callback: () => void) => () => void;
  notifyWakeWord: () => void;
  dismissPopup: () => void;
  resizePopup: (height: number) => void;
  onPopupActivate: (
    callback: (data: { trigger: "wake-word" | "shortcut" }) => void,
  ) => () => void;
  onPopupDeactivate: (callback: () => void) => () => void;
  executeDesktopTool: (
    request: DesktopToolRequest,
  ) => Promise<DesktopToolResult>;
  getDesktopPermissions: () => Promise<DesktopPermissionStatus>;
  openPermissionSettings: (pane: DesktopPermissionPane) => void;
  requestDesktopPermission: (
    pane: DesktopPermissionPane,
  ) => Promise<DesktopPermissionStatus>;
  relaunchDesktopApp: () => void;
  getDesktopSettings: () => Promise<DesktopSettingsSnapshot>;
  setPopupShortcut: (
    accelerator: string,
  ) => Promise<DesktopShortcutUpdateResult>;
  setAppIcon: (id: string) => Promise<boolean>;
}

/** Type guard: `win.api` exists and is the Electron preload API. */
function hasElectronAPI(
  win: Window | undefined,
): win is Window & { api: ElectronAPI } {
  return (
    win !== undefined &&
    "api" in win &&
    typeof win.api === "object" &&
    win.api !== null &&
    "isElectron" in win.api &&
    win.api.isElectron === true
  );
}

/** The preload API, or null outside the desktop app (including SSR). */
export function getElectronAPI(): ElectronAPI | null {
  // In SSR globalThis.window is undefined, which the guard handles directly.
  return hasElectronAPI(globalThis.window) ? globalThis.window.api : null;
}

/** Header the backend reads to surface desktop-only tools. */
export const CLIENT_TYPE_HEADER = "X-Client-Type";
export const DESKTOP_CLIENT_TYPE = "desktop";

/** `X-Client-Type: desktop` when running in the desktop app, else nothing. */
export function desktopClientHeaders(): Record<string, string> {
  return getElectronAPI() ? { [CLIENT_TYPE_HEADER]: DESKTOP_CLIENT_TYPE } : {};
}
