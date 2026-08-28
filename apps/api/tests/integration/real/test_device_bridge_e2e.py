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

pytestmark = [pytest.mark.service, pytest.mark.slow]

# Anchor by walking up to the repo root that owns the CLI package (which ships
# `gaia bridge`), rather than by depth from this test file — the file may move
# within the tests tree.
CLI_DIR = next(
    parent / "packages" / "cli"
    for parent in Path(__file__).resolve().parents
    if (parent / "packages" / "cli").is_dir()
)
# tsx's bin location depends on pnpm's node-linker: the isolated linker (used
# inside the Dagger harness, which never sees the repo .npmrc) puts it in the
# CLI package's own node_modules/.bin; the hoisted linker (dev machines and
# CI runners, per .npmrc) only creates the repo-root node_modules/.bin.
_CLI_TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
_ROOT_TSX = CLI_DIR.parent.parent / "node_modules" / ".bin" / "tsx"
TSX_BIN = _CLI_TSX if _CLI_TSX.exists() else _ROOT_TSX
EVERYTHING_PACKAGE = "@modelcontextprotocol/server-everything"
# `--offline` (not `-y`) is load-bearing, not a micro-optimization. The daemon
# only spawns a stdio server when the cloud opens a tunnel session, i.e. *inside*
# the /api/v1/mcp/test request the round-trip test times. With `-y`, npm resolves
# the package against the registry on every spawn, and a registry request that
# stalls is retried with npm's default backoff (fetch-retries=2,
# fetch-retry-mintimeout=10s, doubling) — 10s + 20s = 30s added to the spawn
# before it falls back to the cache. That is exactly the 30s dead gap seen
# between "[MCP] Opening device-tunnel MCP session" and the tools coming back on
# a loaded CI box, and it blew the client read timeout below.
# `--offline` resolves from the npx cache only, so the spawn is bounded by local
# work: measured 0.87-0.90s vs 1.5-2.1s idle / 3.3-4.4s at load average 12 for
# `-y` on the CI runner. `everything_server_cached` fills that cache first.
EVERYTHING_SERVER = {
    "type": "stdio",
    "key": "everything",
    "name": "Everything Test Server",
    "command": "npx",
    "args": ["--offline", EVERYTHING_PACKAGE, "stdio"],
    "env": {},
}

USER_CODE_RE = re.compile(r"enter this code:\s*([A-Z0-9-]+)")


@cache
def _npm_cache_dir() -> str:
    """The npm/npx cache the daemon's `npx --offline` must read from.

    The daemon runs under a scratch ``HOME`` (so it can never touch a
    developer's real pairing), and npm derives both its content cache and the
    `_npx` package directory from ``HOME``. Left alone, that means the prewarm
    below fills the *runner's* cache while the daemon reads an empty one and
    `npx --offline` dies with ENOTCACHED — the scratch HOME silently defeats
    the prewarm. Pinning ``npm_config_cache`` to one real directory is what
    makes "warm it once, spawn from cache" actually true, while leaving HOME
    isolated for everything else.
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


class BridgeDaemon:
    """Drives the real ``gaia bridge`` CLI as a subprocess, isolated to a
    scratch ``HOME`` so it can never touch a developer's real pairing.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self.login_process: asyncio.subprocess.Process | None = None
        self.up_process: asyncio.subprocess.Process | None = None
        self.login_output: list[str] = []
        self.up_output: list[str] = []
        # One merged, timestamped view of daemon stdout/stderr plus the test's
        # own phase marks. Without it a timeout tells you only that 35s passed,
        # not which of pair/exchange/connect/open/list spent them.
        self.transcript: list[str] = []
        self._t0 = time.monotonic()
        self._tasks: list[asyncio.Task] = []

    async def _spawn(self, *args: str) -> asyncio.subprocess.Process:
        env = {
            **os.environ,
            "HOME": str(self.home),
            # See _npm_cache_dir: the scratch HOME must not take the npx cache
            # with it, or `npx --offline` inside the timed request goes cold.
            "npm_config_cache": _npm_cache_dir(),
        }
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

    async def wait_for_user_code(self, timeout: float = 10.0) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            match = USER_CODE_RE.search("".join(self.login_output))
            if match:
                return match.group(1)
            if loop.time() >= deadline:
                raise AssertionError(
                    f"user_code never appeared in `gaia bridge login` output: "
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

    async def start_up(self) -> None:
        self.up_process = await self._spawn("up")
        self._pump(self.up_process.stdout, self.up_output, "up/out")
        self._pump(self.up_process.stderr, self.up_output, "up/err")

    async def wait_connected(self, timeout: float = 30.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            output = "".join(self.up_output)
            if "connected — exposing" in output:
                return
            assert self.up_process is not None
            if self.up_process.returncode is not None:
                raise AssertionError(f"`gaia bridge up` exited early: {output}")
            if loop.time() >= deadline:
                raise AssertionError(f"tunnel never reported connected: {output}")
            await asyncio.sleep(0.1)

    async def wait_exits_on_its_own(self, timeout: float = 10.0) -> None:
        """After a revoke, the real daemon must drop the tunnel itself — proof
        revocation propagates over the wire, not just as a Postgres flag."""
        assert self.up_process is not None
        await asyncio.wait_for(self.up_process.wait(), timeout=timeout)

    async def stop_all(self) -> None:
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


@pytest.fixture(scope="session")
def everything_server_cached() -> None:
    """Fetch the third-party MCP server into the npx cache once, before any test.

    The daemon spawns it with ``npx --offline`` from inside the request under
    test, and offline mode reads the cache instead of the registry — so the
    fetch has to happen somewhere, and here is the only place where it is not
    being timed. Feeding the real spawn a closed stdin is what makes this a
    fetch rather than an approximation of one: the server sees EOF on its stdio
    transport and exits 0 on its own, so the cache is populated by exactly the
    command the daemon will run.
    """
    # Generous: this is setup, and on a cold runner it is a real npm download.
    warm = subprocess.run(
        ["npx", "-y", EVERYTHING_PACKAGE, "stdio"],
        stdin=subprocess.DEVNULL,
        # Same cache the daemon is pinned to (see _npm_cache_dir) — warming any
        # other one warms nothing that the timed spawn will read.
        env={**os.environ, "npm_config_cache": _npm_cache_dir()},
        capture_output=True,
        text=True,
        timeout=180.0,
        check=False,
    )
    assert warm.returncode == 0, (
        f"could not fetch {EVERYTHING_PACKAGE} into the npx cache "
        f"(rc={warm.returncode}): {warm.stderr}"
    )


def _client(base_url: str, user_id: str | None = None) -> httpx.AsyncClient:
    headers = {"x-test-user-id": user_id} if user_id else {}
    # Sized from the measured cost of the slowest call these clients make — the
    # /api/v1/mcp/test round trip: open the tunnel session (the daemon spawns the
    # local MCP server from the npx cache, measured 0.87-0.90s), then initialize
    # + list_tools over Redis pub/sub. Well under a second of real work; 35s is
    # the headroom for a loaded runner, not a budget for network fetches. Keep
    # the npx spawn cache-only (see EVERYTHING_SERVER) rather than raising this.
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=35.0)


class TestFullDeviceLifecycle:
    async def test_pair_up_real_mcp_round_trip_then_revoke(
        self, tmp_path, live_api_server, clean_bridge_tables, everything_server_cached
    ):
        """The golden path, end to end, with no shortcuts anywhere in the chain."""
        daemon = BridgeDaemon(tmp_path / "home")
        owner = _client(live_api_server.url, "device-e2e-owner")
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
            daemon.write_config([EVERYTHING_SERVER])
            await daemon.start_up()
            await daemon.wait_connected()
            daemon.mark("tunnel connected (token exchanged, ws up)")
            # Regression guard: tunnel.ts's connectOnce() once resolved its
            # connection promise on the socket's `open` event instead of
            # `close`, so run() immediately looped and opened a new socket on
            # every tick — a real reconnect storm a live daemon process (and
            # only a live daemon process) can actually surface.
            await asyncio.sleep(0.5)
            assert "reconnecting in" not in "".join(daemon.up_output)

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

            # 8. The real daemon must receive the revoke frame over its real
            #    socket and exit on its own.
            await daemon.wait_exits_on_its_own()
            daemon.mark("daemon exited on revoke")
            assert "revoked" in "".join(daemon.up_output).lower()
        finally:
            await owner.aclose()
            await daemon.stop_all()
            # Always, not only on failure: pytest shows this under "Captured
            # stdout teardown" for a failing test, and the daemon's own output
            # is otherwise discarded — which is why the last CI timeout could
            # not be attributed to a phase at all.
            print(f"\n--- bridge daemon timeline ---\n{daemon.dump()}")


class TestCrossUserIsolation:
    async def test_intruder_cannot_see_or_revoke_anothers_device(
        self, tmp_path, live_api_server, clean_bridge_tables
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
