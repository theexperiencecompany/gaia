// Bridge frame protocol — must mirror apps/api/app/constants/device_bridge.py.

import { sep } from "node:path";

export const FRAME = {
  // cloud -> device
  PING: "ping",
  MCP_OPEN: "mcp.open",
  MCP_CLOSE: "mcp.close",
  MCP_MSG: "mcp.msg",
  REVOKE: "revoke",
  SERVER_REMOVE: "server.remove",
  // device -> cloud
  PONG: "pong",
  HELLO: "hello",
  MCP_OPENED: "mcp.opened",
  MCP_ERROR: "mcp.error",
  // exec-over-bridge (run_on_device): cloud -> device open, device -> cloud stream.
  EXEC_OPEN: "exec.open",
  EXEC_STDOUT: "exec.stdout",
  EXEC_STDERR: "exec.stderr",
  EXEC_EXIT: "exec.exit",
} as const;

export const DEFAULT_API_URL = "https://api.heygaia.io";

// The built-in filesystem server always uses this stable key.
export const FILESYSTEM_SERVER_KEY = "filesystem";

// Sentinel allow-root meaning "the entire filesystem" — the OS root ("/"). A
// filesystem server whose `allow` is [ENTIRE_FS_ROOT] grants every path this
// user can read (and write, if enabled). See isInside() in filesystem-server.ts.
export const ENTIRE_FS_ROOT = sep;

// Reconnect backoff (ms) with full jitter.
export const RECONNECT_MIN_MS = 500;
export const RECONNECT_MAX_MS = 60_000;
// Spreads the *first* reconnect after a drop over this window instead of
// RECONNECT_MIN_MS — avoids every daemon from a dead pod re-hitting
// /device/token within ~500ms and hammering its Postgres pool.
export const RECONNECT_SPREAD_MS = 5_000;

// Cap read_file responses so a huge file can't blow up the tunnel.
export const MAX_READ_BYTES = 1_000_000;
// Images ride the tunnel as base64 MCP image blocks; allow them a larger cap —
// the backend downsizes before anything is inlined into model context.
export const MAX_IMAGE_READ_BYTES = 5_000_000;

// run_on_device: kill a command after this long, and stop streaming once its
// combined stdout+stderr passes the cap (mirrors DEVICE_EXEC_* in device_bridge.py).
export const DEVICE_EXEC_TIMEOUT_MS = 90_000;
export const DEVICE_EXEC_MAX_OUTPUT_BYTES = 1_000_000;
