// System-tray control for the device bridge. The tray is the always-on
// surface: it shows whether this Mac is online, lets the user pause/connect the
// tunnel and toggle launch-at-login, opens the main window on demand, and quits
// the app (stopping the tunnel first). It is the only UI in `--hidden` launches.

import { join } from "node:path";
import type { BridgeStatus } from "@gaia/shared/bridge-core";
import {
  app,
  Menu,
  type MenuItemConstructorOptions,
  nativeImage,
  Tray,
} from "electron";
import { getDesktopSettings, updateDesktopSettings } from "../settings";
import { getBridgeHost } from "./host";
import { applyLaunchAtLogin } from "./launch-at-login";

// Held at module scope so the Tray is not garbage-collected (a dropped Tray
// vanishes from the menu bar).
let tray: Tray | null = null;

function trayImage(): Electron.NativeImage {
  const relative = "icons/24x24.png";
  const path = app.isPackaged
    ? join(process.resourcesPath, relative)
    : join(__dirname, "../../resources", relative);
  return nativeImage.createFromPath(path);
}

const DEVICE_LABEL =
  process.platform === "darwin" ? "This Mac" : "This computer";

function statusLabel(status: BridgeStatus): string {
  if (!status.paired) return `${DEVICE_LABEL}: not connected`;
  return status.running ? `${DEVICE_LABEL}: online` : `${DEVICE_LABEL}: paused`;
}

function buildMenu(status: BridgeStatus, onOpen: () => void): Menu {
  const host = getBridgeHost();
  const { launchAtLogin } = getDesktopSettings();

  const toggleItem: MenuItemConstructorOptions = status.running
    ? { label: "Pause", click: () => void host.stop() }
    : {
        label: "Connect",
        enabled: status.paired,
        click: () =>
          void host
            .start()
            .catch((err) => console.error("[Tray] connect failed:", err)),
      };

  return Menu.buildFromTemplate([
    { label: statusLabel(status), enabled: false },
    { type: "separator" },
    toggleItem,
    { type: "separator" },
    { label: "Open GAIA", click: onOpen },
    {
      label: "Launch at login",
      type: "checkbox",
      checked: launchAtLogin,
      click: (item) => {
        updateDesktopSettings({ launchAtLogin: item.checked });
        applyLaunchAtLogin(item.checked);
      },
    },
    { type: "separator" },
    {
      label: "Quit GAIA",
      // Drop the device offline before exiting so the backend sees a clean
      // disconnect rather than a heartbeat timeout.
      click: () => void host.stop().finally(() => app.quit()),
    },
  ]);
}

/**
 * Create the bridge tray and keep its menu/tooltip in sync with the live
 * tunnel status. `onOpen` shows the main window (the tray may be the only
 * surface, e.g. a `--hidden` login launch).
 */
export function createBridgeTray(onOpen: () => void): void {
  if (tray) return;
  const host = getBridgeHost();
  tray = new Tray(trayImage());
  tray.setToolTip("GAIA");

  const render = (status: BridgeStatus): void => {
    if (!tray || tray.isDestroyed()) return;
    tray.setToolTip(`GAIA — ${statusLabel(status)}`);
    tray.setContextMenu(buildMenu(status, onOpen));
  };

  render(host.status());
  host.onStatusChange(render);
}
