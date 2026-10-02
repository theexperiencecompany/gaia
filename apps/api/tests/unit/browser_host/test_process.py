"""An engine process from outside: finding its endpoint, measuring its tree, stopping it.

A stray engine on the same port must never be adopted, and a stop must take the
engine's children with it and nothing beside them.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any, cast
from unittest.mock import MagicMock

import psutil
import pytest

from app.browser_host import process
from app.browser_host.process import (
    EngineLaunchError,
    ProcessSampler,
    process_tree_rss_mb,
    stop_process,
    until_published,
)

pytestmark = pytest.mark.unit

_WS = "ws://127.0.0.1:9333/devtools/browser/abc"
_MB = 1024 * 1024


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
    monkeypatch.setattr(process, "_CDP_READY_POLL_SECONDS", 0.0)
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
    monkeypatch.setattr(process, "_CDP_READY_TIMEOUT_SECONDS", 0.01)

    async def _never() -> str | None:
        return None

    with pytest.raises(EngineLaunchError) as late:
        await until_published(cast(Any, _Exiting()), _never)
    assert late.value.args == ("engine did not publish its CDP endpoint in time",)


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
    monkeypatch.setattr(process, "_STOP_GRACE_SECONDS", 0.01)
    proc = _StubbornProc()

    await stop_process(cast(Any, proc))

    assert proc.signals == ["term", "kill"]


def _tree(root: Any) -> list[str]:
    """Lay out an engine whose child starts a grandchild that ignores SIGTERM.

    The grandchild says "ready" on the stdout it inherited once all three run.
    """
    grandchild = root / "grandchild.py"
    grandchild.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    child = root / "child.py"
    child.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(grandchild)!r}])\n"
        "time.sleep(60)\n"
    )
    engine = root / "engine.py"
    engine.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}])\n"
        "time.sleep(60)\n"
    )
    return [sys.executable, str(engine)]


def _alive(procs: list[psutil.Process]) -> list[psutil.Process]:
    return [p for p in procs if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]


async def test_a_stop_takes_the_whole_tree_and_nothing_beside_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(process, "_STOP_GRACE_SECONDS", 0.5)
    bystander = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(60)"
    )
    engine = await asyncio.create_subprocess_exec(*_tree(tmp_path), stdout=subprocess.PIPE)
    assert engine.stdout is not None
    assert await asyncio.wait_for(engine.stdout.readline(), 10.0) == b"ready\n"
    tree = psutil.Process(engine.pid).children(recursive=True)

    try:
        await asyncio.wait_for(stop_process(engine), 10.0)

        assert _alive(tree) == []
        assert bystander.returncode is None
    finally:
        bystander.kill()
        await bystander.wait()


async def test_a_dead_engine_that_has_not_been_reaped_is_stopped_without_complaint() -> None:
    class _Vanished(_Proc):
        def terminate(self) -> None:
            raise ProcessLookupError

        def kill(self) -> None:
            raise ProcessLookupError

        async def wait(self) -> int:
            self.returncode = -9
            return -9

    await stop_process(cast(Any, _Vanished()))
    await stop_process(cast(Any, _Vanished()), graceful=False)


def test_children_that_exit_while_being_stopped_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone, stubborn = MagicMock(), MagicMock()
    gone.terminate.side_effect = psutil.NoSuchProcess(1)
    stubborn.kill.side_effect = psutil.NoSuchProcess(2)
    monkeypatch.setattr(process.psutil, "wait_procs", lambda procs, timeout: ([], procs))

    process._stop_all([gone, stubborn])

    stubborn.terminate.assert_called_once_with()
    stubborn.kill.assert_called_once_with()


def test_a_process_trees_memory_is_the_sum_of_its_members(monkeypatch: pytest.MonkeyPatch) -> None:
    gone, child, grandchild = MagicMock(), MagicMock(), MagicMock()
    gone.memory_info.side_effect = psutil.NoSuchProcess(1)
    child.memory_info.return_value.rss = 1024 * 1024
    grandchild.memory_info.return_value.rss = 2 * 1024 * 1024
    root = MagicMock()
    root.memory_info.return_value.rss = 3 * 1024 * 1024
    root.children.return_value = [gone, child, grandchild]
    monkeypatch.setattr(process.psutil, "Process", MagicMock(return_value=root))

    assert process_tree_rss_mb(1) == 6.0
    root.children.assert_called_once_with(recursive=True)


async def test_an_engine_that_dies_just_as_it_is_killed_is_stopped_without_complaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process, "_STOP_GRACE_SECONDS", 0.01)

    class _GoneAtKill(_StubbornProc):
        def kill(self) -> None:
            self.exited.set()
            raise ProcessLookupError

    await stop_process(cast(Any, _GoneAtKill()))


def test_a_vanished_process_has_no_memory_reading() -> None:
    assert process_tree_rss_mb(999_999_999) is None


def _fake_proc(rss_mb: float, cpu: float) -> MagicMock:
    proc = MagicMock()
    proc.memory_info.return_value = MagicMock(rss=int(rss_mb * _MB))
    proc.cpu_percent.return_value = cpu
    return proc


def _sampler_over(root: MagicMock, monkeypatch: pytest.MonkeyPatch) -> ProcessSampler:
    """Return a real sampler whose process tree resolves to root."""
    monkeypatch.setattr(process.psutil, "Process", MagicMock(return_value=root))
    return ProcessSampler(4321)


def test_a_sample_sums_the_whole_tree_and_skips_a_child_that_exits_mid_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = _fake_proc(50.0, 5.0)
    gone.memory_info.side_effect = psutil.NoSuchProcess(99)
    gone.cpu_percent.side_effect = psutil.NoSuchProcess(99)
    root = _fake_proc(100.0, 10.0)
    root.children.side_effect = lambda recursive: (
        [gone, _fake_proc(50.0, 5.0), _fake_proc(25.0, 2.5)] if recursive else []
    )

    assert _sampler_over(root, monkeypatch).sample() == (175.0, 17.5)


def test_a_tree_that_cannot_be_read_has_no_sample_and_a_dead_pid_no_sampler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = MagicMock()
    root.children.side_effect = psutil.AccessDenied(4321)

    assert _sampler_over(root, monkeypatch).sample() is None
    monkeypatch.setattr(process.psutil, "Process", MagicMock(side_effect=psutil.NoSuchProcess(1)))
    assert ProcessSampler.for_pid(1234) is None
