/**
 * GAIA Desktop - Main Process
 * 
 * Performance-optimized startup flow:
 * 1. Show splash screen IMMEDIATELY (no blocking operations before this)
 * 2. Start Next.js server in background (non-blocking)
 * 3. Create main window (hidden) while server starts IN PARALLEL
 * 4. Wait for renderer to signal ready, then show main window
 * 
 * Key optimizations:
 * - V8 code caching for faster subsequent startups
 * - GPU acceleration flags for faster rendering
 * - Parallel server + window creation (no blocking)
 * - Reduced timeouts for better perceived performance
 */

// Enable V8 code caching for faster subsequent startups (~20-30% improvement)
import 'v8-compile-cache';

import { app, shell, BrowserWindow, ipcMain, screen } from 'electron';
import { join } from 'node:path';
import { electronApp, optimizer } from '@electron-toolkit/utils';
import { startNextServer, stopNextServer, getServerUrl } from './server';

// GPU acceleration and performance flags - must be set before app.ready
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('disable-renderer-backgrounding');

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
    show: true, // Show immediately - splash is simple enough to render instantly
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
  // Window shows immediately (show: true) - no waiting for dom-ready
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
    // In production, wait for server to be ready (polling) then load
    // This allows parallel server + window creation
    const waitForServerAndLoad = async (): Promise<void> => {
      const serverUrl = getServerUrl();
      const maxAttempts = 50; // 50 * 100ms = 5 seconds max wait
      
      for (let i = 0; i < maxAttempts; i++) {
        if (serverStarted) {
          console.log('[Main] Server is ready, loading URL:', serverUrl);
          mainWindow?.loadURL(serverUrl);
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      
      // Fallback: try loading anyway after timeout
      console.log('[Main] Server wait timeout, attempting to load anyway');
      mainWindow?.loadURL(serverUrl);
    };
    
    waitForServerAndLoad().catch(console.error);
  } else {
    // In development, use same non-blocking polling pattern
    // Poll for dev server instead of blocking with wait-on
    const waitForDevServerAndLoad = async (): Promise<void> => {
      const devUrl = 'http://localhost:3000';
      const maxAttempts = 100; // 100 * 100ms = 10 seconds max wait
      
      console.log('[Main] Waiting for dev server at', devUrl);
      
      for (let i = 0; i < maxAttempts; i++) {
        try {
          // Quick TCP check to see if server is up
          const net = await import('node:net');
          const isReady = await new Promise<boolean>((resolve) => {
            const socket = net.createConnection({ port: 3000, host: 'localhost' });
            socket.once('connect', () => { socket.destroy(); resolve(true); });
            socket.once('error', () => { socket.destroy(); resolve(false); });
            setTimeout(() => { socket.destroy(); resolve(false); }, 100);
          });
          
          if (isReady) {
            console.log('[Main] Dev server ready, loading...');
            mainWindow?.loadURL(devUrl);
            return;
          }
        } catch {
          // Ignore errors, keep polling
        }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      
      // Fallback: try loading anyway
      console.log('[Main] Dev server wait timeout, attempting to load anyway');
      mainWindow?.loadURL(devUrl);
    };
    
    waitForDevServerAndLoad().catch(console.error);
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

  // STEP 3: Start server AND create window in PARALLEL (non-blocking!)
  // Window creation now polls for server readiness internally
  const isProduction = process.env.NODE_ENV === 'production' || app.isPackaged;
  
  if (isProduction) {
    // Start server in background - don't block on it
    startNextServer()
      .then(() => {
        serverStarted = true;
        console.log('[Main] Next.js server started');
      })
      .catch((error) => {
        console.error('[Main] Failed to start Next.js server:', error);
        // Still set serverStarted to allow window to attempt loading
        // This enables error recovery - window will show error page or retry
        serverStarted = true;
      });
  }
  
  // Create window IMMEDIATELY in parallel with server start
  // Window's loading logic will poll until server is ready
  createMainWindow().catch(console.error);

  // STEP 4: Fallback timeout - show window even if renderer doesn't signal
  // 10s allows for: server startup (~3-8s) + window load (~1-2s) + renderer hydration (~1-2s)
  setTimeout(() => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      console.log('[Main] Fallback: showing main window after timeout');
      showMainWindow();
    }
  }, 10000); // 10 second fallback

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
