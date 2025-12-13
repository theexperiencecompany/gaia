import { ElectronAPI } from '@electron-toolkit/preload';

declare global {
  interface Window {
    electron: ElectronAPI;
    api: {
      getPlatform: () => Promise<NodeJS.Platform>;
      getVersion: () => Promise<string>;
      isElectron: boolean;
    };
  }
}
