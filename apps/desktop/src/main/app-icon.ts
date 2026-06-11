/**
 * Arc-style switchable app icon (macOS dock).
 *
 * Icon PNGs live in `resources/app-icons/<id>.png`; entries whose file is
 * missing are hidden from the picker, so shipping a new icon is just
 * dropping a PNG in that folder and adding a registry row here.
 *
 * @module app-icon
 */

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
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
  { id: "glow", label: "Glow", file: "app-icons/glow.png" },
  { id: "metal", label: "Metal", file: "app-icons/metal.png" },
  { id: "g3", label: "G3", file: "app-icons/g3.png" },
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

/** Apply an icon to the dock + Finder and persist the choice. */
export function setAppIcon(id: string): boolean {
  const path = iconFilePath(id);
  if (!path) return false;
  applyDockIcon(path);
  applyFinderIcon(id === DEFAULT_APP_ICON ? null : path);
  updateDesktopSettings({ appIcon: id });
  return true;
}

/**
 * Re-apply the persisted icon at startup — the dock resets between runs
 * and reinstalls replace the bundle, wiping the Finder icon xattr.
 */
export function applyPersistedAppIcon(): void {
  const { appIcon } = getDesktopSettings();
  if (appIcon === DEFAULT_APP_ICON) return;
  const path = iconFilePath(appIcon);
  if (path) {
    applyDockIcon(path);
    applyFinderIcon(path);
  }
}

function applyDockIcon(path: string): void {
  if (process.platform !== "darwin" || !app.dock) return;
  const image = nativeImage.createFromPath(path);
  if (!image.isEmpty()) app.dock.setIcon(image);
}

/**
 * NSWorkspace.setIcon via JXA: stores the icon as a Finder xattr on the
 * bundle so the .app in /Applications shows it too. The xattr lives
 * outside the signed contents, so the code signature stays valid —
 * never swap Contents/Resources/icon.icns instead, that breaks the seal.
 * Passing `null` removes the custom icon, restoring the bundled one.
 */
const FINDER_ICON_JXA = `
ObjC.import("AppKit");
function run(argv) {
  const appPath = argv[0];
  const img = argv.length > 1
    ? $.NSImage.alloc.initWithContentsOfFile(argv[1])
    : $();
  return $.NSWorkspace.sharedWorkspace.setIconForFileOptions(img, appPath, 0);
}`;

function applyFinderIcon(iconPath: string | null): void {
  if (process.platform !== "darwin" || !app.isPackaged) return;
  const bundlePath = resolve(app.getPath("exe"), "../../..");
  if (!bundlePath.endsWith(".app")) return;
  const args = ["-l", "JavaScript", "-e", FINDER_ICON_JXA, bundlePath];
  if (iconPath) args.push(iconPath);
  // Absolute path to the SIP-protected system binary — never resolve via
  // $PATH, which could be repointed at a malicious `osascript`.
  execFile("/usr/bin/osascript", args, (error) => {
    if (error) console.error("[AppIcon] Finder icon update failed:", error);
  });
}
