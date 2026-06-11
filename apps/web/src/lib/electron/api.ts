/**
 * Electron preload API typing and access — the single source of truth for
 * `window.api` on the web side. Plain module (no "use client") so both React
 * hooks and non-React modules (axios client, stream handlers) can use it.
 */

import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  DesktopToolRequest,
  DesktopToolResult,
} from "@shared/desktop-tools";

/** Auth callback data from the gaia:// deep link. */
export interface AuthCallbackData {
  token: string;
}

/** The API surface exposed by the desktop app's preload script. */
export interface ElectronAPI {
  getPlatform: () => Promise<NodeJS.Platform>;
  getVersion: () => Promise<string>;
  isElectron: boolean;
  signalReady: () => void;
  openExternal: (url: string) => void;
  onAuthCallback: (callback: (data: AuthCallbackData) => void) => () => void;
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
}

/** Type guard: `window.api` exists and is the Electron preload API. */
export function hasElectronAPI(
  window: Window,
): window is Window & { api: ElectronAPI } {
  return (
    typeof window !== "undefined" &&
    "api" in window &&
    typeof window.api === "object" &&
    window.api !== null &&
    "isElectron" in window.api &&
    window.api.isElectron === true
  );
}

/** The preload API, or null outside the desktop app (including SSR). */
export function getElectronAPI(): ElectronAPI | null {
  if (typeof window === "undefined" || !hasElectronAPI(window)) return null;
  return window.api;
}

/** Header the backend reads to surface desktop-only tools. */
export const CLIENT_TYPE_HEADER = "X-Client-Type";
export const DESKTOP_CLIENT_TYPE = "desktop";

/** `X-Client-Type: desktop` when running in the desktop app, else nothing. */
export function desktopClientHeaders(): Record<string, string> {
  return getElectronAPI() ? { [CLIENT_TYPE_HEADER]: DESKTOP_CLIENT_TYPE } : {};
}
