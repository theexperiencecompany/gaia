"""Launch Obscura: a CDP server (obscura serve) on a free port, not a chrome-with-a-debug-flag.

The interactive browser host and the crawl4ai engine start it the same way.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
import socket

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.browser_host.process import spawn_engine, stop_process, until_published
from app.config.browser_host_settings import browser_host_settings

_LOOPBACK = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class LaunchedEngine:
    """An engine process that has published its CDP endpoint."""

    proc: asyncio.subprocess.Process
    port: int
    ws_url: str

    @property
    def http_url(self) -> str:
        """The DevTools HTTP endpoint, for clients that discover the websocket themselves."""
        # The engine's DevTools endpoint on loopback speaks plain HTTP only.
        return f"http://{_LOOPBACK}:{self.port}"  # NOSONAR python:S5332


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
    """Return the environment an Obscura process runs with: ours plus its script deadline."""
    return {
        **os.environ,
        "OBSCURA_SCRIPT_DEADLINE_MS": str(
            browser_host_settings.OBSCURA_SCRIPT_DEADLINE_SECONDS * 1000
        ),
    }


def _json_version_reader(
    client: httpx.AsyncClient, port: int
) -> Callable[[], Awaitable[str | None]]:
    """Read the root webSocketDebuggerUrl off /json/version; None while nothing answers there."""

    async def read() -> str | None:
        try:
            # Loopback DevTools endpoint: plain HTTP only.
            url = f"http://{_LOOPBACK}:{port}/json/version"  # NOSONAR python:S5332
            resp = await client.get(url)
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
