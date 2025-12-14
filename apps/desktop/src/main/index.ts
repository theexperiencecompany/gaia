/**
 * GAIA Desktop - Main Process
 * 
 * Performance-optimized startup flow:
 * 1. Show splash screen IMMEDIATELY (no blocking operations before this)
 * 2. Start Next.js server in background (non-blocking)
 * 3. Create main window (hidden) while server starts
 * 4. Wait for renderer to signal ready, then show main window
 * 
 * Key optimizations from Electron docs:
 * - Defer module loading where possible
 * - Never block the main process with sync operations
 * - Show visual feedback immediately
 */

import { app, shell, BrowserWindow, ipcMain, screen } from 'electron';
import { join } from 'node:path';
import { electronApp, optimizer } from '@electron-toolkit/utils';
import { startNextServer, stopNextServer, getServerUrl } from './server';

let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;
let serverStarted = false;

/**
 * Create fullscreen splash screen with vibrancy
 * This MUST be the first visual operation - no blocking code before this
 */
function createSplashWindow(): void {
  // Get primary display for fullscreen splash
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  splashWindow = new BrowserWindow({
    width,
    height,
    x: 0,
    y: 0,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    // closable must be true for destroy() to work
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: false,
    show: false, // Show after content loads for smoother appearance
    hasShadow: false,
    // macOS vibrancy for native blur effect
    vibrancy: process.platform === 'darwin' ? 'under-window' : undefined,
    visualEffectState: 'active',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // Load splash HTML
  const splashPath = app.isPackaged
    ? join(process.resourcesPath, 'splash.html')
    : join(__dirname, '../../resources/splash.html');

  splashWindow.loadFile(splashPath);

  // Show as soon as DOM is ready (faster than waiting for full load)
  splashWindow.webContents.on('dom-ready', () => {
    splashWindow?.show();
  });
}

/**
 * Close and destroy splash window
 */
function closeSplashWindow(): void {
  if (splashWindow && !splashWindow.isDestroyed()) {
    // Use destroy() instead of close() to ensure it's removed
    splashWindow.destroy();
    splashWindow = null;
    console.log('[Main] Splash window destroyed');
  }
}

/**
 * Create the main application window
 */
async function createMainWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false, // Hidden until renderer signals ready
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

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url);
    return { action: 'deny' };
  });

  // Determine URL to load
  const isProduction = process.env.NODE_ENV === 'production' || app.isPackaged;
  
  if (isProduction) {
    // In production, load from bundled Next.js server
    const serverUrl = getServerUrl();
    mainWindow.loadURL(serverUrl);
  } else {
    // In development, wait for dev server
    // Defer wait-on import since it's only needed in dev
    const waitOn = await import('wait-on');
    const devUrl = 'http://localhost:3000';
    console.log('Waiting for web dev server at', devUrl);
    await waitOn.default({ resources: [devUrl], timeout: 30000 });
    console.log('Web dev server ready, loading...');
    mainWindow.loadURL(devUrl);
  }
}

/**
 * Show main window and close splash
 * Called when renderer signals it's ready via IPC
 */
function showMainWindow(): void {
  console.log('[Main] showMainWindow called');
  
  if (!mainWindow || mainWindow.isDestroyed()) {
    console.log('[Main] Main window not available');
    return;
  }
  
  // Maximize for fullscreen-like experience, then show
  mainWindow.maximize();
  mainWindow.show();
  mainWindow.focus();
  console.log('[Main] Main window shown and focused');
  
  // Close splash AFTER main window is visible to avoid flicker
  console.log('[Main] About to close splash window');
  closeSplashWindow();
}

/**
 * Main startup sequence - optimized for perceived performance
 */
app.whenReady().then(() => {
  // Set app user model id for Windows
  electronApp.setAppUserModelId('io.heygaia.desktop');

  // STEP 1: Show splash IMMEDIATELY - this is the first thing user sees
  // No blocking operations before this!
  createSplashWindow();

  // Watch shortcuts in development
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window);
  });

  // STEP 2: Register IPC handlers (fast, non-blocking)
  ipcMain.handle('get-platform', () => process.platform);
  ipcMain.handle('get-version', () => app.getVersion());
  
  // Handle window-ready signal from renderer
  ipcMain.on('window-ready', () => {
    console.log('[Main] Renderer signaled ready');
    showMainWindow();
  });

  // STEP 3: Start Next.js server in background (non-blocking!)
  // Don't await this - let it run in parallel
  const isProduction = process.env.NODE_ENV === 'production' || app.isPackaged;
  if (isProduction) {
    startNextServer()
      .then(() => {
        serverStarted = true;
        console.log('[Main] Next.js server started');
        // Now create main window that will load from server
        createMainWindow().catch(console.error);
      })
      .catch((error) => {
        console.error('[Main] Failed to start Next.js server:', error);
        // Still try to create window - might recover
        createMainWindow().catch(console.error);
      });
  } else {
    // In development, just create window (will wait for dev server internally)
    createMainWindow().catch(console.error);
  }

  // STEP 4: Fallback timeout - show window even if renderer doesn't signal
  // This prevents the app from being stuck on splash if something goes wrong
  setTimeout(() => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      console.log('[Main] Fallback: showing main window after timeout');
      showMainWindow();
    }
  }, 15000); // 15 second fallback

  // macOS: re-create window when dock icon clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow().catch(console.error);
    }
  });
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Cleanup on quit
app.on('before-quit', () => {
  stopNextServer().catch(console.error);
});
