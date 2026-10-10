"""True black-box E2E tests for the device bridge, driven only through the real wire protocol as a real user/device would.

The daemon runs as a real Node subprocess (via tsx); the signed-in-user side
is driven by real HTTP calls against a real, live GAIA API instance (see
live_api_server in conftest.py); the local MCP server is the real, official
@modelcontextprotocol/server-everything reference server over real stdio.

Direct Redis access, called out inline, covers only a 15-minute pairing-code
expiry and a 60-second refresh-token retry grace window a real client can't
otherwise produce without waiting it out — every assertion is still made
through the real API response.

Contrast with test_device_bridge_real.py, which calls internal Python
functions directly against real Redis to regression-test plumbing bugs — a
different, still-valuable tier.
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
# tsx's bin location depends on pnpm's node-linker: the default isolated
# linker (no .npmrc) puts it in the CLI package's own node_modules/.bin; the
# repo-root fallback covers a hoisted install (older checkout, or node-linker set).
_CLI_TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
_ROOT_TSX = CLI_DIR.parent.parent / "node_modules" / ".bin" / "tsx"
TSX_BIN = _CLI_TSX if _CLI_TSX.exists() else _ROOT_TSX
EVERYTHING_PACKAGE = "@modelcontextprotocol/server-everything"
# Pinned — unpinned re-resolves `latest` every run (15-19s on CI). Bump with
# `npx -y @modelcontextprotocol/server-everything@<new> stdio </dev/null`, but
# only to a version the self-hosted npm mirror already has (unmirrored -> ETARGET, per 2026.8.31).
EVERYTHING_VERSION = "2026.8.18"


@cache
def _npm_cache_dir() -> str:
    """Where everything_server_cached installs the server and finds it again.

    npm derives both its content cache and the _npx package directory from
    HOME, so leaving it implicit means the install and the lookup can land
    in different places depending on whose HOME is set. Naming one real
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

# Measured prefix (node boot + tsx transpile + one HTTP round trip): 0.76s dev
# laptop, ~1s CI idle; golden path 5.0s idle (run 33302182969), contended to
# 4.1-9.5s with ~50% empty-transcript failures (run 33301137881) — a dead child now fails in under a second via wait_for_user_code's liveness check.
USER_CODE_TIMEOUT_SECONDS = 60.0


def everything_server(entry: Path) -> dict:
    """Build the third-party stdio MCP server config, spawning entry directly with node instead of npx.

    Inside the timed /api/v1/mcp/test request, resolving via npx measured a
    5.3s idle / 9.4-15.2s under-load gap between tunnel-open and server
    banner — enough to blow a 28s round trip past the 35s client budget.
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
    """Drives the real gaia bridge CLI as a subprocess, isolated to a scratch HOME so it can never touch a developer's real pairing."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.login_process: asyncio.subprocess.Process | None = None
        self.up_process: asyncio.subprocess.Process | None = None
        # The detached `up --serve` tunnel daemon `gaia bridge up` spawns; not a
        # child of this process (double-forks and exits), so it's tracked by the
        # pid written to <HOME>/.gaia/bridge/daemon.pid, not a Process handle.
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
        """Let the output pumps reach EOF so a dead child's last words make it into the raised message."""
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
            # Liveness guard: without it a crashed vs. merely-slow child both report
            # only after the full timeout — this ambiguity stayed a CI mystery for
            # two days with an empty transcript.
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
        """Return the detached tunnel daemon's own log.

        gaia bridge up runs the tunnel in a background --serve child whose
        stdout/stderr are redirected here, so the daemon's connect/revoke
        lines land in this file rather than the (already-exited) parent's stdout.
        """
        log_file = self._daemon_dir() / "daemon.log"
        return log_file.read_text(errors="replace") if log_file.exists() else ""

    async def start_up(self, timeout: float = 30.0) -> None:
        """Run gaia bridge up and wait for it to background itself.

        It registers configured servers, spawns the detached tunnel daemon,
        prints the background notice, and exits 0 — that exit is success, not
        failure. Captures the daemon's pid so teardown can reap it.
        """
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
        """Run a one-shot gaia bridge command and return its combined output.

        Asserts a clean exit.
        """
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
        """Return the server keys the daemon currently has in its local config.json."""
        config_file = self._daemon_dir() / "config.json"
        if not config_file.exists():
            return set()
        servers = json.loads(config_file.read_text()).get("servers", [])
        return {s["key"] for s in servers}

    async def wait_daemon_exits(self, timeout: float = 10.0) -> None:
        """Wait for the real background daemon to drop the tunnel and exit on its own.

        This is proof revocation propagates over the wire, not just as a
        Postgres flag. The daemon is detached, so wait on its pid, not a handle.
        """
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
        # Reap the detached daemon FIRST — `gaia bridge up` spawns it detached and
        # exits, so it's nobody's child (a leaked `--serve` process happened once).
        # Pidfile stays after revoke (only `gaia bridge down` unlinks it); absent when no tunnel was ever brought up.
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
    """Return the pinned server's entry script if npx has already installed it, else None."""
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
    """Fetch the third-party MCP server once, untimed, before any test.

    A closed stdin makes this a real fetch, not an approximation: the server
    sees EOF and exits 0 on its own, installed by the exact command a user
    would run. A warm cache skips the npx step entirely, since the pinned
    version is already on disk.
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

    This pays node boot plus tsx's transpile outside the timed window, and
    turns an unrunnable CLI (missing tsx, a dangling symlink, a node/ABI
    mismatch) into a named failure here instead of a silent "user_code never
    appeared" that looks like a timing flake.
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
    # Sized for the slowest call these clients make: /api/v1/mcp/test's tunnel
    # open + initialize + list_tools round trip. 35s is headroom for a loaded
    # runner, not a startup budget — keep spawn a direct node exec, not this.
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=35.0)


OWNER_USER_ID = "device-e2e-owner"


async def wait_device_online(
    client: httpx.AsyncClient, device_id: str, *, timeout: float = 30.0
) -> None:
    """Poll the real /device/list until the cloud reports the device online.

    Presence flips when the daemon's tunnel WebSocket connects and sends its
    HELLO — the backend-visible proof the backgrounded daemon came up, since
    "connected — exposing" now goes to daemon.log, not the parent's stdout.
    """
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
        """Warm-connect makes the server's tools discoverable without hitting /mcp/test.

        No ARQ worker runs in this harness, so the task is invoked inline —
        this still exercises the real tunnel connect + Chroma index + DB
        record, just not the queue hop itself.
        """
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
        # (device_ws.py); without it the handshake 403s and nothing starts. A
        # free user's rejection is covered by test_device_ws_paid_only_gate.py.
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
            # Regression guard: connectOnce() once resolved on the socket's `open`
            # event instead of `close`, causing a tight reconnect-loop storm that
            # only a live daemon process surfaces. Tunnel logs land in daemon.log now.
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
            # Always, not only on failure: pytest shows this under "Captured stdout
            # teardown", and discarding it is why a past CI timeout couldn't be
            # attributed to any phase. The daemon logs to a file, not stdout — print both.
            print(f"\n--- bridge daemon timeline ---\n{daemon.dump()}")
            print(f"\n--- detached tunnel daemon.log ---\n{daemon.daemon_log()}")


class TestDeviceServerRemoval:
    """Remove a device MCP server end to end, through the real daemon and real HTTP (no internal calls)."""

    async def _pair_and_expose_everything(
        self, daemon: BridgeDaemon, owner: httpx.AsyncClient, api_url: str, entry: Path
    ) -> str:
        """Pair the daemon, expose the everything server, wait for it online; returns the device_id."""
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
        """Device-initiated: gaia bridge rm clears local config and the cloud row."""
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
        """Cloud-initiated: deleting the integration sends a server.remove frame down the live tunnel."""
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

            # ...and the running daemon receives server.remove over its live socket,
            # forgets the server, then logs it. Poll both: the log line is written
            # after the config, so checking it the instant the config clears races.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 10.0
            while (
                daemon.read_config_keys() != set()
                or "removed server 'everything'" not in daemon.daemon_log().lower()
            ):
                if loop.time() >= deadline:
                    raise AssertionError(
                        f"daemon still exposes {daemon.read_config_keys()} after delete; "
                        f"daemon.log:\n{daemon.daemon_log()}"
                    )
                await asyncio.sleep(0.1)
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
        """Regression: a dead child once looked like a slow one until timeout (cost 2 days of CI triage)."""
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
        """Expires the pairing key directly in Redis rather than waiting out the real 15-minute TTL; the poll response asserted on is still real."""
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
        """Clears the 60s post-rotation grace-window Redis key directly, since no exposed API can skip it, to force the real reuse-detection branch."""
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
