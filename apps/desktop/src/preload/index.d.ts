import { ElectronAPI } from "@electron-toolkit/preload";
import type {
  AddOptions,
  BridgeInvokeResult,
  BridgeStatus,
  DeviceServerView,
} from "@gaia/shared/bridge-core";
import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  DesktopSettingsSnapshot,
  DesktopShortcutUpdateResult,
  DesktopToolRequest,
  DesktopToolResult,
  FolderAccessResult,
  ProtectedFolder,
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
      requestFolderAccess: (
        folder: ProtectedFolder,
      ) => Promise<FolderAccessResult>;
      relaunchDesktopApp: () => void;
      getDesktopSettings: () => Promise<DesktopSettingsSnapshot>;
      setPopupShortcut: (
        accelerator: string,
      ) => Promise<DesktopShortcutUpdateResult>;
      setAppIcon: (id: string) => Promise<boolean>;
      bridge: {
        pair: () => Promise<BridgeInvokeResult<BridgeStatus>>;
        status: () => Promise<BridgeInvokeResult<BridgeStatus>>;
        start: () => Promise<BridgeInvokeResult<BridgeStatus>>;
        stop: () => Promise<BridgeInvokeResult<BridgeStatus>>;
        listServers: () => Promise<BridgeInvokeResult<DeviceServerView[]>>;
        addServer: (
          opts: AddOptions,
        ) => Promise<BridgeInvokeResult<DeviceServerView[]>>;
        retryServer: (
          key: string,
        ) => Promise<BridgeInvokeResult<DeviceServerView[]>>;
        removeServer: (
          key: string,
        ) => Promise<BridgeInvokeResult<DeviceServerView[]>>;
        onStatusChanged: (
          callback: (status: BridgeStatus) => void,
        ) => () => void;
        onServersChanged: (
          callback: (servers: DeviceServerView[]) => void,
        ) => () => void;
      };
    };
  }
}
