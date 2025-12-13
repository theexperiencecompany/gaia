import { app, shell, BrowserWindow, ipcMain } from 'electron';
import { join } from 'node:path';
import { electronApp, optimizer, is } from '@electron-toolkit/utils';
import { startNextServer, stopNextServer, getServerUrl } from './server';

let mainWindow: BrowserWindow | null = null;

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#000000',
    icon: join(__dirname, '../../resources/icons/256x256.png'),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show();
  });

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url);
    return { action: 'deny' };
  });

  // Load the Next.js server URL
  const serverUrl = getServerUrl();
  if (is.dev) {
    // In development, wait for web dev server then load it
    const devUrl = 'http://localhost:3000';
    const waitOn = await import('wait-on');
    console.log('Waiting for web dev server at', devUrl);
    await waitOn.default({ resources: [devUrl], timeout: 30000 });
    console.log('Web dev server ready, loading...');
    mainWindow.loadURL(devUrl);
  } else {
    // In production, use the bundled Next.js server
    mainWindow.loadURL(serverUrl);
  }
}

app.whenReady().then(async () => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('io.heygaia.desktop');

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window);
  });

  // IPC handlers
  ipcMain.handle('get-platform', () => process.platform);
  ipcMain.handle('get-version', () => app.getVersion());

  // Start the Next.js server in production
  if (!is.dev) {
    await startNextServer();
  }

  createWindow();

  app.on('activate', () => {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows are closed, except on macOS.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Cleanup on quit
app.on('before-quit', async () => {
  await stopNextServer();
});
