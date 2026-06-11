/**
 * IPC Handler Registration Module
 *
 * Registers all `ipcMain` handlers that the renderer (via the
 * preload script) can invoke. Keeps IPC surface area in one
 * place for easy auditing.
 *
 * @module ipc
 */

import type {
  DesktopPermissionPane,
  DesktopToolRequest,
} from "@gaia/shared/desktop-tools";
import { app, ipcMain, shell } from "electron";
import { dispatchDesktopTool } from "./tools";
import {
  getPermissionStatus,
  openPermissionSettings,
} from "./tools/permissions";
import {
  dismissAssistantPopup,
  resizeAssistantPopup,
  showAssistantPopup,
} from "./windows/assistant-popup";
import { getMainWindow } from "./windows/main";

/**
 * Register all main-process IPC handlers.
 *
 * Handlers registered here:
 * - `get-platform`        — returns `process.platform`
 * - `get-version`         — returns the app version string
 * - `window-ready`        — renderer signals it has finished hydrating
 * - `open-external`       — opens a URL in the default system browser
 * - `wake-word-detected`  — listener heard "Hey GAIA"; show the popup
 * - `popup-dismiss`       — popup renderer requested dismissal
 * - `desktop-tool:execute` — run a backend-requested action (screenshot, ...)
 * - `desktop-tool:permissions` — report mic/screen permission status
 * - `desktop-tool:open-permission-settings` — deep-link a privacy pane
 *
 * @param onWindowReady - Callback invoked when the renderer sends `window-ready`.
 */
export function registerIpcHandlers(onWindowReady: () => void): void {
  ipcMain.handle("get-platform", () => process.platform);
  ipcMain.handle("get-version", () => app.getVersion());

  ipcMain.on("window-ready", (event) => {
    // Secondary windows (assistant popup, wake listener) load app routes
    // too — only the main window's renderer may drive the splash swap.
    const main = getMainWindow();
    if (main && event.sender !== main.webContents) return;

    console.log("[Main] Renderer signaled ready");
    onWindowReady();
  });

  ipcMain.on("open-external", (_event, url: string) => {
    console.log("[Main] Opening external URL:", url);
    if (url.startsWith("https://") || url.startsWith("http://")) {
      shell.openExternal(url);
    }
  });

  ipcMain.on("wake-word-detected", () => {
    console.log("[Main] Wake word detected");
    showAssistantPopup("wake-word");
  });

  ipcMain.on("popup-dismiss", () => {
    dismissAssistantPopup();
  });

  ipcMain.on("popup-resize", (_event, height: number) => {
    if (typeof height === "number" && Number.isFinite(height)) {
      resizeAssistantPopup(height);
    }
  });

  ipcMain.handle(
    "desktop-tool:execute",
    (_event, request: DesktopToolRequest) => dispatchDesktopTool(request),
  );

  ipcMain.handle("desktop-tool:permissions", () => getPermissionStatus());

  ipcMain.on(
    "desktop-tool:open-permission-settings",
    (_event, pane: DesktopPermissionPane) => {
      openPermissionSettings(pane);
    },
  );
}
