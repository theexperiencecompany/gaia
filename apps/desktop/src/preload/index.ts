import { contextBridge, ipcRenderer } from 'electron';
import { electronAPI } from '@electron-toolkit/preload';

// Custom APIs for renderer
const api = {
  // Get the current platform (darwin, win32, linux)
  getPlatform: (): Promise<NodeJS.Platform> => ipcRenderer.invoke('get-platform'),
  
  // Get the app version
  getVersion: (): Promise<string> => ipcRenderer.invoke('get-version'),
  
  // Check if running in Electron
  isElectron: true,
};

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI);
    contextBridge.exposeInMainWorld('api', api);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI;
  // @ts-ignore (define in dts)
  window.api = api;
}
