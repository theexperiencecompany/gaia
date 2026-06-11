/**
 * macOS permission status + Settings deep links for desktop tools.
 *
 * Screen Recording has no programmatic prompt — the user must grant it in
 * System Settings, so we expose deep links to the exact privacy pane.
 *
 * @module tools/permissions
 */

import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
} from "@gaia/shared/desktop-tools";
import { shell, systemPreferences } from "electron";

const PRIVACY_PANE_URLS: Record<DesktopPermissionPane, string> = {
  microphone:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
  screen:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
};

export function getPermissionStatus(): DesktopPermissionStatus {
  if (process.platform !== "darwin") {
    return { microphone: "unknown", screen: "unknown" };
  }
  return {
    microphone: systemPreferences.getMediaAccessStatus("microphone"),
    screen: systemPreferences.getMediaAccessStatus("screen"),
  };
}

export function openPermissionSettings(pane: DesktopPermissionPane): void {
  const url = PRIVACY_PANE_URLS[pane];
  if (url && process.platform === "darwin") {
    shell.openExternal(url);
  }
}
