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
 * 
 * OAuth:
 * - Registers gaia:// protocol for desktop OAuth deep linking
 * - Handles auth callbacks from system browser
 */

// Enable V8 code caching for faster subsequent startups (~20-30% improvement)
import 'v8-compile-cache';

import { app, shell, BrowserWindow, ipcMain, screen, dialog } from 'electron';
import { join, resolve } from 'node:path';
import { electronApp, optimizer } from '@electron-toolkit/utils';
import { autoUpdater } from 'electron-updater';
import { startNextServer, stopNextServer, getServerUrl } from './server';

// Configure auto-updater
autoUpdater.autoDownload = false; // Don't auto-download, just notify user
autoUpdater.autoInstallOnAppQuit = true; // Install on quit if downloaded

/**
 * Set up auto-updater event handlers
 * Uses native dialogs to notify user about updates
 */
function setupAutoUpdater(): void {
  // Log updater events for debugging
  autoUpdater.on('checking-for-update', () => {
    console.log('[AutoUpdater] Checking for updates...');
  });

  autoUpdater.on('update-available', (info) => {
    console.log('[AutoUpdater] Update available:', info.version);
    
    dialog.showMessageBox({
      type: 'info',
      title: 'Update Available',
      message: `A new version of GAIA is available!`,
      detail: `Version ${info.version} is ready to download. Would you like to update now?`,
      buttons: ['Download Update', 'Later'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) {
        console.log('[AutoUpdater] User chose to download update');
        autoUpdater.downloadUpdate();
      }
    });
  });

  autoUpdater.on('update-not-available', () => {
    console.log('[AutoUpdater] No updates available');
  });

  autoUpdater.on('download-progress', (progress) => {
    console.log(`[AutoUpdater] Download progress: ${progress.percent.toFixed(1)}%`);
  });

  autoUpdater.on('update-downloaded', (info) => {
    console.log('[AutoUpdater] Update downloaded:', info.version);
    
    dialog.showMessageBox({
      type: 'info',
      title: 'Update Ready',
      message: 'Update downloaded successfully!',
      detail: `Version ${info.version} has been downloaded. Restart GAIA to apply the update.`,
      buttons: ['Restart Now', 'Later'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) {
        console.log('[AutoUpdater] User chose to restart and install');
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on('error', (error) => {
    console.error('[AutoUpdater] Error:', error.message);
    // Don't show error dialog to user - updates are non-critical
    // They can manually check for updates or download from website
  });
}

// GPU acceleration and performance flags - must be set before app.ready
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('disable-renderer-backgrounding');

// Register as default protocol handler for gaia:// links
// This must be done before app.ready
if (process.defaultApp) {
  // Development: need to pass the script path
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient('gaia', process.execPath, [resolve(process.argv[1])]);
  }
} else {
  // Production: packaged app
  app.setAsDefaultProtocolClient('gaia');
}

let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;
let serverStarted = false;
let pendingDeepLink: string | null = null;

/**
 * Handle deep link URLs (gaia://...)
 * Called when the app receives a gaia:// URL from the OS
 */
function handleDeepLink(url: string): void {
  console.log('[Main] Deep link received:', url);
  
  try {
    // Parse the URL: gaia://auth/callback?token=xxx
    const urlObj = new URL(url);
    
    if (urlObj.hostname === 'auth' && urlObj.pathname === '/callback') {
      const token = urlObj.searchParams.get('token');
      const error = urlObj.searchParams.get('error');
      
      if (error) {
        console.log('[Main] Auth error:', error);
        // Navigate to login with error
        if (mainWindow && !mainWindow.isDestroyed()) {
          const serverUrl = getServerUrl();
          mainWindow.loadURL(`${serverUrl}/login?error=${encodeURIComponent(error)}`);
        }
      } else if (token) {
        console.log('[Main] Auth token received, storing and navigating');
        // Send token to renderer to store in cookies/localStorage
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('auth-callback', { token });
          // Navigate to main app
          const serverUrl = getServerUrl();
          mainWindow.loadURL(`${serverUrl}/c`);
        }
      }
    }
  } catch (err) {
    console.error('[Main] Failed to parse deep link:', err);
  }
}

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
    alwaysOnTop: false,
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
  
  // Process any pending deep link after window is shown
  if (pendingDeepLink) {
    console.log('[Main] Processing pending deep link');
    handleDeepLink(pendingDeepLink);
    pendingDeepLink = null;
  }
}

// Request single instance lock for deep link handling on Windows/Linux
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  // Another instance is running, quit this one
  app.quit();
} else {
  // Handle second instance (Windows/Linux deep links when app is already running)
  app.on('second-instance', (_event, commandLine) => {
    console.log('[Main] Second instance detected, command line:', commandLine);
    
    // Find the deep link URL in command line args
    const url = commandLine.find(arg => arg.startsWith('gaia://'));
    if (url) {
      handleDeepLink(url);
    }
    
    // Focus the main window
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  // macOS: Handle deep links when app is already running
  app.on('open-url', (event, url) => {
    event.preventDefault();
    console.log('[Main] open-url event:', url);
    
    if (mainWindow && !mainWindow.isDestroyed()) {
      handleDeepLink(url);
    } else {
      // Store for later if window isn't ready yet
      pendingDeepLink = url;
    }
  });

  /**
   * Main startup sequence - optimized for perceived performance
   */
  app.whenReady().then(() => {
    // Set app user model id for Windows
    electronApp.setAppUserModelId('io.heygaia.desktop');

    // STEP 1: Show splash IMMEDIATELY - this is the first thing user sees
    // No blocking operations before this!
    createSplashWindow();

    // STEP 1.5: Set up auto-updater (production only)
    // This runs in background and doesn't block startup
    const isProduction = process.env.NODE_ENV === 'production' || app.isPackaged;
    if (isProduction) {
      setupAutoUpdater();
      // Check for updates after a short delay to not interfere with startup
      setTimeout(() => {
        autoUpdater.checkForUpdates().catch((err) => {
          console.error('[AutoUpdater] Failed to check for updates:', err.message);
        });
      }, 3000); // 3 second delay after startup
    }

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
    
    // Handle open-external requests from renderer (for OAuth)
    ipcMain.on('open-external', (_event, url: string) => {
      console.log('[Main] Opening external URL:', url);
      shell.openExternal(url);
    });

    // STEP 3: Start server AND create window in PARALLEL (non-blocking!)
    // Window creation now polls for server readiness internally
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
    
    // Check for deep link passed via command line (Windows/Linux cold start)
    const deepLinkArg = process.argv.find(arg => arg.startsWith('gaia://'));
    if (deepLinkArg) {
      console.log('[Main] Deep link from command line:', deepLinkArg);
      pendingDeepLink = deepLinkArg;
    }
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
}
