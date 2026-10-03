#!/usr/bin/env python3
"""In-sandbox bridge client: stdlib-only frame protocol, allowlist, and exec runner."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import ClassVar

# Frame types mirrored from app/constants/device_bridge.py — do not rename.
FRAME_PING = "ping"
FRAME_MCP_OPEN = "mcp.open"
FRAME_MCP_CLOSE = "mcp.close"
FRAME_MCP_MSG = "mcp.msg"
FRAME_REVOKE = "revoke"
FRAME_SERVER_REMOVE = "server.remove"
FRAME_PONG = "pong"
FRAME_HELLO = "hello"
FRAME_MCP_OPENED = "mcp.opened"
FRAME_MCP_ERROR = "mcp.error"
FRAME_EXEC_OPEN = "exec.open"
FRAME_EXEC_STDOUT = "exec.stdout"
FRAME_EXEC_STDERR = "exec.stderr"
FRAME_EXEC_EXIT = "exec.exit"

# Sandbox JWT audience, mirroring execute_token.py pattern; minted server-side at acquire.
SANDBOX_TOKEN_AUDIENCE = "sandbox-bridge"
SANDBOX_TOKEN_EXPIRY_MINUTES = 15
SANDBOX_WS_PATH = "/ws/sandbox"
# Allowlist GAIA writes per acquire; absent file means the closed default below.
BRIDGE_CONFIG_PATH = "/workspace/.gaia/bridge.json"
DEFAULT_ALLOWED_SERVERS: tuple[str, ...] = ("splitwise",)
# Exec bounds mirrored from DEVICE_EXEC_* in device_bridge.py.
EXEC_TIMEOUT_SECONDS = 90.0
EXEC_MAX_OUTPUT_BYTES = 1_000_000
# Append-only audit trail of server-issued commands, mirroring exec.ts.
EXEC_AUDIT_LOG = "/workspace/.gaia/exec-audit.log"


@dataclass
class Frame:
    """One bridge envelope; `t` names the frame, the rest are per-type fields."""

    t: str
    sid: str | None = None
    server: str | None = None
    servers: list[str] | None = None
    data: str | None = None
    error: str | None = None
    command: str | None = None
    cwd: str | None = None
    code: int | None = None
    key: str | None = None
    pod: str | None = None

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "sid",
        "server",
        "servers",
        "data",
        "error",
        "command",
        "cwd",
        "code",
        "key",
        "pod",
    )

    def encode(self) -> str:
        """Serialize to the wire format, dropping unset fields."""
        payload: dict[str, object] = {"t": self.t}
        for name in self._FIELDS:
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return json.dumps(payload)

    @classmethod
    def decode(cls, raw: str) -> Frame:
        """Parse one wire frame; raises ValueError on malformed input."""
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"not JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("frame must be a JSON object")
        t = obj.get("t")
        if not isinstance(t, str) or not t:
            raise ValueError("frame missing string 't'")
        frame = cls(t=t)
        for name in cls._FIELDS:
            if name in obj:
                setattr(frame, name, obj[name])
        return frame


@dataclass
class BridgeConfig:
    """Allowlist of local MCP server keys this bridge may expose."""

    allowed_servers: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_SERVERS))


def load_bridge_config(path: str | Path = BRIDGE_CONFIG_PATH) -> BridgeConfig:
    """Read the GAIA-written allowlist; a missing file means splitwise-only."""
    p = Path(path)
    if not p.exists():
        return BridgeConfig()
    try:
        obj = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable bridge config at {p}: {e}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("allowed_servers"), list):
        raise ValueError(f'bridge config at {p} must be {{"allowed_servers": [...]}}')
    servers = obj["allowed_servers"]
    if not all(isinstance(s, str) for s in servers):
        raise ValueError(f"bridge config at {p} must list string server keys")
    return BridgeConfig(allowed_servers=list(servers))


def _truncate_outputs(stdout: str, stderr: str, limit: int) -> tuple[str, str, bool]:
    """Cap combined output length, keeping stdout in full before touching stderr."""
    if len(stdout) + len(stderr) <= limit:
        return stdout, stderr, False
    out = stdout[:limit]
    err = stderr[: max(limit - len(out), 0)]
    return out, err, True


@dataclass
class ExecResult:
    """Shaped outcome of one exec.open command."""

    stdout: str
    stderr: str
    code: int
    truncated: bool = False

    def to_frames(self, sid: str, pod: str | None = None) -> list[Frame]:
        """Shape into exec.stdout/stderr/exit frames, echoing the pod."""
        frames: list[Frame] = []
        if self.stdout:
            frames.append(Frame(t=FRAME_EXEC_STDOUT, sid=sid, pod=pod, data=self.stdout))
        if self.stderr:
            frames.append(Frame(t=FRAME_EXEC_STDERR, sid=sid, pod=pod, data=self.stderr))
        frames.append(Frame(t=FRAME_EXEC_EXIT, sid=sid, pod=pod, code=self.code))
        return frames


def _audit_exec(command: str, cwd: str | None) -> None:
    """Append one audit line; a failed write never blocks the command."""
    where = f" (cwd: {cwd})" if cwd else ""
    line = f"{datetime.now(UTC).isoformat()}{where} $ {command}\n"
    with suppress(OSError):
        with open(EXEC_AUDIT_LOG, "a") as f:
            f.write(line)


def _default_cwd() -> str:
    """Sandbox workspace when present, else the user home, mirroring exec.ts."""
    if Path("/workspace").is_dir():
        return "/workspace"
    return str(Path.home())


def run_exec_command(
    command: str,
    cwd: str | None = None,
    timeout: float = EXEC_TIMEOUT_SECONDS,
) -> ExecResult:
    """Run one shell command; the trust boundary is the sandbox JWT, not the text."""
    _audit_exec(command, cwd)
    try:
        proc = subprocess.run(  # noqa: S602 - server-issued shell command, cf. exec.ts
            command,
            shell=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd or _default_cwd(),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        out, err, _ = _truncate_outputs(e.stdout or "", e.stderr or "", EXEC_MAX_OUTPUT_BYTES)
        note = f"\n[sandbox bridge] killed — exceeded {timeout:g}s timeout\n"
        out, err, _ = _truncate_outputs(out, err + note, EXEC_MAX_OUTPUT_BYTES)
        return ExecResult(stdout=out, stderr=err, code=-1, truncated=True)
    except OSError as e:
        return ExecResult(
            stdout="", stderr=f"[sandbox bridge] could not start command: {e}\n", code=127
        )
    stdout, stderr, truncated = _truncate_outputs(proc.stdout, proc.stderr, EXEC_MAX_OUTPUT_BYTES)
    return ExecResult(stdout=stdout, stderr=stderr, code=proc.returncode, truncated=truncated)


ExecRunner = Callable[[str, str | None], ExecResult]


class Bridge:
    """Transport-free dispatch core; the socket layer feeds handle_raw and sends replies."""

    def __init__(self, config: BridgeConfig, exec_runner: ExecRunner | None = None) -> None:
        self._config = config
        self._sessions: set[str] = set()
        self._exec_runner = exec_runner if exec_runner is not None else run_exec_command
        self.stopped = False

    def hello_frame(self) -> Frame:
        """Announce the allowlisted servers, mirroring tunnel.ts connect hello."""
        return Frame(t=FRAME_HELLO, servers=list(self._config.allowed_servers))

    def handle_raw(self, raw: str) -> list[Frame]:
        """Parse and dispatch one wire line; malformed or unknown input yields nothing."""
        try:
            frame = Frame.decode(raw)
        except ValueError:
            return []
        return self.handle_frame(frame)

    def handle_frame(self, frame: Frame) -> list[Frame]:
        """Dispatch one frame, mirroring tunnel.ts onFrame semantics."""
        if frame.t == FRAME_PING:
            return [Frame(t=FRAME_PONG)]
        if frame.t == FRAME_MCP_OPEN:
            return self._open_session(frame)
        if frame.t == FRAME_MCP_MSG:
            return self._forward_to_server(frame)
        if frame.t == FRAME_MCP_CLOSE:
            if frame.sid is not None:
                self._sessions.discard(frame.sid)
            return []
        if frame.t == FRAME_EXEC_OPEN:
            return self._run_exec(frame)
        if frame.t == FRAME_REVOKE:
            self.stopped = True
            return []
        if frame.t == FRAME_SERVER_REMOVE:
            if frame.key is not None:
                self._drop_server(frame.key)
            return []
        return []

    def _open_session(self, frame: Frame) -> list[Frame]:
        """Admit sid when the server is allowlisted, else reply mcp.error."""
        if not frame.sid or not frame.server:
            return []
        if frame.server not in self._config.allowed_servers:
            return [
                Frame(
                    t=FRAME_MCP_ERROR,
                    sid=frame.sid,
                    pod=frame.pod,
                    error=f"Unknown server '{frame.server}'",
                )
            ]
        self._sessions.add(frame.sid)
        return [Frame(t=FRAME_MCP_OPENED, sid=frame.sid, pod=frame.pod)]

    def _forward_to_server(self, frame: Frame) -> list[Frame]:
        """Gate downstream JSON-RPC on an open session; relay to the stdio child lands later."""
        if not frame.sid or frame.data is None:
            return []
        if frame.sid not in self._sessions:
            return [
                Frame(
                    t=FRAME_MCP_ERROR,
                    sid=frame.sid,
                    pod=frame.pod,
                    error=f"Unknown session '{frame.sid}'",
                )
            ]
        return []

    def _run_exec(self, frame: Frame) -> list[Frame]:
        """Run the shell command and shape stdout/stderr/exit frames."""
        if not frame.sid or not frame.command:
            return []
        return self._exec_runner(frame.command, frame.cwd).to_frames(frame.sid, frame.pod)

    def _drop_server(self, key: str) -> None:
        """Forget a server deleted in GAIA so hello stops advertising it."""
        if key in self._config.allowed_servers:
            self._config.allowed_servers.remove(key)


def sandbox_ws_url(host: str) -> str:
    """Map an http(s) API host to its sandbox socket URL, mirroring tunnel.ts."""
    if host.startswith("http://"):
        base = "ws://" + host[len("http://") :]
    elif host.startswith("https://"):
        base = "wss://" + host[len("https://") :]
    else:
        base = "wss://" + host
    return base.rstrip("/") + SANDBOX_WS_PATH


def build_auth_header(token: str) -> dict[str, str]:
    """Authorization header the dialer presents the sandbox JWT in."""
    return {"Authorization": f"Bearer {token}"}


def run_stdio(config_path: str | Path = BRIDGE_CONFIG_PATH) -> int:
    """Serve newline-delimited frames on stdio until EOF or revoke."""
    bridge = Bridge(load_bridge_config(config_path))
    print(bridge.hello_frame().encode(), flush=True)
    for line in sys.stdin:
        if bridge.stopped:
            break
        for reply in bridge.handle_raw(line):
            print(reply.encode(), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: stdio frame loop over the GAIA-written allowlist."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=BRIDGE_CONFIG_PATH)
    args = parser.parse_args(argv)
    return run_stdio(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
