/**
 * IPC channel names — the single source of truth for every `ipcMain` /
 * `ipcRenderer` channel string.
 *
 * Both the main process (`ipc.ts`) and the preload bridge (`preload/index.ts`)
 * import from here so a renamed or mistyped channel is a compile error rather
 * than a silent runtime no-op (a one-sided typo just never matches).
 *
 * @module ipc-channels
 */

export const IPC = {
  getPlatform: "get-platform",
  getVersion: "get-version",
  windowReady: "window-ready",
  openExternal: "open-external",
  authRedirecting: "auth-redirecting",
  wakeWordDetected: "wake-word-detected",
  popupDismiss: "popup-dismiss",
  popupResize: "popup-resize",
  popupActivate: "popup-activate",
  popupDeactivate: "popup-deactivate",
  desktopToolExecute: "desktop-tool:execute",
  desktopToolPermissions: "desktop-tool:permissions",
  desktopToolRequestPermission: "desktop-tool:request-permission",
  desktopToolOpenPermissionSettings: "desktop-tool:open-permission-settings",
  desktopToolRequestFolderAccess: "desktop-tool:request-folder-access",
  desktopAppRelaunch: "desktop-app:relaunch",
  desktopSettingsGet: "desktop-settings:get",
  desktopSettingsSetShortcut: "desktop-settings:set-shortcut",
  desktopSettingsSetIcon: "desktop-settings:set-icon",
  bridgePair: "bridge:pair",
  bridgeStatus: "bridge:status",
  bridgeStart: "bridge:start",
  bridgeStop: "bridge:stop",
  bridgeListServers: "bridge:list-servers",
  bridgeAddServer: "bridge:add-server",
  bridgeRemoveServer: "bridge:remove-server",
  bridgeRetryServer: "bridge:retry-server",
  bridgeStatusChanged: "bridge:status-changed",
  bridgeServersChanged: "bridge:servers-changed",
} as const;
