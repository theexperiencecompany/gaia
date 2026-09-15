/**
 * macOS permission status + Settings deep links for desktop tools.
 *
 * Screen Recording has no programmatic prompt — the user must grant it in
 * System Settings, so we expose deep links to the exact privacy pane.
 *
 * @module tools/permissions
 */

import { readdir } from "node:fs/promises";
import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
  FolderAccessResult,
  ProtectedFolder,
} from "@gaia/shared/desktop-tools";
import { app, shell, systemPreferences } from "electron";

const PRIVACY_PANE_URLS: Record<DesktopPermissionPane, string> = {
  microphone:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
  screen:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
  accessibility:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
  "full-disk":
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
};

export function getPermissionStatus(): DesktopPermissionStatus {
  if (process.platform !== "darwin") {
    return {
      microphone: "unknown",
      screen: "unknown",
      accessibility: "unknown",
    };
  }
  return {
    microphone: systemPreferences.getMediaAccessStatus("microphone"),
    screen: systemPreferences.getMediaAccessStatus("screen"),
    accessibility: systemPreferences.isTrustedAccessibilityClient(false)
      ? "granted"
      : "denied",
  };
}

/**
 * Trigger the OS permission flow for a pane. Microphone shows a real
 * prompt; accessibility shows the system "grant in Settings" dialog;
 * Screen Recording has no prompt at all — deep-link straight to Settings.
 */
export async function requestPermission(
  pane: DesktopPermissionPane,
): Promise<DesktopPermissionStatus> {
  if (process.platform === "darwin") {
    if (pane === "microphone") {
      await systemPreferences.askForMediaAccess("microphone");
    } else if (pane === "accessibility") {
      systemPreferences.isTrustedAccessibilityClient(true);
    } else {
      openPermissionSettings(pane);
    }
  }
  return getPermissionStatus();
}

export function openPermissionSettings(pane: DesktopPermissionPane): void {
  const url = PRIVACY_PANE_URLS[pane];
  if (url && process.platform === "darwin") {
    shell.openExternal(url);
  }
}

/**
 * Trigger the one-time macOS TCC prompt for a protected folder by reading it.
 * Uses the NS<Folder>FolderUsageDescription strings in the packaged Info.plist.
 *
 * TCC attributes the grant to the app's code signature, so this only prompts
 * and persists reliably on a Developer-ID-signed build; an unsigned dev build
 * may not prompt, or may attribute the grant to the wrong app.
 */
export async function requestFolderAccess(
  folder: ProtectedFolder,
): Promise<FolderAccessResult> {
  if (process.platform !== "darwin") return { folder, granted: true };
  try {
    await readdir(app.getPath(folder));
    return { folder, granted: true };
  } catch {
    return { folder, granted: false };
  }
}
