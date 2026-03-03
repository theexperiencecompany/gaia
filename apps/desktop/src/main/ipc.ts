/**
 * IPC Handler Registration Module
 *
 * Registers all `ipcMain` handlers that the renderer (via the
 * preload script) can invoke. Keeps IPC surface area in one
 * place for easy auditing.
 *
 * @module ipc
 */

import { app, ipcMain, shell } from "electron";

/**
 * Register all main-process IPC handlers.
 *
 * Handlers registered here:
 * - `get-platform`   — returns `process.platform`
 * - `get-version`    — returns the app version string
 * - `window-ready`   — renderer signals it has finished hydrating
 * - `open-external`  — opens a URL in the default system browser
 *
 * @param onWindowReady - Callback invoked when the renderer sends `window-ready`.
 */
export function registerIpcHandlers(onWindowReady: () => void): void {
  ipcMain.handle("get-platform", () => process.platform);
  ipcMain.handle("get-version", () => app.getVersion());

  ipcMain.on("window-ready", () => {
    console.log("[Main] Renderer signaled ready");
    onWindowReady();
  });

  ipcMain.on("open-external", (_event, url: string) => {
    console.log("[Main] Opening external URL:", url);
    if (url.startsWith("https://") || url.startsWith("http://")) {
      shell.openExternal(url);
    }
  });
}
