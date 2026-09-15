"""True black-box E2E tests for the device bridge — driven only through the real
wire protocol, exactly as a real user/device would:

  * the ``gaia bridge`` daemon runs as a real Node subprocess (via ``tsx``, no
    build step) and does its own real pairing/token/WebSocket work — nothing
    about the daemon is mocked or called into directly from Python;
  * the "signed-in user" side (approve, list, test-connection, revoke) is
    driven by real HTTP calls against a real, live GAIA API instance (see
    ``live_api_server`` in conftest.py) — no internal service-function calls;
  * the local MCP server the daemon exposes is the real, official
    ``@modelcontextprotocol/server-everything`` reference server, spawned by
    the daemon over real stdio — not the built-in ``filesystem`` special case.

Direct Redis access is used in exactly two places, both called out inline,
for states a real client genuinely cannot produce without waiting out a real
TTL: a 15-minute pairing-code expiry and a 60-second refresh-token retry
grace window. Every assertion in those tests is still made through the real
API response, never by reading the seeded state back out of Redis.

Contrast with test_device_bridge_real.py, which calls internal Python
functions (mark_online, register_up_session, etc.) directly against real
Redis to regression-test specific plumbing bugs (presence CAS, dispatch
isolation) — a different, still-valuable tier that this file does not
replace.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import contextlib
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import httpx
import pytest

from app.workers.tasks.device_tasks import warm_device_servers
from tests.helpers import pick_free_port

pytestmark = [pytest.mark.service, pytest.mark.slow]

# Anchor by walking up to the repo root that owns the CLI package (which ships
# `gaia bridge`), rather than by depth from this test file — the file may move
# within the tests tree.
CLI_DIR = next(
    parent / "packages" / "cli"
    for parent in Path(__file__).resolve().parents
    if (parent / "packages" / "cli").is_dir()
)
# tsx's bin location depends on pnpm's node-linker. The repo now runs the
# default isolated linker everywhere (no .npmrc), which puts tsx in the CLI
# package's own node_modules/.bin; the repo-root fallback keeps this working on
# a hoisted install (an older checkout, or a consumer that sets node-linker).
_CLI_TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
_ROOT_TSX = CLI_DIR.parent.parent / "node_modules" / ".bin" / "tsx"
TSX_BIN = _CLI_TSX if _CLI_TSX.exists() else _ROOT_TSX
EVERYTHING_PACKAGE = "@modelcontextprotocol/server-everything"
# Pinned: an unpinned spec makes npx re-resolve `latest` against
# registry.npmjs.org on every run even when the package is already in its
# cache — 15-19s on the CI box's residential uplink under load. To bump, run
# `npx -y @modelcontextprotocol/server-everything@<new> stdio </dev/null` once
# and set the new version here. Keep it to a version the self-hosted runner's
# npm mirror already has: a brand-new version it has never fetched resolves to
# ETARGET on the box even while it exists on public npm (2026.8.31 did this).
EVERYTHING_VERSION = "2026.8.18"


@cache
def _npm_cache_dir() -> str:
    """Where ``everything_server_cached`` installs the server and finds it again.

    npm derives both its content cache and the ``_npx`` package directory from
    ``HOME``, so leaving it implicit means the install and the lookup can land
    in different places depending on whose ``HOME`` is set. Naming one real
    directory pins both ends of the fixture to the same install.
    """
    resolved = subprocess.run(
        ["npm", "config", "get", "cache"],
        capture_output=True,
        text=True,
        timeout=60.0,
        check=True,
    ).stdout.strip()
    assert resolved and resolved != "undefined", f"could not resolve npm cache dir: {resolved!r}"
    return resolved


USER_CODE_RE = re.compile(r"enter this code:\s*([A-Z0-9-]+)")

# How long the daemon gets to print its pairing code, measured rather than guessed.
# `runLogin` prints NOTHING until `startPairing` returns, so this window covers
# node boot + tsx transpiling src/index.ts's whole import graph (it statically
# imports every command — ink, react, simple-git, execa, the MCP SDK — before
# commander even parses argv) + one HTTP round trip. Measured cost of that whole
# prefix: 0.76s on a dev laptop, ~1s on the runner's i7-10700K, and the complete
# golden path (pair, tunnel up, real MCP round trip, revoke) runs in 5.0s when the
# runner is idle (run 33302182969, bridge alone on the box).
#
# The old 10s was inside the noise, not outside it. The self-hosted box schedules
# up to seven jobs across 8 physical cores at once — unit-a/unit-b/integration
# claim 16 xdist workers between them, plus test-typescript, build and
# docker-image — and this slice is budgeted no share at all. Under that load the
# same fixture's setup goes 4.1s -> 9.5s (run 33301137881) and the daemon's spawn
# is hit harder still: the test failed ~50% of the time with an EMPTY transcript.
# This is the contended ceiling, not the expected cost; a genuinely dead child now
# fails in under a second via the liveness check in wait_for_user_code, so the
# only thing a large ceiling buys is not flaking on a busy machine.
USER_CODE_TIMEOUT_SECONDS = 60.0


def everything_server(entry: Path) -> dict:
    """The third-party stdio MCP server config the daemon is told to expose.

    ``entry`` is the server's own entry script, resolved out of the npx cache by
    ``everything_server_cached``, and it is spawned with ``node`` directly
    rather than through ``npx``. This is inside the timed /api/v1/mcp/test
    request, and ``npx`` is not free there: it is a whole extra Node process
    that re-resolves the package before exec'ing the real one. Measured on the
    CI box, the gap between the tunnel opening the session and the server
    printing its banner was 5.3s idle and 9.4-15.2s under load — enough to put
    a 28s round trip inside a 35s client budget. Resolving once in a fixture
    and exec'ing the script leaves only the server's own Node startup in the
    request. It is still the real, official reference server over real stdio.
    """
    return {
        "type": "stdio",
        "key": "everything",
        "name": "Everything Test Server",
        "command": "node",
        "args": [str(entry), "stdio"],
        "env": {},
    }


class BridgeDaemon:
    """Drives the real ``gaia bridge`` CLI as a subprocess, isolated to a
    scratch ``HOME`` so it can never touch a developer's real pairing.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self.login_process: asyncio.subprocess.Process | None = None
        self.up_process: asyncio.subprocess.Process | None = None
        # The detached `up --serve` tunnel daemon that `gaia bridge up` spawns.
        # It is NOT a child of this process (up double-forks and exits), so it is
        # tracked by the pid it writes to <HOME>/.gaia/bridge/daemon.pid and
        # reaped by pid, not by awaiting a Process handle.
        self.daemon_pid: int | None = None
        self.login_output: list[str] = []
        self.up_output: list[str] = []
        # One merged, timestamped view of daemon stdout/stderr plus the test's
        # own phase marks. Without it a timeout tells you only that 35s passed,
        # not which of pair/exchange/connect/open/list spent them.
        self.transcript: list[str] = []
        self._t0 = time.monotonic()
        self._tasks: list[asyncio.Task] = []

    async def _spawn(self, *args: str) -> asyncio.subprocess.Process:
        env = {**os.environ, "HOME": str(self.home)}
        self._log(f"spawn: {TSX_BIN} src/index.ts bridge {' '.join(args)}")
        return await asyncio.create_subprocess_exec(
            str(TSX_BIN),
            "src/index.ts",
            "bridge",
            *args,
            cwd=str(CLI_DIR),
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def _log(self, text: str) -> None:
        """Append one timestamped line to the transcript printed at teardown."""
        self.transcript.append(f"[+{time.monotonic() - self._t0:7.3f}s] {text.rstrip()}")

    def _pump(self, stream: asyncio.StreamReader, sink: list[str], label: str) -> None:
        async def _run() -> None:
            while True:
                line = await stream.readline()
                if not line:
                    return
                decoded = line.decode(errors="replace")
                sink.append(decoded)
                # Timestamps are the whole point: a daemon that is *slow* and a
                # daemon that is *stuck* produce the same untimed text.
                self._log(f"{label} | {decoded}")

        self._tasks.append(asyncio.create_task(_run()))

    def mark(self, phase: str) -> None:
        """Record a wall-clock phase boundary on the same timeline as daemon output."""
        self._log(f"PHASE {phase}")

    def dump(self) -> str:
        return "\n".join(self.transcript)

    async def start_login(self, api_url: str, name: str) -> None:
        self.login_process = await self._spawn("login", "--api", api_url, "--name", name)
        self._pump(self.login_process.stdout, self.login_output, "login/out")
        self._pump(self.login_process.stderr, self.login_output, "login/err")

    async def _drain(self, timeout: float = 2.0) -> None:
        """Let the output pumps reach EOF so a dead child's last words — the
        stack trace saying *why* it died — make it into the message we raise."""
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=timeout)

    async def wait_for_user_code(self, timeout: float = USER_CODE_TIMEOUT_SECONDS) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            match = USER_CODE_RE.search("".join(self.login_output))
            if match:
                return match.group(1)
            assert self.login_process is not None
            # Liveness guard: without it a child that crashed and one that is
            # merely slow both report the collected output only after the full
            # timeout, which is how a CI failure with an empty transcript stayed
            # ambiguous for two days.
            returncode = self.login_process.returncode
            if returncode is not None:
                await self._drain()
                raise AssertionError(
                    f"`gaia bridge login` exited with exit code {returncode} before "
                    f"printing a user_code; output: {''.join(self.login_output)!r}"
                )
            if loop.time() >= deadline:
                raise AssertionError(
                    f"user_code never appeared in `gaia bridge login` output within "
                    f"{timeout:.0f}s — the child is still running (pid "
                    f"{self.login_process.pid}), so this is starvation or a hung "
                    f"request, not a crash. Output so far: "
                    f"{''.join(self.login_output)!r}"
                )
            await asyncio.sleep(0.1)

    async def wait_login_complete(self, timeout: float = 20.0) -> None:
        assert self.login_process is not None
        await asyncio.wait_for(self.login_process.wait(), timeout=timeout)
        output = "".join(self.login_output)
        assert self.login_process.returncode == 0, f"`gaia bridge login` failed: {output}"
        assert "Paired as" in output, output

    def write_config(self, servers: Iterable[dict]) -> None:
        config_dir = self.home / ".gaia" / "bridge"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(json.dumps({"servers": list(servers)}))

    def _daemon_dir(self) -> Path:
        return self.home / ".gaia" / "bridge"

    def _read_daemon_pid(self) -> int | None:
        pidfile = self._daemon_dir() / "daemon.pid"
        if not pidfile.exists():
            return None
        text = pidfile.read_text().strip()
        return int(text) if text else None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)  # signal 0 probes liveness without killing
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not ours — still alive
        return True

    def daemon_log(self) -> str:
        """The detached tunnel daemon's own log. `gaia bridge up` runs the tunnel
        in a background `--serve` child whose stdout/stderr are redirected here,
        so the daemon's `connected — exposing` / `revoked` lines land in this file
        rather than in the parent `up` process's (already-exited) stdout."""
        log_file = self._daemon_dir() / "daemon.log"
        return log_file.read_text(errors="replace") if log_file.exists() else ""

    async def start_up(self, timeout: float = 30.0) -> None:
        """Run `gaia bridge up`: it registers the configured servers, spawns the
        detached tunnel daemon, prints the background notice, and EXITS 0. The
        tunnel itself now runs in the background — the parent exiting is success,
        not failure. Captures the daemon's pid so teardown can reap it."""
        self.up_process = await self._spawn("up")
        self._pump(self.up_process.stdout, self.up_output, "up/out")
        self._pump(self.up_process.stderr, self.up_output, "up/err")
        await asyncio.wait_for(self.up_process.wait(), timeout=timeout)
        await self._drain()
        output = "".join(self.up_output)
        assert self.up_process.returncode == 0, f"`gaia bridge up` failed: {output}"
        assert "started in the background" in output, output
        self.daemon_pid = self._read_daemon_pid()
        assert self.daemon_pid is not None, f"`gaia bridge up` wrote no daemon pid: {output}"

    async def run_bridge_command(self, *args: str, timeout: float = 30.0) -> str:
        """Run a one-shot `gaia bridge <args>` (e.g. `rm <key>`), wait for it to
        exit, and return its combined output. Asserts a clean exit."""
        proc = await self._spawn(*args)
        out: list[str] = []
        self._pump(proc.stdout, out, f"{args[0]}/out")
        self._pump(proc.stderr, out, f"{args[0]}/err")
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        await self._drain()
        output = "".join(out)
        assert proc.returncode == 0, f"`gaia bridge {' '.join(args)}` failed: {output}"
        return output

    def read_config_keys(self) -> set[str]:
        """The server keys the daemon currently has in its local config.json."""
        config_file = self._daemon_dir() / "config.json"
        if not config_file.exists():
            return set()
        servers = json.loads(config_file.read_text()).get("servers", [])
        return {s["key"] for s in servers}

    async def wait_daemon_exits(self, timeout: float = 10.0) -> None:
        """After a revoke, the real background daemon must drop the tunnel and
        exit on its own — proof revocation propagates over the wire, not just as
        a Postgres flag. The daemon is detached, so wait on its pid, not a handle."""
        assert self.daemon_pid is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._pid_alive(self.daemon_pid):
            if loop.time() >= deadline:
                raise AssertionError(
                    f"background tunnel daemon (pid {self.daemon_pid}) did not exit "
                    f"within {timeout:.0f}s of revoke; daemon.log:\n{self.daemon_log()}"
                )
            await asyncio.sleep(0.1)

    async def stop_all(self) -> None:
        # Reap the detached background tunnel daemon FIRST. `gaia bridge up`
        # spawns it detached and exits, so it is nobody's child — without this,
        # a `--serve` node process leaks between tests (a prior run did exactly
        # that). Read the pidfile fresh: a successful revoke leaves the pid dead
        # but the pidfile present (only `gaia bridge down` unlinks it), and the
        # other lifecycle tests never bring a tunnel up, so there is no pidfile.
        pid = self._read_daemon_pid()
        if pid is not None and self._pid_alive(pid):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5.0
            while True:
                if not self._pid_alive(pid):
                    break
                if time.monotonic() >= deadline:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)  # last resort if SIGTERM was ignored
                    break
                await asyncio.sleep(0.1)
        for process in (self.login_process, self.up_process):
            if process is not None and process.returncode is None:
                process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


def _cached_everything_entry(cache_dir: str) -> Path | None:
    """The pinned server's entry script if npx has already installed it, else None."""
    for package in sorted(Path(cache_dir).glob(f"_npx/*/node_modules/{EVERYTHING_PACKAGE}")):
        manifest = json.loads((package / "package.json").read_text())
        if manifest["version"] != EVERYTHING_VERSION:
            continue
        # `bin` is either a string or a {name: path} map; this package ships one bin.
        bin_field = manifest["bin"]
        relative = bin_field if isinstance(bin_field, str) else next(iter(bin_field.values()))
        entry = package / relative
        if entry.is_file():
            return entry
    return None


@pytest.fixture(scope="session")
def everything_server_cached() -> Path:
    """Fetch the third-party MCP server once, before any test, and resolve it.

    The fetch has to happen somewhere, and here is the only place where it is
    not being timed. Feeding the real spawn a closed stdin is what makes this a
    fetch rather than an approximation of one: the server sees EOF on its stdio
    transport and exits 0 on its own, so the package is installed by exactly the
    command a user would run. What the tests then spawn is the entry script this
    resolves out of that install — see ``everything_server``.

    A warm cache (the persistent home runner, a developer laptop) skips the npx
    step entirely: the pinned version is already on disk, and npx would only
    spend the time re-resolving the spec against the registry.
    """
    cache_dir = _npm_cache_dir()
    entry = _cached_everything_entry(cache_dir)
    if entry is None:
        # Generous: this is setup, and on a cold runner it is a real npm download.
        warm = subprocess.run(
            [
                "npx",
                "-y",
                "--prefer-offline",
                f"{EVERYTHING_PACKAGE}@{EVERYTHING_VERSION}",
                "stdio",
            ],
            stdin=subprocess.DEVNULL,
            env={**os.environ, "npm_config_cache": cache_dir},
            capture_output=True,
            text=True,
            timeout=180.0,
            check=False,
        )
        assert warm.returncode == 0, (
            f"could not install {EVERYTHING_PACKAGE}@{EVERYTHING_VERSION} "
            f"(rc={warm.returncode}): {warm.stderr}"
        )
        entry = _cached_everything_entry(cache_dir)
    assert entry is not None, (
        f"{EVERYTHING_PACKAGE}@{EVERYTHING_VERSION} not found under {cache_dir}/_npx "
        "after a successful fetch"
    )
    return entry


@pytest.fixture(scope="session")
def warm_cli() -> None:
    """Run the real CLI once, before any test's readiness clock starts.

    Two jobs, both learned from a CI failure whose only symptom was an empty
    transcript. It pays node's boot plus tsx's transpile of src/index.ts's whole
    import graph (every command is a static import — ink, react, simple-git,
    execa, the MCP SDK — so `bridge login` loads all of it before printing
    anything) outside the window the tests measure. And it turns an unrunnable
    CLI — tsx missing, a node_modules symlink dangling after a pnpm store move,
    a node/ABI mismatch — into a named failure here rather than a silent
    "user_code never appeared" inside a test that looks like a timing flake.

    Same trick, for the same reason, as everything_server_cached above.
    """
    probe = subprocess.run(
        [str(TSX_BIN), "src/index.ts", "--version"],
        cwd=str(CLI_DIR),
        capture_output=True,
        text=True,
        timeout=180.0,
        check=False,
    )
    assert probe.returncode == 0, (
        f"the `gaia` CLI is not runnable via {TSX_BIN} (rc={probe.returncode}); "
        f"every bridge test below would fail as a bare timeout. stderr: {probe.stderr}"
    )


def _client(base_url: str, user_id: str | None = None) -> httpx.AsyncClient:
    headers = {"x-test-user-id": user_id} if user_id else {}
    # Sized from the measured cost of the slowest call these clients make — the
    # /api/v1/mcp/test round trip: open the tunnel session (the daemon spawns the
    # local MCP server), then initialize + list_tools over Redis pub/sub. 35s is
    # headroom for a loaded runner, not a budget for process startup: keep the
    # spawn a direct `node` exec of a pre-resolved script (see
    # everything_server) rather than raising this.
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=35.0)


OWNER_USER_ID = "device-e2e-owner"


async def wait_device_online(
    client: httpx.AsyncClient, device_id: str, *, timeout: float = 30.0
) -> None:
    """Poll the real /device/list until the cloud reports the device online.

    Presence flips on when the daemon's tunnel WebSocket connects and sends its
    HELLO, so this is the backend-visible proof the backgrounded daemon came up —
    the exact signal Settings > Devices shows a user. It replaces scanning the
    old foreground `up` process's stdout for "connected — exposing" (which now
    goes to the detached daemon.log, never the parent's stdout)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        listing = await client.get("/api/v1/device/list")
        assert listing.status_code == 200, listing.text
        device = next((d for d in listing.json()["devices"] if d["id"] == device_id), None)
        if device is not None and device["online"] is True:
            return
        if loop.time() >= deadline:
            raise AssertionError(
                f"device {device_id} never came online within {timeout:.0f}s; "
                f"last listing: {listing.json()!r}"
            )
        await asyncio.sleep(0.25)


class TestFullDeviceLifecycle:
    async def _warm_and_assert_tools_indexed(self, owner, device_id, daemon) -> None:
        """Warm-connect is what registration enqueues to make the server's tools
        discoverable without anyone hitting /mcp/test. No ARQ worker runs in this
        harness, so the task is invoked inline — this still exercises the real
        tunnel connect + Chroma index + DB record, just not the queue hop itself."""
        summary = await warm_device_servers({}, device_id)
        assert summary == "warmed=1 failed=0", summary
        warmed = (await owner.get("/api/v1/device/list")).json()["devices"][0]["servers"][0]
        assert warmed["tools_synced_at"] is not None
        assert warmed["status"] == "connected"
        assert warmed["kind"] == "stdio"
        daemon.mark("warm-connect indexed tools (tools_synced_at set)")

    async def test_pair_up_real_mcp_round_trip_then_revoke(
        self,
        tmp_path,
        live_api_server,
        clean_bridge_tables,
        everything_server_cached,
        warm_cli,
        make_pro_subscription,
    ):
        """The golden path, end to end, with no shortcuts anywhere in the chain."""
        # The device tunnel is paid-only and checks the subscription at connect
        # (device_ws.py), so the owner needs a real active subscription before
        # the daemon dials — otherwise the handshake is refused with a 403 and
        # the whole lifecycle never starts. A free user's rejection is covered
        # by tests/unit/api/test_device_ws_paid_only_gate.py.
        await make_pro_subscription(OWNER_USER_ID)
        daemon = BridgeDaemon(tmp_path / "home")
        owner = _client(live_api_server.url, OWNER_USER_ID)
        try:
            # 1. Real `gaia bridge login` subprocess starts RFC 8628 pairing.
            await daemon.start_login(live_api_server.url, "e2e-test-machine")
            user_code = await daemon.wait_for_user_code()
            daemon.mark("user_code shown")

            # 2. The "signed-in user" approves — a real HTTP call, exactly what
            #    the Settings > Devices approve page sends.
            approve = await owner.post("/api/v1/device/pair/approve", json={"user_code": user_code})
            assert approve.status_code == 200, approve.text
            device_id = approve.json()["device_id"]
            daemon.mark("pairing approved")

            # 3. The daemon's poll loop picks up the approval and finishes on
            #    its own — nothing pushed to it directly.
            await daemon.wait_login_complete()
            daemon.mark("login complete (credential issued)")

            # 4. Configure a real third-party stdio MCP server (the general
            #    `gaia bridge add` path, not the built-in `filesystem` case)
            #    and bring the tunnel up for real.
            daemon.write_config([everything_server(everything_server_cached)])
            # `up` registers servers, spawns the detached tunnel daemon, and
            # exits 0 — the parent exiting is success, not failure.
            await daemon.start_up()
            daemon.mark(f"up exited 0; tunnel daemon detached (pid {daemon.daemon_pid})")
            # The daemon connects in the background; wait for the backend to see
            # it online (presence set on the tunnel's WS connect).
            await wait_device_online(owner, device_id)
            daemon.mark("device online (tunnel connected in the background)")
            # Regression guard: tunnel.ts's connectOnce() once resolved its
            # connection promise on the socket's `open` event instead of
            # `close`, so run() immediately looped and opened a new socket on
            # every tick — a real reconnect storm a live daemon process (and
            # only a live daemon process) can actually surface. The daemon's
            # tunnel logs now land in daemon.log, not the parent's stdout.
            await asyncio.sleep(0.5)
            daemon_log = daemon.daemon_log()
            assert "reconnecting in" not in daemon_log, daemon_log
            assert "connected — exposing" in daemon_log, daemon_log

            # 5. The user's browser lists devices — real HTTP, real Postgres read.
            listing = await owner.get("/api/v1/device/list")
            assert listing.status_code == 200
            devices = listing.json()["devices"]
            assert len(devices) == 1
            assert devices[0]["id"] == device_id
            assert devices[0]["online"] is True
            assert len(devices[0]["servers"]) == 1
            server = devices[0]["servers"][0]
            assert server["server_key"] == "everything"
            daemon.mark("device listed online")
            assert server["tools_synced_at"] is None, "not warmed yet"

            # 5b. Warm-connect makes the server's tools discoverable (see helper).
            await self._warm_and_assert_tools_indexed(owner, device_id, daemon)

            # 6. Trigger a real MCP round trip through the whole tunnel — the
            #    same endpoint Settings uses to test/retry a connection. No
            #    LLM call, no internal Python call into DeviceConnector.
            probe = await owner.post(f"/api/v1/mcp/test/{server['integration_id']}")
            assert probe.status_code == 200, probe.text
            body = probe.json()
            assert body["status"] == "connected", body
            assert body["tools_count"] > 0, "expected real tools from the spawned MCP server"
            daemon.mark(f"mcp round trip done ({body['tools_count']} tools)")

            # 7. Revoke — real HTTP DELETE.
            revoke = await owner.delete(f"/api/v1/device/{device_id}")
            assert revoke.status_code == 200

            listing_after = await owner.get("/api/v1/device/list")
            assert listing_after.json()["devices"] == []

            # 8. The real background daemon must receive the revoke frame over
            #    its real socket and exit on its own.
            await daemon.wait_daemon_exits()
            daemon.mark("background daemon exited on revoke")
            assert "revoked" in daemon.daemon_log().lower(), daemon.daemon_log()
        finally:
            await owner.aclose()
            await daemon.stop_all()
            # Always, not only on failure: pytest shows this under "Captured
            # stdout teardown" for a failing test, and the daemon's own output
            # is otherwise discarded — which is why the last CI timeout could
            # not be attributed to a phase at all. The detached daemon logs to a
            # file, not the parent's stdout, so surface both.
            print(f"\n--- bridge daemon timeline ---\n{daemon.dump()}")
            print(f"\n--- detached tunnel daemon.log ---\n{daemon.daemon_log()}")


class TestDeviceServerRemoval:
    """Removing a device MCP server keeps the cloud and the daemon in sync,
    driven end to end through the real daemon + real HTTP (no internal calls)."""

    async def _pair_and_expose_everything(
        self, daemon: BridgeDaemon, owner: httpx.AsyncClient, api_url: str, entry: Path
    ) -> str:
        """Pair the daemon, expose the real everything server, wait until the
        cloud sees the device online. Returns the device_id."""
        await daemon.start_login(api_url, "e2e-removal-machine")
        user_code = await daemon.wait_for_user_code()
        approve = await owner.post("/api/v1/device/pair/approve", json={"user_code": user_code})
        assert approve.status_code == 200, approve.text
        device_id = approve.json()["device_id"]
        await daemon.wait_login_complete()
        daemon.write_config([everything_server(entry)])
        await daemon.start_up()
        await wait_device_online(owner, device_id)
        return device_id

    async def test_gaia_bridge_rm_removes_the_server_from_the_cloud(
        self,
        tmp_path,
        live_api_server,
        clean_bridge_tables,
        everything_server_cached,
        warm_cli,
        make_pro_subscription,
    ):
        """Device-initiated removal: `gaia bridge rm` drops the server from local
        config AND calls DELETE /device/servers/{key}, so the cloud row goes too."""
        owner_id = "device-rm-owner"
        # The tunnel is paid-only (device_ws.py): a free owner's daemon never comes online.
        await make_pro_subscription(owner_id)
        daemon = BridgeDaemon(tmp_path / "home")
        owner = _client(live_api_server.url, owner_id)
        try:
            await self._pair_and_expose_everything(
                daemon, owner, live_api_server.url, everything_server_cached
            )
            listing = await owner.get("/api/v1/device/list")
            keys = [s["server_key"] for s in listing.json()["devices"][0]["servers"]]
            assert keys == ["everything"], keys
            daemon.mark("server registered in cloud")

            output = await daemon.run_bridge_command("rm", "everything")
            assert "Removed 'everything'" in output, output
            daemon.mark("gaia bridge rm done")

            listing_after = await owner.get("/api/v1/device/list")
            assert listing_after.json()["devices"][0]["servers"] == []
            assert daemon.read_config_keys() == set()
        finally:
            await owner.aclose()
            await daemon.stop_all()
            print(f"\n--- bridge daemon timeline ---\n{daemon.dump()}")
            print(f"\n--- detached tunnel daemon.log ---\n{daemon.daemon_log()}")

    async def test_deleting_the_integration_makes_the_daemon_forget_the_server(
        self,
        tmp_path,
        live_api_server,
        clean_bridge_tables,
        everything_server_cached,
        warm_cli,
        make_pro_subscription,
    ):
        """Cloud-initiated delete: deleting the device integration deletes the
        Postgres row AND sends a server.remove frame down the live tunnel, so the
        daemon forgets the server and can't re-register it on reconnect."""
        owner_id = "device-del-owner"
        # The tunnel is paid-only (device_ws.py): a free owner's daemon never comes online.
        await make_pro_subscription(owner_id)
        daemon = BridgeDaemon(tmp_path / "home")
        owner = _client(live_api_server.url, owner_id)
        try:
            await self._pair_and_expose_everything(
                daemon, owner, live_api_server.url, everything_server_cached
            )
            server = (await owner.get("/api/v1/device/list")).json()["devices"][0]["servers"][0]
            integration_id = server["integration_id"]
            daemon.mark("server registered in cloud")

            deleted = await owner.delete(f"/api/v1/integrations/custom/{integration_id}")
            assert deleted.status_code == 200, deleted.text
            daemon.mark("integration deleted in cloud")

            # The cloud drops the server row immediately...
            listing_after = await owner.get("/api/v1/device/list")
            assert listing_after.json()["devices"][0]["servers"] == []

            # ...and the running daemon receives server.remove over its live socket
            # and forgets the server. Poll its config until the frame lands.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 10.0
            while daemon.read_config_keys() != set():
                if loop.time() >= deadline:
                    raise AssertionError(
                        f"daemon still exposes {daemon.read_config_keys()} after delete; "
                        f"daemon.log:\n{daemon.daemon_log()}"
                    )
                await asyncio.sleep(0.1)
            assert "removed server 'everything'" in daemon.daemon_log().lower()
        finally:
            await owner.aclose()
            await daemon.stop_all()
            print(f"\n--- bridge daemon timeline ---\n{daemon.dump()}")
            print(f"\n--- detached tunnel daemon.log ---\n{daemon.daemon_log()}")


class TestCrossUserIsolation:
    async def test_intruder_cannot_see_or_revoke_anothers_device(
        self, tmp_path, live_api_server, clean_bridge_tables, warm_cli
    ):
        daemon = BridgeDaemon(tmp_path / "home")
        owner = _client(live_api_server.url, "cross-user-owner")
        intruder = _client(live_api_server.url, "cross-user-intruder")
        try:
            await daemon.start_login(live_api_server.url, "cross-user-test-machine")
            user_code = await daemon.wait_for_user_code()

            approve = await owner.post("/api/v1/device/pair/approve", json={"user_code": user_code})
            device_id = approve.json()["device_id"]
            await daemon.wait_login_complete()

            intruder_listing = await intruder.get("/api/v1/device/list")
            assert intruder_listing.json()["devices"] == []

            intruder_revoke = await intruder.delete(f"/api/v1/device/{device_id}")
            assert intruder_revoke.status_code == 404

            owner_listing = await owner.get("/api/v1/device/list")
            assert len(owner_listing.json()["devices"]) == 1
        finally:
            await owner.aclose()
            await intruder.aclose()
            await daemon.stop_all()


class TestDaemonStartupDiagnostics:
    async def test_a_dead_login_child_is_reported_as_a_death_not_as_silence(
        self, tmp_path, warm_cli
    ):
        """A `gaia bridge login` that exits must fail the wait immediately, naming
        its exit code — not time out looking like a slow one.

        This is the gap that cost two days of CI triage: before the liveness
        guard, `wait_for_user_code` only ever reported the collected output, so a
        child that died at 0.8s and a child still transpiling at 10s produced the
        same message. Pointing the CLI at a port nothing is listening on makes
        `startPairing`'s fetch reject, which is a real, unmocked death of the
        real child process.
        """
        daemon = BridgeDaemon(tmp_path / "home")
        try:
            await daemon.start_login(f"http://127.0.0.1:{pick_free_port()}", "dead-child")
            started = time.monotonic()
            with pytest.raises(AssertionError) as excinfo:
                await daemon.wait_for_user_code()
            elapsed = time.monotonic() - started

            message = str(excinfo.value)
            assert "exit code 1" in message, message
            # The child's own last words, which say *why* it died.
            assert "fetch failed" in message, message
            # And it must not burn the readiness budget on a process already gone.
            assert elapsed < USER_CODE_TIMEOUT_SECONDS / 2, (
                f"waited {elapsed:.1f}s for a child that had already exited"
            )
        finally:
            await daemon.stop_all()


class TestPairingCodeExpiry:
    async def test_expired_pairing_code_is_rejected(self, live_api_server, real_redis):
        """Waiting out the real 15-minute TTL isn't practical in a test run.
        Expiring the pairing key directly in Redis is the one part of this test
        not driven through the wire — the poll response itself is still a real
        API call and is what's actually asserted on.
        """
        async with _client(live_api_server.url) as client:
            start = await client.post(
                "/api/v1/device/pair/start",
                json={"name": "expiry-test", "platform": "test", "daemon_version": "0.0.0"},
            )
            device_code = start.json()["device_code"]

            await real_redis.delete(f"device:pairing:{device_code}")

            poll = await client.post("/api/v1/device/pair/poll", json={"device_code": device_code})
            assert poll.status_code == 200
            assert poll.json()["status"] == "expired"


class TestRefreshTokenReuseDetection:
    async def test_replaying_a_rotated_refresh_token_revokes_the_device(
        self, live_api_server, real_redis, clean_bridge_tables
    ):
        """Same carve-out as pairing expiry: the 60s post-rotation grace window
        can't be skipped through any exposed API, so the grace-window Redis key
        is cleared directly to force the genuine reuse-detection branch instead
        of the lost-response retry branch. Every assertion is still made
        through real /device/token responses.
        """
        owner = _client(live_api_server.url, "reuse-test-owner")
        anon = _client(live_api_server.url)
        try:
            start = await anon.post(
                "/api/v1/device/pair/start",
                json={"name": "reuse-test", "platform": "test", "daemon_version": "0.0.0"},
            )
            user_code = start.json()["user_code"]
            device_code = start.json()["device_code"]

            approve = await owner.post("/api/v1/device/pair/approve", json={"user_code": user_code})
            assert approve.status_code == 200, approve.text

            poll = await anon.post("/api/v1/device/pair/poll", json={"device_code": device_code})
            original_token = poll.json()["refresh_token"]

            first_exchange = await anon.post(
                "/api/v1/device/token", json={"refresh_token": original_token}
            )
            assert first_exchange.status_code == 200, first_exchange.text
            rotated_token = first_exchange.json()["refresh_token"]

            token_hash = hashlib.sha256(original_token.encode()).hexdigest()
            await real_redis.delete(f"device:refreshretry:{token_hash}")

            replay = await anon.post("/api/v1/device/token", json={"refresh_token": original_token})
            assert replay.status_code == 401, replay.text

            # Reuse detection revokes the device outright — even the freshly
            # rotated, otherwise-legitimate token must now fail too.
            rotated_exchange = await anon.post(
                "/api/v1/device/token", json={"refresh_token": rotated_token}
            )
            assert rotated_exchange.status_code == 401, rotated_exchange.text

            owner_listing = await owner.get("/api/v1/device/list")
            assert owner_listing.json()["devices"] == []
        finally:
            await owner.aclose()
            await anon.aclose()
