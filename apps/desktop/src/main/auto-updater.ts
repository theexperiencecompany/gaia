/**
 * Auto-Updater Module
 *
 * Manages application update lifecycle using electron-updater.
 * Presents native dialogs to the user for download confirmation
 * and restart prompts. Runs entirely in the background without
 * blocking the main startup flow.
 *
 * @module auto-updater
 */

import { dialog } from "electron";
import pkg from "electron-updater";

const { autoUpdater } = pkg;

/** Don't auto-download updates — let the user decide via dialog. */
autoUpdater.autoDownload = false;

/** Silently install any downloaded update when the app quits. */
autoUpdater.autoInstallOnAppQuit = true;

/**
 * Register all auto-updater event handlers.
 *
 * Hooks into electron-updater's event lifecycle to:
 * - Log update check progress
 * - Prompt the user when an update is available
 * - Show download progress
 * - Offer a restart once the update is downloaded
 * - Silently swallow errors (updates are non-critical)
 */
export function setupAutoUpdater(): void {
  autoUpdater.on("checking-for-update", () => {
    console.log("[AutoUpdater] Checking for updates...");
  });

  autoUpdater.on("update-available", (info) => {
    console.log("[AutoUpdater] Update available:", info.version);

    dialog
      .showMessageBox({
        type: "info",
        title: "Update Available",
        message: "A new version of GAIA is available!",
        detail: `Version ${info.version} is ready to download. Would you like to update now?`,
        buttons: ["Download Update", "Later"],
        defaultId: 0,
        cancelId: 1,
      })
      .then(({ response }) => {
        if (response === 0) {
          console.log("[AutoUpdater] User chose to download update");
          autoUpdater.downloadUpdate();
        }
      });
  });

  autoUpdater.on("update-not-available", () => {
    console.log("[AutoUpdater] No updates available");
  });

  autoUpdater.on("download-progress", (progress) => {
    console.log(
      `[AutoUpdater] Download progress: ${progress.percent.toFixed(1)}%`,
    );
  });

  autoUpdater.on("update-downloaded", (info) => {
    console.log("[AutoUpdater] Update downloaded:", info.version);

    dialog
      .showMessageBox({
        type: "info",
        title: "Update Ready",
        message: "Update downloaded successfully!",
        detail: `Version ${info.version} has been downloaded. Restart GAIA to apply the update.`,
        buttons: ["Restart Now", "Later"],
        defaultId: 0,
        cancelId: 1,
      })
      .then(({ response }) => {
        if (response === 0) {
          console.log("[AutoUpdater] User chose to restart and install");
          autoUpdater.quitAndInstall();
        }
      });
  });

  autoUpdater.on("error", (error) => {
    console.error("[AutoUpdater] Error:", error.message);
  });
}

/**
 * Trigger an update check after a delay.
 *
 * Waits {@link delayMs} milliseconds before checking so the main
 * startup sequence is not impacted. Errors are logged but never
 * surfaced to the user.
 *
 * @param delayMs - Milliseconds to wait before checking (default 3 000)
 */
export function checkForUpdatesAfterDelay(delayMs = 3000): void {
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((err) => {
      console.error("[AutoUpdater] Failed to check for updates:", err.message);
    });
  }, delayMs);
}
