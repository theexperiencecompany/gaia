"""Engine process primitives: the Obscura command, finding an endpoint, stopping a tree.

A stray engine on the same port must never be adopted, a failed launch must
leave nothing running, and a stop must take the engine's children with it.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import psutil
import pytest

from app.browser_host import obscura_launch
from app.browser_host.obscura_launch import (
    EngineLaunchError,
    free_local_port,
    launch_obscura,
    obscura_serve_argv,
    obscura_serve_env,
    process_tree_rss_mb,
    stop_process,
    until_published,
)
from app.config.browser_host_settings import browser_host_settings

pytestmark = pytest.mark.unit

_WS = "ws://127.0.0.1:9333/devtools/browser/abc"


class _Proc:
    def __init__(self, returncode: int | None = None) -> None:
        self.pid = 999_999_999
        self.returncode = returncode
        self.signals: list[str] = []

    def terminate(self) -> None:
        self.signals.append("term")
        self.returncode = -15

    def kill(self) -> None:
        self.signals.append("kill")
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def test_obscura_is_served_stealthed_on_the_port_it_is_given_and_never_privately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")

    assert obscura_serve_argv(9931) == [
        "/opt/obscura/obscura",
        "serve",
        "--port",
        "9931",
        "--stealth",
    ]


def test_obscura_without_a_binary_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", None)

    with pytest.raises(RuntimeError, match="OBSCURA_BIN"):
        obscura_serve_argv(9931)


def test_obscura_receives_both_load_deadlines_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_NAV_TIMEOUT_SECONDS", 45)
    monkeypatch.setattr(browser_host_settings, "OBSCURA_SCRIPT_DEADLINE_SECONDS", 7)
    monkeypatch.setenv("OBSCURA_PROBE_PASSTHROUGH", "kept")

    env = obscura_serve_env()

    assert env["OBSCURA_NAV_TIMEOUT_MS"] == "45000"
    assert env["OBSCURA_SCRIPT_DEADLINE_MS"] == "7000"
    assert env["OBSCURA_PROBE_PASSTHROUGH"] == "kept"


def test_a_free_port_is_one_nothing_listens_on() -> None:
    port = free_local_port()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def _version_client(*responses: httpx.Response) -> tuple[httpx.AsyncClient, list[str]]:
    asked: list[str] = []
    queue = list(responses)

    def _handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler)), asked


async def test_obscuras_endpoint_is_what_json_version_publishes_once_it_answers() -> None:
    client, asked = _version_client(
        httpx.Response(503),
        httpx.Response(200, json={"Browser": "x"}),
        httpx.Response(200, json={"webSocketDebuggerUrl": _WS}),
    )
    read = obscura_launch._json_version_reader(client, 9333)

    assert [await read(), await read(), await read()] == [None, None, _WS]
    assert asked == ["http://127.0.0.1:9333/json/version"] * 3


class _Exiting(_Proc):
    """An engine whose wait() returns only once the test lets it exit."""

    def __init__(self) -> None:
        super().__init__()
        self.exited = asyncio.Event()

    async def wait(self) -> int:
        await self.exited.wait()
        return self.returncode or 0


async def test_the_endpoint_is_returned_as_soon_as_it_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(obscura_launch, "_CDP_READY_POLL_SECONDS", 0.0)
    answers = iter([None, None, _WS])

    async def _read() -> str | None:
        return next(answers)

    assert await until_published(cast(Any, _Exiting()), _read) == _WS


async def test_an_engine_that_exits_first_is_never_mistaken_for_one_on_its_port() -> None:
    proc = _Exiting()
    stray_answers = asyncio.Event()

    async def _read() -> str | None:
        await stray_answers.wait()
        return _WS

    waiting = asyncio.create_task(until_published(cast(Any, proc), _read))
    await asyncio.sleep(0)
    proc.returncode = 1
    proc.exited.set()

    with pytest.raises(EngineLaunchError, match="exited with 1"):
        await asyncio.wait_for(waiting, 1.0)


async def test_an_endpoint_that_never_appears_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obscura_launch, "_CDP_READY_TIMEOUT_SECONDS", 0.01)

    async def _never() -> str | None:
        return None

    with pytest.raises(EngineLaunchError, match="did not publish its CDP endpoint in time"):
        await until_published(cast(Any, _Exiting()), _never)


async def test_obscura_is_launched_on_a_free_port_and_stopped_when_it_never_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")
    monkeypatch.setattr(obscura_launch, "free_local_port", lambda: 9444)
    proc = _Proc()
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(obscura_launch.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        obscura_launch, "until_published", AsyncMock(side_effect=EngineLaunchError("x"))
    )

    with pytest.raises(EngineLaunchError):
        await launch_obscura()

    assert spawn.await_args is not None
    assert spawn.await_args.args == ("/opt/obscura/obscura", "serve", "--port", "9444", "--stealth")
    assert spawn.await_args.kwargs["stdout"] is subprocess.DEVNULL
    assert spawn.await_args.kwargs["env"]["OBSCURA_NAV_TIMEOUT_MS"]
    assert proc.signals == ["term"]


async def test_a_launched_obscura_knows_its_port_and_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")
    monkeypatch.setattr(obscura_launch, "free_local_port", lambda: 9444)
    monkeypatch.setattr(obscura_launch, "spawn_engine", AsyncMock(return_value=_Proc()))
    monkeypatch.setattr(obscura_launch, "until_published", AsyncMock(return_value=_WS))

    launched = await launch_obscura()

    assert (launched.port, launched.ws_url, launched.http_url) == (
        9444,
        _WS,
        "http://127.0.0.1:9444",
    )


async def test_a_graceful_stop_asks_first_and_a_failed_engine_is_killed_outright() -> None:
    polite, failed, gone = _Proc(), _Proc(), _Proc(returncode=0)

    await stop_process(cast(Any, polite))
    await stop_process(cast(Any, failed), graceful=False)
    await stop_process(cast(Any, gone))

    assert polite.signals == ["term"]
    assert failed.signals == ["kill"]
    assert gone.signals == []


class _StubbornProc(_Proc):
    """An engine that never acts on terminate, only on kill."""

    def __init__(self) -> None:
        super().__init__()
        self.exited = asyncio.Event()

    def terminate(self) -> None:
        self.signals.append("term")

    def kill(self) -> None:
        super().kill()
        self.exited.set()

    async def wait(self) -> int:
        await self.exited.wait()
        return -9


async def test_an_engine_that_ignores_the_request_is_killed_after_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(obscura_launch, "_STOP_GRACE_SECONDS", 0.01)
    proc = _StubbornProc()

    await stop_process(cast(Any, proc))

    assert proc.signals == ["term", "kill"]


async def test_a_stop_takes_the_engines_children_with_it() -> None:
    parent = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)",
    )
    for _ in range(100):
        children = psutil.Process(parent.pid).children(recursive=True)
        if children:
            break
        await asyncio.sleep(0.02)

    await stop_process(parent)

    assert children
    assert not any(
        child.is_running() and child.status() != psutil.STATUS_ZOMBIE for child in children
    )


def test_a_process_trees_memory_is_the_sum_of_its_members(monkeypatch: pytest.MonkeyPatch) -> None:
    child, gone = MagicMock(), MagicMock()
    child.memory_info.return_value.rss = 1024 * 1024
    gone.memory_info.side_effect = psutil.NoSuchProcess(1)
    root = MagicMock()
    root.memory_info.return_value.rss = 3 * 1024 * 1024
    root.children.return_value = [child, gone]
    monkeypatch.setattr(obscura_launch.psutil, "Process", MagicMock(return_value=root))

    assert process_tree_rss_mb(1) == 4.0


def test_a_vanished_process_has_no_memory_reading() -> None:
    assert process_tree_rss_mb(999_999_999) is None
