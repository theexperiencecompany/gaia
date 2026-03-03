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
import { contextBridge, ipcRenderer } from "electron";

/** Data payload sent by the main process on a successful OAuth callback. */
interface AuthCallbackData {
  token: string;
}

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
    ipcRenderer.invoke("get-platform"),

  /**
   * Get the app's semantic version string (from `package.json`).
   *
   * @returns e.g. `"1.2.3"`
   */
  getVersion: (): Promise<string> => ipcRenderer.invoke("get-version"),

  /** `true` when running inside the Electron shell. */
  isElectron: true,

  /**
   * Signal the main process that the renderer has finished
   * hydrating and is ready to be shown.
   *
   * Triggers the splash → main window transition.
   */
  signalReady: (): void => ipcRenderer.send("window-ready"),

  /**
   * Open a URL in the user's default system browser.
   *
   * Used for OAuth flows where the user must authenticate
   * outside the Electron window.
   *
   * @param url - An `https://` or `http://` URL to open.
   */
  openExternal: (url: string): void => ipcRenderer.send("open-external", url),

  /**
   * Subscribe to auth-callback events from the main process.
   *
   * The main process fires `auth-callback` after successfully
   * handling a `gaia://auth/callback` deep link.
   *
   * @param callback - Handler invoked with the auth data.
   * @returns A cleanup function that removes the listener.
   */
  onAuthCallback: (
    callback: (data: AuthCallbackData) => void,
  ): (() => void) => {
    const handler = (
      _event: Electron.IpcRendererEvent,
      data: AuthCallbackData,
    ) => callback(data);
    ipcRenderer.on("auth-callback", handler);
    return () => ipcRenderer.removeListener("auth-callback", handler);
  },

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
    ipcRenderer.on("auth-redirecting", handler);
    return () => ipcRenderer.removeListener("auth-redirecting", handler);
  },
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
