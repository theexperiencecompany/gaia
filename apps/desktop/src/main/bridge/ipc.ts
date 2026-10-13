// The renderer-facing half of the device bridge: it registers one ipcMain.handle
// per bridge action, delegating each to the BridgeHost singleton, and pushes
// status changes to the main window so the UI (Phase 3) stays live.
//
// Every invoke resolves to a BridgeInvokeResult envelope rather than rejecting —
// a rejected handle() reaches the renderer as a wrapped stack string, so instead
// we catch and serialize the host's typed errors to { code, message } (R4: only
// status/error data crosses this boundary, never the device refresh token).

import type {
  AddOptions,
  BridgeError,
  BridgeInvokeResult,
  BridgeStatus,
  DeviceServerView,
} from "@gaia/shared/bridge-core";
import { buildConfigFromFlags } from "@gaia/shared/bridge-core";
import { ipcMain } from "electron";
import { IPC } from "../../ipc-channels";
import { getMainWindow } from "../windows/main";
import {
  BridgeNotAuthenticatedError,
  BridgeNotPairedError,
  getBridgeHost,
} from "./host";

/** Map a thrown host error to the renderer contract. The typed pairing errors
 * get machine-readable codes; a server-message error (including the 409
 * device-cap) keeps its human-readable detail under `unknown`. */
function toBridgeError(error: unknown): BridgeError {
  if (error instanceof BridgeNotAuthenticatedError)
    return { code: "not_authenticated", message: error.message };
  if (error instanceof BridgeNotPairedError)
    return { code: "not_paired", message: error.message };
  return {
    code: "unknown",
    message: error instanceof Error ? error.message : String(error),
  };
}

/** Run a host operation and wrap its outcome in the invoke envelope, so the
 * handler never rejects and the renderer always gets a typed result. */
async function run<T>(
  op: () => T | Promise<T>,
): Promise<BridgeInvokeResult<T>> {
  try {
    return { ok: true, value: await op() };
  } catch (error) {
    const bridgeError = toBridgeError(error);
    console.error(
      `[bridge] ipc failure (${bridgeError.code}): ${bridgeError.message}`,
    );
    return { ok: false, error: bridgeError };
  }
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

/** Structural guard for the add-server flags arriving from the renderer. The
 * frame is untrusted over IPC, so validate field *types* here; the required-vs-
 * optional-per-type rules (and slug/tokenize/loopback checks) belong to
 * buildConfigFromFlags, the single source shared with the CLI's `bridge add`. */
function isAddOptions(value: unknown): value is AddOptions {
  if (typeof value !== "object" || value === null) return false;
  const o = value as Record<string, unknown>;
  const optionalString = (key: string): boolean =>
    o[key] === undefined || typeof o[key] === "string";
  const optionalStringArray = (key: string): boolean =>
    o[key] === undefined || isStringArray(o[key]);
  return (
    optionalString("type") &&
    optionalString("name") &&
    optionalString("command") &&
    optionalString("url") &&
    (o["write"] === undefined || typeof o["write"] === "boolean") &&
    optionalStringArray("path") &&
    optionalStringArray("env") &&
    optionalStringArray("header")
  );
}

function bridgePair(): Promise<BridgeInvokeResult<BridgeStatus>> {
  return run(async () => {
    const host = getBridgeHost();
    await host.pair();
    return host.status();
  });
}

function bridgeStatus(): Promise<BridgeInvokeResult<BridgeStatus>> {
  return run(() => getBridgeHost().status());
}

function bridgeStart(): Promise<BridgeInvokeResult<BridgeStatus>> {
  return run(async () => {
    const host = getBridgeHost();
    await host.start();
    return host.status();
  });
}

function bridgeStop(): Promise<BridgeInvokeResult<BridgeStatus>> {
  return run(async () => {
    const host = getBridgeHost();
    await host.stop();
    return host.status();
  });
}

function bridgeListServers(): Promise<BridgeInvokeResult<DeviceServerView[]>> {
  return run(() => getBridgeHost().listServers());
}

function bridgeAddServer(
  opts: unknown,
): Promise<BridgeInvokeResult<DeviceServerView[]>> {
  return run(async () => {
    if (!isAddOptions(opts)) throw new Error("invalid server options");
    const host = getBridgeHost();
    // Returns immediately with the new server as "connecting"; its real state
    // arrives via the servers-changed push once the background connect settles.
    await host.addServer(buildConfigFromFlags(opts));
    return host.listServers();
  });
}

function bridgeRetryServer(
  key: unknown,
): Promise<BridgeInvokeResult<DeviceServerView[]>> {
  return run(async () => {
    if (typeof key !== "string" || key.length === 0)
      throw new Error("invalid server key");
    const host = getBridgeHost();
    await host.retryServer(key);
    return host.listServers();
  });
}

function bridgeRemoveServer(
  key: unknown,
): Promise<BridgeInvokeResult<DeviceServerView[]>> {
  return run(async () => {
    if (typeof key !== "string" || key.length === 0)
      throw new Error("invalid server key");
    const host = getBridgeHost();
    await host.removeServer(key);
    return host.listServers();
  });
}

/** Forward a host status change to the main window's renderer. Guards a
 * destroyed/absent window (status can change before the window exists, or
 * after it closes on quit). */
function pushStatus(status: BridgeStatus): void {
  const win = getMainWindow();
  if (win && !win.isDestroyed()) {
    win.webContents.send(IPC.bridgeStatusChanged, status);
  }
}

/** Forward a server-list change (add/connect/error/remove) to the renderer so
 * the This Mac card reflects each server's live connect state. */
function pushServers(servers: DeviceServerView[]): void {
  const win = getMainWindow();
  if (win && !win.isDestroyed()) {
    win.webContents.send(IPC.bridgeServersChanged, servers);
  }
}

/**
 * Register every bridge IPC handler and the status-change push. Called once
 * from {@link registerIpcHandlers}. Also configures the host's state dir up
 * front (cheap, no shell spawn) so status()/pair() resolve credentials
 * immediately without waiting on the PATH-resolving init() that only the
 * tunnel needs.
 */
export function registerBridgeIpcHandlers(): void {
  getBridgeHost().configureStateDir();

  ipcMain.handle(IPC.bridgePair, () => bridgePair());
  ipcMain.handle(IPC.bridgeStatus, () => bridgeStatus());
  ipcMain.handle(IPC.bridgeStart, () => bridgeStart());
  ipcMain.handle(IPC.bridgeStop, () => bridgeStop());
  ipcMain.handle(IPC.bridgeListServers, () => bridgeListServers());
  ipcMain.handle(IPC.bridgeAddServer, (_event, opts: unknown) =>
    bridgeAddServer(opts),
  );
  ipcMain.handle(IPC.bridgeRemoveServer, (_event, key: unknown) =>
    bridgeRemoveServer(key),
  );
  ipcMain.handle(IPC.bridgeRetryServer, (_event, key: unknown) =>
    bridgeRetryServer(key),
  );

  getBridgeHost().onStatusChange(pushStatus);
  getBridgeHost().onServersChange(pushServers);
}
