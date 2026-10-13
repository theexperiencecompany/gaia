// Renderer-facing bridge contract: the shapes that cross the desktop IPC /
// preload boundary between the Electron main process (BridgeHost) and the web
// renderer. Kept as pure types (no node imports) so the web app can import them
// without pulling the node-only bridge-core runtime.
//
// The device refresh token NEVER appears here (R4): status is a two-boolean
// snapshot and errors are a { code, message } pair, so no credential can leak to
// the renderer through the IPC surface.

/** Snapshot for the renderer/tray: whether this device is paired (has stored
 * credentials) and whether its tunnel is currently held open. `deviceId` is the
 * paired device's id (null when unpaired) so the renderer can tell which row in
 * the devices list is "this Mac" and not show it twice; the refresh token is
 * never included. */
export interface BridgeStatus {
  paired: boolean;
  running: boolean;
  deviceId: string | null;
}

/** Transient connect state of a device MCP server, tracked by the host so the
 * card can show progress: a freshly added server is `connecting` (its
 * test+register runs in the background) until it settles to `connected` or
 * `error`. Servers loaded from config at startup are reported `connected`. */
export type DeviceServerState = "connecting" | "connected" | "error";

/** One MCP server on this device for the This Mac card: the config fields the
 * UI shows plus its live connect state (and error message when it failed). */
export interface DeviceServerView {
  key: string;
  name: string;
  type: "stdio" | "url" | "filesystem";
  state: DeviceServerState;
  error?: string;
}

/** Machine-readable outcome for a failed bridge invoke. `not_authenticated` and
 * `not_paired` map to the host's typed errors; everything else (including the
 * server's 409 device-cap message) is `unknown`, with the human-readable detail
 * carried in {@link BridgeError.message}. */
export type BridgeErrorCode = "not_authenticated" | "not_paired" | "unknown";

export interface BridgeError {
  code: BridgeErrorCode;
  message: string;
}

/** Every bridge invoke resolves to this envelope rather than rejecting, so the
 * renderer inspects a typed { code, message } instead of a wrapped stack trace. */
export type BridgeInvokeResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: BridgeError };
