/**
 * Protocol Registration Module
 *
 * Registers the `gaia://` custom protocol so the OS can route
 * deep-link URLs (e.g. OAuth callbacks) back to the desktop app.
 *
 * Platform behaviour:
 * - **macOS** — `setAsDefaultProtocolClient` works in dev; production
 *   relies on `CFBundleURLTypes` in the app bundle.
 * - **Windows** — `setAsDefaultProtocolClient` writes to the registry;
 *   the NSIS installer also registers the protocol.
 * - **Linux** — Requires a `.desktop` file with a `MimeType` entry.
 *   Production deb/rpm packages register via electron-builder's
 *   `mimeTypes` config. In dev (and AppImage) we create a temporary
 *   `.desktop` file in `~/.local/share/applications/`.
 *
 * All registration calls must run **before** `app.ready`.
 *
 * @module protocol
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { app } from "electron";

/** The custom URL scheme used for deep linking. */
const PROTOCOL = "gaia";

/**
 * Register the app as the default handler for `gaia://` URLs.
 *
 * In development (when launched via `electron .`) the current
 * script path is passed so Electron can re-launch correctly.
 */
export function registerProtocol(): void {
  if (process.defaultApp) {
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [
        resolve(process.argv[1]),
      ]);
    }
  } else {
    app.setAsDefaultProtocolClient(PROTOCOL);
  }
}

/**
 * Create a `.desktop` file for Linux development environments.
 *
 * Without this file `xdg-mime` has nothing to associate the
 * `x-scheme-handler/gaia` MIME type with, so `setAsDefaultProtocolClient`
 * alone is not enough.  The file is rewritten on every launch so the
 * `Exec` path stays current after `node_modules` reinstalls.
 *
 * No-ops on non-Linux platforms and in packaged (production) builds
 * where the installer handles registration.
 */
export function registerLinuxDevProtocol(): void {
  if (process.platform !== "linux" || app.isPackaged) return;

  try {
    const appsDir = join(homedir(), ".local", "share", "applications");
    const desktopFile = join(appsDir, "gaia-dev.desktop");
    const scriptPath = resolve(process.argv[1] || "");

    const content = [
      "[Desktop Entry]",
      "Name=GAIA (Dev)",
      "Type=Application",
      // %u passes the full URI (gaia://...) as the first argument
      // Paths are quoted to handle spaces and special characters
      `Exec="${process.execPath}" "${scriptPath}" %u`,
      "Terminal=false",
      "MimeType=x-scheme-handler/gaia;",
      "NoDisplay=true",
      "StartupNotify=false",
    ].join("\n");

    if (!existsSync(appsDir)) {
      mkdirSync(appsDir, { recursive: true });
    }

    writeFileSync(desktopFile, content);

    // Rebuild the MIME cache — this is what xdg-open actually reads.
    // xdg-mime default only writes to mimeapps.list; without rebuilding
    // mimeinfo.cache the system falls back to the app store.
    // Use spawnSync with an explicit args array (no shell) to avoid
    // command injection and PATH-hijacking risks.
    spawnSync("update-desktop-database", [appsDir], { shell: false });

    // Also write the mimeapps.list entry explicitly so it takes precedence
    // over any distro-level handlers.
    spawnSync(
      "xdg-mime",
      ["default", "gaia-dev.desktop", "x-scheme-handler/gaia"],
      { shell: false },
    );

    console.log(
      "[Main] gaia:// protocol registered. Exec:",
      `"${process.execPath}" "${scriptPath}" %u`,
    );
  } catch (err) {
    console.error("[Main] Failed to register gaia:// protocol on Linux:", err);
  }
}
