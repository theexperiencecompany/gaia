"""Constants for the device bridge — the outbound tunnel from a user's machine.

A paired device (the gaia bridge CLI daemon) holds one outbound WebSocket to
/ws/device and relays MCP JSON-RPC over it. These constants govern pairing,
device connect-token lifetime, and the Redis routing channels that let any worker
reach the pod that owns a device's socket.
"""

from typing import Final, Literal

# The kind of thing a `server_key` resolves to on the device — the daemon's
# ServerConfig.type. The cloud stores it for display/agent context only; it never
# learns the underlying command or URL.
DeviceServerKind = Literal["stdio", "url", "filesystem"]

# --- Device connect token (short-lived JWT the daemon presents on the WS upgrade) ---
# Distinct audience so a device token can never be replayed against the chat-stream
# agent-token path or a WorkOS session — the WS handler checks aud explicitly.
DEVICE_TOKEN_AUDIENCE: Final[str] = "device-bridge"
DEVICE_TOKEN_EXPIRY_MINUTES: Final[int] = 15

# --- Pairing (RFC 8628 device authorization grant) ---
# The device_code is the daemon's secret (never shown); the user_code is the
# short human-typed/clicked code shown in the browser approval page.
DEVICE_CODE_BYTES: Final[int] = 32  # 256-bit opaque device_code
USER_CODE_LENGTH: Final[int] = 8  # e.g. "GAIA-7F3K" without the prefix/dash
# Unambiguous alphabet (no 0/O, 1/I) for a code a human reads off a terminal.
USER_CODE_ALPHABET: Final[str] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_TTL_SECONDS: Final[int] = 15 * 60  # user has 15 min to approve
PAIRING_POLL_INTERVAL_SECONDS: Final[int] = 5  # RFC 8628 poll cadence hint

# Upper bound on ACTIVE devices one user may hold at once — bounds credential
# sprawl and self-pair abuse. Enforced in the shared device-creation path, so
# both browser-approval and desktop self-pair reject creation past it.
MAX_ACTIVE_DEVICES_PER_USER: Final[int] = 20

# --- Device refresh credential (long-lived, rotates on every token exchange) ---
REFRESH_TOKEN_BYTES: Final[int] = 32  # 256-bit opaque refresh token
# Lost-response grace: after rotation, the just-consumed credential can be
# re-exchanged within this window for the SAME replacement (idempotent retry)
# instead of tripping reuse detection. A replay after this window still revokes.
REFRESH_TOKEN_RETRY_GRACE_SECONDS: Final[int] = 60
# Redis key holding a just-issued token so an in-grace retry can be replayed it.
DEVICE_REFRESH_RETRY_PREFIX: Final[str] = "device:refreshretry:"

# --- Redis keys / channels ---
# Pending pairing request, keyed by the opaque device_code.
DEVICE_PAIRING_PREFIX: Final[str] = "device:pairing:"
# Reverse lookup so the browser approval page can resolve a typed user_code.
DEVICE_USER_CODE_PREFIX: Final[str] = "device:usercode:"
# Presence: which pod currently holds the device's socket (heartbeat TTL).
DEVICE_PRESENCE_PREFIX: Final[str] = "device:presence:"
DEVICE_PRESENCE_TTL_SECONDS: Final[int] = 90
# Downstream (any worker -> owning pod -> device socket): one channel per device.
DEVICE_DOWN_CHANNEL_PREFIX: Final[str] = "device:down:"
# Upstream (device socket -> owning pod -> waiting worker): ONE channel per
# consumer pod, not per session — up-frames carry the pod id so the owning pod
# addresses the reply directly; a single shared per-pod listener dispatches by `sid`.
DEVICE_UP_POD_CHANNEL_PREFIX: Final[str] = "device:up:pod:"
# Revocation fan-out: publish a device_id here to force any owning pod to drop it.
# One shared per-pod listener watches this channel (not one per connection).
DEVICE_REVOKE_CHANNEL: Final[str] = "device:revoke"
# Shared per-pod listeners (revoke, up-frames) wait this long before re-subscribing
# after a dropped Redis connection.
DEVICE_LISTENER_RESUBSCRIBE_SECONDS: Final[float] = 5.0

# --- WebSocket liveness ---
# App-level heartbeat: the pod pings; two missed pongs (2x interval) -> drop.
DEVICE_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0
DEVICE_HEARTBEAT_TIMEOUT_SECONDS: Final[float] = 75.0

# --- MCP-over-bridge session ---
# How long a worker waits for the device to open a proxied MCP session before
# giving up (the local server may be slow to spawn / the device offline).
MCP_SESSION_OPEN_TIMEOUT_SECONDS: Final[float] = 30.0

# --- Device server warmup coalescing ---
# Repeat warmups for identical work inside this window collapse instead of racing on status writes.
# A failed warmup suppresses retry for at most this long; the next connect re-drives it.
DEVICE_WARMUP_COALESCE_SECONDS: Final[int] = 60
DEVICE_WARMUP_COALESCE_PREFIX: Final[str] = "device:warmup:"
# How long the online WS handler waits for the down-relay subscription before
# enqueueing warmup anyway. Subscribe is one Redis RTT; the socket must never
# fail if it stalls, but an unsubscribed relay drops the worker's open frame.
DEVICE_RELAY_READY_TIMEOUT_SECONDS: Final[float] = 5.0
# Per JSON-RPC round trip through the tunnel (tool call, list_tools, initialize).
MCP_SESSION_CALL_TIMEOUT_SECONDS: Final[float] = 120.0

# --- exec-over-bridge session (run_on_device) ---
# Hard ceiling before the daemon kills the process. Kept below the 120s
# TOOL_EXECUTION_TIMEOUT_SECONDS (constants/llm.py) so the collector's partial-output result returns first.
DEVICE_EXEC_TIMEOUT_SECONDS: Final[float] = 90.0
# Total captured output (stdout+stderr) per exec before the daemon truncates and
# stops streaming — bounds a runaway command from flooding the tunnel.
DEVICE_EXEC_MAX_OUTPUT_BYTES: Final[int] = 1_000_000

# --- Bridge frame types (WS envelope ``t`` field) ---
# cloud -> device
FRAME_PING: Final[str] = "ping"
FRAME_MCP_OPEN: Final[str] = "mcp.open"
FRAME_MCP_CLOSE: Final[str] = "mcp.close"
FRAME_MCP_MSG: Final[str] = "mcp.msg"
FRAME_REVOKE: Final[str] = "revoke"
FRAME_SERVER_REMOVE: Final[str] = "server.remove"  # drop one server from the daemon's local config
# device -> cloud
FRAME_PONG: Final[str] = "pong"
FRAME_HELLO: Final[str] = "hello"  # daemon announces its exposed servers on connect
FRAME_MCP_OPENED: Final[str] = "mcp.opened"
FRAME_MCP_ERROR: Final[str] = "mcp.error"
# exec-over-bridge (run_on_device): cloud -> device open, device -> cloud stream.
FRAME_EXEC_OPEN: Final[str] = "exec.open"
FRAME_EXEC_STDOUT: Final[str] = "exec.stdout"
FRAME_EXEC_STDERR: Final[str] = "exec.stderr"
FRAME_EXEC_EXIT: Final[str] = "exec.exit"

# --- Chat-driven onboarding copy (surfaced by the add_device tool's card) ---
# Global install commands for the `@heygaia/cli` package. MUST match
# CLI_INSTALL_COMMANDS in libs/shared/ts/src/cli/command-manifest.ts.
CLI_INSTALL_COMMANDS: Final[dict[str, str]] = {
    "npm": "npm install -g @heygaia/cli",
    "pnpm": "pnpm add -g @heygaia/cli",
    "bun": "bun add -g @heygaia/cli",
}
# The commands the user runs after installing.
DEVICE_PAIR_COMMAND: Final[str] = "gaia bridge login"
DEVICE_UP_COMMAND: Final[str] = "gaia bridge up"
# Public setup guide (Mintlify) GAIA links to and can fetch to troubleshoot.
DEVICE_BRIDGE_DOCS_URL: Final[str] = "https://docs.heygaia.io/cli/device-bridge"

# Integration category for device-tunnel MCP servers. They keep managed_by="mcp"
# (they ARE MCP servers, just reached over the tunnel); the transport marker below
# is the real discriminator. Category keeps them out of the public marketplace UI.
DEVICE_CATEGORY: Final[str] = "device"
# Transport marker stored on the integration's mcp_config so _do_connect routes
# through the device bridge instead of an outbound URL.
DEVICE_TRANSPORT: Final[str] = "device"
