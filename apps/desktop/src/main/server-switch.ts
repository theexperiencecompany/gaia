/**
 * Switch between GAIA Cloud and a self-hosted server. A switch persists the
 * choice and relaunches, so every window, the session-cookie handling and the
 * device bridge start cleanly against the new server.
 *
 * @module server-switch
 */

import {
  DESKTOP_SERVER_FORM_PARAM,
  type DesktopServerConnectResult,
  type DesktopServerFormReason,
} from "@gaia/shared/desktop-tools";
import { app, type BrowserWindow, net } from "electron";
import { normalizeServerAddress, probeSelfHostServer } from "./server-address";
import { updateDesktopSettings } from "./settings";
import { loadBundledRoute } from "./windows/load-url";

function relaunchAfterReply(): void {
  // setImmediate lets the IPC reply reach the renderer before the app quits.
  setImmediate(() => {
    app.relaunch();
    app.quit();
  });
}

/** Validate `address` as a self-hosted GAIA server and relaunch against it. */
export async function connectSelfHostServer(
  address: string,
): Promise<DesktopServerConnectResult> {
  const parsed = normalizeServerAddress(address);
  if (!parsed.ok) return parsed;

  const probed = await probeSelfHostServer(parsed.origin, net.fetch);
  if (!probed.ok) return probed;

  console.log("[Main] Connecting to self-hosted server:", probed.origin);
  updateDesktopSettings({ selfHostOrigin: probed.origin });
  relaunchAfterReply();
  return { ok: true };
}

/** Forget the self-hosted server and relaunch against GAIA Cloud. */
export function switchToGaiaCloud(): void {
  console.log("[Main] Switching to GAIA Cloud");
  updateDesktopSettings({ selfHostOrigin: null });
  relaunchAfterReply();
}

/** Show the bundled server form, which works whether or not a server is reachable. */
export function loadServerForm(
  win: BrowserWindow,
  reason: DesktopServerFormReason,
  serverReady: () => boolean,
): Promise<void> {
  return loadBundledRoute(
    win,
    `/desktop-login?${DESKTOP_SERVER_FORM_PARAM}=${reason}`,
    serverReady,
  );
}
