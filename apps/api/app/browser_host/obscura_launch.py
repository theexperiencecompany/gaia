"""Process primitives for a CDP engine: spawn Obscura, find its endpoint, stop it.

Obscura is a CDP server (obscura serve), not a chrome-with-a-debug-flag. The
interactive browser host and the crawl4ai engine start it the same way, and the
host's Chromium shares the endpoint discovery and the teardown, so one engine
process is launched, found and stopped one way everywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass
import os
import socket

# spawns the engine via create_subprocess_exec with a fixed argv from settings,
# never a shell; the import is an intended, confirmed use.
import subprocess  # nosec B404

import httpx
import psutil
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.browser_host_settings import browser_host_settings

# Budget for an engine to publish its DevTools endpoint after launch.
_CDP_READY_TIMEOUT_SECONDS = 30.0
# Neither engine announces readiness, so where it publishes is asked until it answers.
_CDP_READY_POLL_SECONDS = 0.2
# How long a terminated engine gets to exit before it is killed.
_STOP_GRACE_SECONDS = 5.0
_LOOPBACK = "127.0.0.1"
_BYTES_PER_MB = 1024 * 1024


class EngineLaunchError(RuntimeError):
    """Raised when an engine process exits or never publishes its CDP endpoint."""


@dataclass(frozen=True, slots=True)
class LaunchedEngine:
    """An engine process that has published its CDP endpoint."""

    proc: asyncio.subprocess.Process
    port: int
    ws_url: str

    @property
    def http_url(self) -> str:
        """The DevTools HTTP endpoint, for clients that discover the websocket themselves."""
        return f"http://{_LOOPBACK}:{self.port}"


class _DevToolsVersion(BaseModel):
    """The one field of the /json/version document the launcher waits for."""

    model_config = ConfigDict(extra="ignore")

    web_socket_debugger_url: str = Field(alias="webSocketDebuggerUrl")


def free_local_port() -> int:
    """Return a loopback port nothing listens on now, for an engine that only serves a port it is named."""
    with socket.socket() as probe:
        probe.bind((_LOOPBACK, 0))
        port: int = probe.getsockname()[1]
    return port


def obscura_serve_argv(port: int) -> list[str]:
    """Build the obscura serve argv for port, stealthed.

    Raises when OBSCURA_BIN is unset: fail loud, never silently fall back to another engine.
    """
    obscura_bin = browser_host_settings.OBSCURA_BIN
    if not obscura_bin:
        raise RuntimeError("Obscura requires OBSCURA_BIN to be set")
    return [obscura_bin, "serve", "--port", str(port), "--stealth"]


def obscura_serve_env() -> dict[str, str]:
    """Return the environment an Obscura process runs with: ours plus its load deadlines."""
    return {
        **os.environ,
        "OBSCURA_NAV_TIMEOUT_MS": str(browser_host_settings.OBSCURA_NAV_TIMEOUT_SECONDS * 1000),
        "OBSCURA_SCRIPT_DEADLINE_MS": str(
            browser_host_settings.OBSCURA_SCRIPT_DEADLINE_SECONDS * 1000
        ),
    }


async def spawn_engine(argv: list[str], env: dict[str, str] | None) -> asyncio.subprocess.Process:
    """Start an engine process with its output discarded."""
    return await asyncio.create_subprocess_exec(
        *argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


async def until_published(
    proc: asyncio.subprocess.Process, read: Callable[[], Awaitable[str | None]]
) -> str:
    """Return the CDP endpoint read() finds once the engine has published it.

    Neither engine announces readiness, so read() is asked until it answers; the
    engine's exit is awaited beside it and fails the wait at once, so a stray
    engine on the same port is never mistaken for the one just launched.
    """

    async def _asked_until_answered() -> str:
        while True:
            found = await read()
            if found is not None:
                return found
            await asyncio.sleep(_CDP_READY_POLL_SECONDS)

    found = asyncio.ensure_future(_asked_until_answered())
    exited = asyncio.ensure_future(proc.wait())
    try:
        await asyncio.wait(
            {found, exited}, timeout=_CDP_READY_TIMEOUT_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        found.cancel()
        exited.cancel()
    if found.done() and not found.cancelled():
        return found.result()
    if proc.returncode is not None:
        raise EngineLaunchError(
            f"engine exited with {proc.returncode} before publishing its endpoint"
        )
    raise EngineLaunchError("engine did not publish its CDP endpoint in time")


def _json_version_reader(
    client: httpx.AsyncClient, port: int
) -> Callable[[], Awaitable[str | None]]:
    """Read the root webSocketDebuggerUrl off /json/version; None while nothing answers there."""

    async def read() -> str | None:
        try:
            resp = await client.get(f"http://{_LOOPBACK}:{port}/json/version")
            resp.raise_for_status()
            return _DevToolsVersion.model_validate(resp.json()).web_socket_debugger_url
        except (httpx.HTTPError, ValidationError):
            return None

    return read


async def launch_obscura() -> LaunchedEngine:
    """Start an Obscura on a free port once its CDP endpoint answers.

    The process is stopped before any failure propagates, so a failed launch leaves nothing behind.
    """
    port = free_local_port()
    proc = await spawn_engine(obscura_serve_argv(port), obscura_serve_env())
    try:
        async with httpx.AsyncClient() as client:
            ws_url = await until_published(proc, _json_version_reader(client, port))
    except BaseException:
        await stop_process(proc)
        raise
    return LaunchedEngine(proc=proc, port=port, ws_url=ws_url)


def process_tree_rss_mb(pid: int) -> float | None:
    """Resident memory of a process and all its children, or None when it cannot be read."""
    try:
        root = psutil.Process(pid)
        total: int = root.memory_info().rss
        for child in root.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.NoSuchProcess:
                continue
    except psutil.Error:
        return None
    return total / _BYTES_PER_MB


async def stop_process(proc: asyncio.subprocess.Process, *, graceful: bool = True) -> None:
    """Stop an engine and every process it started, and reap them.

    Graceful asks it to exit and kills it only past the grace period; a failed
    engine is killed outright, since a frozen one never acts on the request.
    Its children (renderers, render workers) are stopped too: they outlive the
    parent otherwise, holding memory and writing into its profile.
    """
    children = _children_of(proc.pid)
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            if graceful:
                proc.terminate()
            else:
                proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_STOP_GRACE_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
    await proc.wait()
    await asyncio.to_thread(_stop_all, children)


def _children_of(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def _stop_all(procs: list[psutil.Process]) -> None:
    """Terminate whatever of procs is still running, killing what outlives the grace period."""
    for proc in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.terminate()
    _, alive = psutil.wait_procs(procs, timeout=_STOP_GRACE_SECONDS)
    for proc in alive:
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.kill()
    # SIGKILL cannot be ignored, so the bound only matters for a process stuck in
    # uninterruptible sleep, which nothing can produce on demand to test it.
    psutil.wait_procs(alive, timeout=_STOP_GRACE_SECONDS)  # pragma: no mutate
