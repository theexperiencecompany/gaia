import { electronAPI } from "@electron-toolkit/preload";
import { contextBridge, ipcRenderer } from "electron";

// Auth callback data type
interface AuthCallbackData {
  token: string;
}

// Custom APIs for renderer
const api = {
  // Get the current platform (darwin, win32, linux)
  getPlatform: (): Promise<NodeJS.Platform> =>
    ipcRenderer.invoke("get-platform"),

  // Get the app version
  getVersion: (): Promise<string> => ipcRenderer.invoke("get-version"),

  // Check if running in Electron
  isElectron: true,

  // Signal that the renderer is ready (for splash screen)
  signalReady: (): void => ipcRenderer.send("window-ready"),

  // Open URL in system browser (for OAuth)
  openExternal: (url: string): void => ipcRenderer.send("open-external", url),

  // Listen for auth callback from deep link
  onAuthCallback: (
    callback: (data: AuthCallbackData) => void,
  ): (() => void) => {
    const handler = (
      _event: Electron.IpcRendererEvent,
      data: AuthCallbackData,
    ) => callback(data);
    ipcRenderer.on("auth-callback", handler);
    // Return cleanup function
    return () => ipcRenderer.removeListener("auth-callback", handler);
  },
};

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
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
