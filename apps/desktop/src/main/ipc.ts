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
  DesktopSettingsSnapshot,
  DesktopToolRequest,
  ProtectedFolder,
} from "@gaia/shared/desktop-tools";
import { app, ipcMain, shell } from "electron";
import { IPC } from "../ipc-channels";
import { listAppIcons, setAppIcon } from "./app-icon";
import { registerBridgeIpcHandlers } from "./bridge/ipc";
import { updatePopupShortcut } from "./popup-shortcut";
import { getDesktopSettings } from "./settings";
import { dispatchDesktopTool } from "./tools";
import {
  getPermissionStatus,
  openPermissionSettings,
  requestFolderAccess,
  requestPermission,
} from "./tools/permissions";
import {
  dismissAssistantPopup,
  resizeAssistantPopup,
  showAssistantPopup,
} from "./windows/assistant-popup";
import { getMainWindow } from "./windows/main";

/**
 * Register all main-process IPC handlers: platform/version info, the renderer's
 * `window-ready` signal, opening external URLs, wake-word popup show/dismiss,
 * and the desktop-tool bridge (execute, permissions, permission-settings deep link).
 */
export function registerIpcHandlers(onWindowReady: () => void): void {
  ipcMain.handle(IPC.getPlatform, () => process.platform);
  ipcMain.handle(IPC.getVersion, () => app.getVersion());

  ipcMain.on(IPC.windowReady, (event) => {
    // Secondary windows (assistant popup, wake listener) load app routes
    // too — only the main window's renderer may drive the splash swap.
    const main = getMainWindow();
    if (main && event.sender !== main.webContents) return;

    console.log("[Main] Renderer signaled ready");
    onWindowReady();
  });

  ipcMain.on(IPC.openExternal, (_event, url: unknown) => {
    if (typeof url !== "string") return;
    console.log("[Main] Opening external URL:", url);
    if (url.startsWith("https://") || url.startsWith("http://")) {
      void shell.openExternal(url);
    }
  });

  ipcMain.on(IPC.wakeWordDetected, () => {
    console.log("[Main] Wake word detected");
    showAssistantPopup("wake-word");
  });

  ipcMain.on(IPC.popupDismiss, () => {
    dismissAssistantPopup();
  });

  ipcMain.on(IPC.popupResize, (_event, height: number) => {
    if (typeof height === "number" && Number.isFinite(height)) {
      resizeAssistantPopup(height);
    }
  });

  ipcMain.handle(
    IPC.desktopToolExecute,
    (_event, request: DesktopToolRequest) => dispatchDesktopTool(request),
  );

  ipcMain.handle(IPC.desktopToolPermissions, () => getPermissionStatus());

  ipcMain.handle(
    IPC.desktopToolRequestPermission,
    (_event, pane: DesktopPermissionPane) => requestPermission(pane),
  );

  ipcMain.on(
    IPC.desktopToolOpenPermissionSettings,
    (_event, pane: DesktopPermissionPane) => {
      openPermissionSettings(pane);
    },
  );

  ipcMain.handle(
    IPC.desktopToolRequestFolderAccess,
    (_event, folder: ProtectedFolder) => requestFolderAccess(folder),
  );

  // Screen Recording grants only apply after relaunch — TCC keeps the
  // running process's old verdict, so the settings page offers a restart.
  ipcMain.on(IPC.desktopAppRelaunch, () => {
    app.relaunch();
    app.exit(0);
  });

  ipcMain.handle(
    IPC.desktopSettingsGet,
    (): DesktopSettingsSnapshot => ({
      settings: getDesktopSettings(),
      icons: listAppIcons(),
    }),
  );

  ipcMain.handle(
    IPC.desktopSettingsSetShortcut,
    (_event, accelerator: string) => updatePopupShortcut(String(accelerator)),
  );

  ipcMain.handle(IPC.desktopSettingsSetIcon, (_event, id: string) =>
    setAppIcon(String(id)),
  );

  // Device bridge: pair/status/start/stop + server management, and the
  // main→renderer status push. Configures the host state dir up front so the
  // reads work immediately (no tunnel auto-start — Phase 4 owns launch policy).
  registerBridgeIpcHandlers();
}
