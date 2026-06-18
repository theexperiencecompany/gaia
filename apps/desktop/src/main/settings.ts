/**
 * Desktop-local settings, persisted as JSON in the app's userData dir.
 *
 * These are per-machine preferences (popup shortcut, dock icon) — they
 * never sync to the backend.
 *
 * @module settings
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { DesktopSettings } from "@gaia/shared/desktop-tools";
import { app } from "electron";

export const DEFAULT_POPUP_SHORTCUT = "CommandOrControl+Shift+G";
export const DEFAULT_APP_ICON = "default";

const SETTINGS_FILE = "desktop-settings.json";

const DEFAULT_SETTINGS: DesktopSettings = {
  popupShortcut: DEFAULT_POPUP_SHORTCUT,
  appIcon: DEFAULT_APP_ICON,
};

let cached: DesktopSettings | null = null;

function settingsPath(): string {
  return join(app.getPath("userData"), SETTINGS_FILE);
}

export function getDesktopSettings(): DesktopSettings {
  if (cached) return cached;
  try {
    const raw = JSON.parse(readFileSync(settingsPath(), "utf-8"));
    cached = {
      popupShortcut:
        typeof raw.popupShortcut === "string" && raw.popupShortcut
          ? raw.popupShortcut
          : DEFAULT_SETTINGS.popupShortcut,
      appIcon:
        typeof raw.appIcon === "string" && raw.appIcon
          ? raw.appIcon
          : DEFAULT_SETTINGS.appIcon,
    };
  } catch {
    cached = { ...DEFAULT_SETTINGS };
  }
  return cached;
}

export function updateDesktopSettings(
  patch: Partial<DesktopSettings>,
): DesktopSettings {
  const next = { ...getDesktopSettings(), ...patch };
  cached = next;
  try {
    const path = settingsPath();
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(next, null, 2)}\n`, "utf-8");
  } catch (err) {
    console.error("[Main] Failed to persist desktop settings:", err);
  }
  return next;
}
