/**
 * Preload Script
 *
 * Runs in a privileged context **before** the renderer page loads.
 * Exposes a safe, sandboxed API surface to the renderer via
 * `contextBridge` so the web app can communicate with the main
 * process without direct access to Node.js or Electron internals.
 *
 * Exposed globals:
 * - `window.electron` — low-level Electron helpers from `@electron-toolkit`
 * - `window.api`      — GAIA-specific IPC methods (see {@link api})
 *
 * @module preload
 */

import { electronAPI } from "@electron-toolkit/preload";
import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  DesktopSettingsSnapshot,
  DesktopShortcutUpdateResult,
  DesktopToolRequest,
  DesktopToolResult,
} from "@gaia/shared/desktop-tools";
import { contextBridge, ipcRenderer } from "electron";
import { IPC } from "../ipc-channels";

/**
 * GAIA renderer API.
 *
 * Each method maps to an IPC channel registered in the main process.
 * The preload script is the **only** bridge — the renderer never
 * touches `ipcRenderer` directly.
 */
const api = {
  /**
   * Get the current operating system platform.
   *
   * @returns `"darwin"`, `"win32"`, `"linux"`, etc.
   */
  getPlatform: (): Promise<NodeJS.Platform> =>
    ipcRenderer.invoke(IPC.getPlatform),

  /**
   * Get the app's semantic version string (from `package.json`).
   *
   * @returns e.g. `"1.2.3"`
   */
  getVersion: (): Promise<string> => ipcRenderer.invoke(IPC.getVersion),

  /** `true` when running inside the Electron shell. */
  isElectron: true,

  /**
   * Signal the main process that the renderer has finished
   * hydrating and is ready to be shown.
   *
   * Triggers the splash → main window transition.
   */
  signalReady: (): void => ipcRenderer.send(IPC.windowReady),

  /**
   * Open a URL in the user's default system browser.
   *
   * Used for OAuth flows where the user must authenticate
   * outside the Electron window.
   *
   * @param url - An `https://` or `http://` URL to open.
   */
  openExternal: (url: string): void => ipcRenderer.send(IPC.openExternal, url),

  /**
   * Subscribe to auth-redirecting events from the main process.
   *
   * Fired immediately after the session cookie is stored and just
   * before the window navigates to the main app, giving the renderer
   * a chance to show a transitional spinner.
   *
   * @param callback - Handler invoked when redirection is imminent.
   * @returns A cleanup function that removes the listener.
   */
  onAuthRedirecting: (callback: () => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent) => callback();
    ipcRenderer.on(IPC.authRedirecting, handler);
    return () => ipcRenderer.removeListener(IPC.authRedirecting, handler);
  },

  /**
   * Notify the main process that the wake word ("Hey GAIA") was
   * detected. Sent by the hidden `/wake-listener` renderer; the main
   * process responds by showing the assistant popup.
   */
  notifyWakeWord: (): void => ipcRenderer.send(IPC.wakeWordDetected),

  /**
   * Ask the main process to dismiss the assistant popup (after the
   * renderer's exit animation is triggered via `popup-deactivate`).
   */
  dismissPopup: (): void => ipcRenderer.send(IPC.popupDismiss),

  /**
   * Resize the assistant popup window to fit its content (Siri-style:
   * composer pill alone, expanding when the conversation appears).
   *
   * @param height - Desired window height in px (clamped by main).
   */
  resizePopup: (height: number): void =>
    ipcRenderer.send(IPC.popupResize, height),

  /**
   * Subscribe to popup activation events.
   *
   * Fired when the assistant popup is shown so the renderer can play
   * its entrance animation. The payload carries how it was summoned
   * ("wake-word" | "shortcut") — the acknowledgment sound is scoped to
   * voice activations.
   *
   * @param callback - Handler invoked with the activation payload.
   * @returns A cleanup function that removes the listener.
   */
  onPopupActivate: (
    callback: (data: { trigger: "wake-word" | "shortcut" }) => void,
  ): (() => void) => {
    const handler = (
      _event: Electron.IpcRendererEvent,
      data: { trigger: "wake-word" | "shortcut" },
    ) => callback(data);
    ipcRenderer.on(IPC.popupActivate, handler);
    return () => ipcRenderer.removeListener(IPC.popupActivate, handler);
  },

  /**
   * Subscribe to popup deactivation events.
   *
   * Fired just before the popup window fades out so the renderer can
   * play its exit animation.
   *
   * @param callback - Handler invoked on deactivation.
   * @returns A cleanup function that removes the listener.
   */
  onPopupDeactivate: (callback: () => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent) => callback();
    ipcRenderer.on(IPC.popupDeactivate, handler);
    return () => ipcRenderer.removeListener(IPC.popupDeactivate, handler);
  },

  /**
   * Execute a backend-requested desktop tool action (screenshot, clipboard,
   * open app/URL, list windows) in the main process and return its result.
   *
   * @param request - The `desktop_tool_request` frame from the chat stream.
   */
  executeDesktopTool: (
    request: DesktopToolRequest,
  ): Promise<DesktopToolResult> =>
    ipcRenderer.invoke(IPC.desktopToolExecute, request),

  /**
   * Report the current microphone / screen-recording permission status.
   */
  getDesktopPermissions: (): Promise<DesktopPermissionStatus> =>
    ipcRenderer.invoke(IPC.desktopToolPermissions),

  /**
   * Open the macOS System Settings privacy pane for a permission, since
   * Screen Recording cannot be prompted for programmatically.
   *
   * @param pane - Which privacy pane to open.
   */
  openPermissionSettings: (pane: DesktopPermissionPane): void =>
    ipcRenderer.send(IPC.desktopToolOpenPermissionSettings, pane),

  /**
   * Trigger the OS permission flow for a pane (real prompt where one
   * exists, Settings deep link otherwise) and return the updated status.
   */
  requestDesktopPermission: (
    pane: DesktopPermissionPane,
  ): Promise<DesktopPermissionStatus> =>
    ipcRenderer.invoke(IPC.desktopToolRequestPermission, pane),

  /**
   * Relaunch the app. Needed after granting Screen Recording — macOS only
   * applies that permission to a freshly launched process.
   */
  relaunchDesktopApp: (): void => ipcRenderer.send(IPC.desktopAppRelaunch),

  /** Current desktop settings plus the available app-icon options. */
  getDesktopSettings: (): Promise<DesktopSettingsSnapshot> =>
    ipcRenderer.invoke(IPC.desktopSettingsGet),

  /**
   * Re-bind the popup global shortcut. Returns the shortcut actually
   * registered after the call (the old one on failure).
   */
  setPopupShortcut: (
    accelerator: string,
  ): Promise<DesktopShortcutUpdateResult> =>
    ipcRenderer.invoke(IPC.desktopSettingsSetShortcut, accelerator),

  /** Switch the dock icon (Arc-style) and persist the choice. */
  setAppIcon: (id: string): Promise<boolean> =>
    ipcRenderer.invoke(IPC.desktopSettingsSetIcon, id),
};

/*
 * Expose APIs to the renderer.
 *
 * When context isolation is enabled (the default), we use
 * `contextBridge` for a secure handoff. Otherwise we fall
 * back to direct `window` assignment (non-isolated legacy mode).
 */
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("electron", electronAPI);
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-expect-error (define in dts)
  window.electron = electronAPI;
  // @ts-expect-error (define in dts)
  window.api = api;
}
