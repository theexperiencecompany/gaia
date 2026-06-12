import { ElectronAPI } from "@electron-toolkit/preload";
import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  DesktopSettingsSnapshot,
  DesktopShortcutUpdateResult,
  DesktopToolRequest,
  DesktopToolResult,
} from "@gaia/shared/desktop-tools";

declare global {
  interface Window {
    electron: ElectronAPI;
    api: {
      getPlatform: () => Promise<NodeJS.Platform>;
      getVersion: () => Promise<string>;
      isElectron: boolean;
      signalReady: () => void;
      openExternal: (url: string) => void;
      onAuthRedirecting: (callback: () => void) => () => void;
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
    };
  }
}
