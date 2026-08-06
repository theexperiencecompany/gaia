// Bridge frame protocol — must mirror apps/api/app/constants/device_bridge.py.

export const FRAME = {
  // cloud -> device
  PING: "ping",
  MCP_OPEN: "mcp.open",
  MCP_CLOSE: "mcp.close",
  MCP_MSG: "mcp.msg",
  REVOKE: "revoke",
  // device -> cloud
  PONG: "pong",
  HELLO: "hello",
  MCP_OPENED: "mcp.opened",
  MCP_ERROR: "mcp.error",
} as const;

export const DEFAULT_API_URL = "https://api.heygaia.io";

// The built-in filesystem server always uses this stable key.
export const FILESYSTEM_SERVER_KEY = "filesystem";

// Reconnect backoff (ms) with full jitter.
export const RECONNECT_MIN_MS = 500;
export const RECONNECT_MAX_MS = 60_000;
// After a healthy connection drops, spread the *first* reconnect over this window
// instead of RECONNECT_MIN_MS. When a whole pod dies, every daemon it held would
// otherwise re-hit /device/token inside ~500ms; jittering over several seconds
// keeps that burst off the token endpoint and its Postgres pool.
export const RECONNECT_SPREAD_MS = 5_000;

// Cap read_file responses so a huge file can't blow up the tunnel.
export const MAX_READ_BYTES = 1_000_000;
// Images ride the tunnel as base64 MCP image blocks; allow them a larger cap —
// the backend downsizes before anything is inlined into model context.
export const MAX_IMAGE_READ_BYTES = 5_000_000;
