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
    const scriptPath = process.argv[1];
    if (scriptPath) {
      app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [
        resolve(scriptPath),
      ]);
    }
  } else {
    app.setAsDefaultProtocolClient(PROTOCOL);
  }
}

/**
 * Create a `.desktop` file for Linux dev environments — without it, `xdg-mime`
 * has nothing to associate `x-scheme-handler/gaia` with. Rewritten on every
 * launch so `Exec` stays current after `node_modules` reinstalls. No-ops on
 * non-Linux platforms and packaged builds (installer handles registration).
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

    // Rebuild the MIME cache (what xdg-open reads) — xdg-mime default only writes
    // mimeapps.list. spawnSync uses an explicit args array (no shell) to avoid
    // command injection / PATH-hijacking.
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
