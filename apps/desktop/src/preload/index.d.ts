import { ElectronAPI } from "@electron-toolkit/preload";

interface AuthCallbackData {
  token: string;
}

declare global {
  interface Window {
    electron: ElectronAPI;
    api: {
      getPlatform: () => Promise<NodeJS.Platform>;
      getVersion: () => Promise<string>;
      isElectron: boolean;
      signalReady: () => void;
      openExternal: (url: string) => void;
      onAuthCallback: (
        callback: (data: AuthCallbackData) => void,
      ) => () => void;
    };
  }
}
