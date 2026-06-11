/**
 * Arc-style switchable app icon (macOS dock).
 *
 * Icon PNGs live in `resources/app-icons/<id>.png`; entries whose file is
 * missing are hidden from the picker, so shipping a new icon is just
 * dropping a PNG in that folder and adding a registry row here.
 *
 * @module app-icon
 */

import { existsSync } from "node:fs";
import { join } from "node:path";
import type { DesktopAppIconOption } from "@gaia/shared/desktop-tools";
import { app, nativeImage } from "electron";
import {
  DEFAULT_APP_ICON,
  getDesktopSettings,
  updateDesktopSettings,
} from "./settings";

const PREVIEW_SIZE = 128;

interface AppIconEntry {
  id: string;
  label: string;
  /** Path relative to the resources root. */
  file: string;
}

const APP_ICON_REGISTRY: AppIconEntry[] = [
  { id: DEFAULT_APP_ICON, label: "GAIA", file: "icons/512x512.png" },
  { id: "neon", label: "Neon", file: "app-icons/neon.png" },
  { id: "chrome", label: "Chrome", file: "app-icons/chrome.png" },
  { id: "glass", label: "Glass", file: "app-icons/glass.png" },
  { id: "blueprint", label: "Blueprint", file: "app-icons/blueprint.png" },
  { id: "retro", label: "Retro", file: "app-icons/retro.png" },
];

function resourcePath(relative: string): string {
  return app.isPackaged
    ? join(process.resourcesPath, relative)
    : join(__dirname, "../../resources", relative);
}

function iconFilePath(id: string): string | null {
  const entry = APP_ICON_REGISTRY.find((icon) => icon.id === id);
  if (!entry) return null;
  const path = resourcePath(entry.file);
  return existsSync(path) ? path : null;
}

/** Picker options for every icon whose PNG actually exists. */
export function listAppIcons(): DesktopAppIconOption[] {
  const options: DesktopAppIconOption[] = [];
  for (const entry of APP_ICON_REGISTRY) {
    const path = iconFilePath(entry.id);
    if (!path) continue;
    const preview = nativeImage
      .createFromPath(path)
      .resize({ width: PREVIEW_SIZE });
    if (preview.isEmpty()) continue;
    options.push({
      id: entry.id,
      label: entry.label,
      preview: preview.toDataURL(),
    });
  }
  return options;
}

/** Apply an icon to the dock and persist the choice. */
export function setAppIcon(id: string): boolean {
  const path = iconFilePath(id);
  if (!path) return false;
  applyDockIcon(path);
  updateDesktopSettings({ appIcon: id });
  return true;
}

/** Re-apply the persisted icon at startup (dock resets between runs). */
export function applyPersistedAppIcon(): void {
  const { appIcon } = getDesktopSettings();
  if (appIcon === DEFAULT_APP_ICON) return;
  const path = iconFilePath(appIcon);
  if (path) applyDockIcon(path);
}

function applyDockIcon(path: string): void {
  if (process.platform !== "darwin" || !app.dock) return;
  const image = nativeImage.createFromPath(path);
  if (!image.isEmpty()) app.dock.setIcon(image);
}
