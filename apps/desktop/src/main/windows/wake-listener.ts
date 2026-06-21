/**
 * Wake-Word Listener Window Module
 *
 * A hidden, never-shown renderer that runs the on-device "Hey GAIA"
 * wake-word pipeline (`/wake-listener` web route) for the lifetime of
 * the app. On detection the route sends the `wake-word-detected` IPC
 * message, which the main process answers by showing the assistant
 * popup.
 *
 * @module windows/wake-listener
 */

import { join } from "node:path";
import { BrowserWindow, systemPreferences } from "electron";
import { loadAppRoute } from "./load-url";

/** Reference to the listener window (if created). */
let listenerWindow: BrowserWindow | null = null;

/**
 * Request microphone access on macOS without blocking — the OS dialog
 * can stay open indefinitely. A denial only disables the wake word;
 * the popup remains reachable via the global shortcut.
 */
function requestMicrophoneAccess(): void {
  if (process.platform !== "darwin") return;

  systemPreferences
    .askForMediaAccess("microphone")
    .then((granted) => {
      if (!granted) {
        console.warn(
          "[Main] Microphone access denied — wake word disabled (shortcut still works)",
        );
      }
    })
    .catch((err) => {
      console.error("[Main] Microphone access request failed:", err);
    });
}

/**
 * Create the hidden wake-word listener window and start loading the
 * `/wake-listener` route in the background.
 *
 * @param serverReady - Returns `true` once the production server is up.
 */
export async function createWakeListenerWindow(
  serverReady: () => boolean,
): Promise<void> {
  requestMicrophoneAccess();

  listenerWindow = new BrowserWindow({
    width: 0,
    height: 0,
    show: false,
    skipTaskbar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
      // Keep the audio pipeline running while hidden.
      backgroundThrottling: false,
    },
  });

  listenerWindow.on("closed", () => {
    listenerWindow = null;
  });

  await loadAppRoute(listenerWindow, "/wake-listener", serverReady);
}

/** Destroy the listener window (app shutdown). */
export function destroyWakeListenerWindow(): void {
  if (listenerWindow && !listenerWindow.isDestroyed()) {
    listenerWindow.destroy();
    listenerWindow = null;
  }
}
