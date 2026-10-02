"""An engine process from outside: start it, wait for its CDP endpoint, measure it, stop it.

Nothing here knows which engine it runs. The host's Obscura and Chromium and
the crawl Obscura are each launched, found, measured and stopped this one way,
along with every child they start.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from operator import methodcaller

# spawns the engine via create_subprocess_exec with a fixed argv from settings,
# never a shell; the import is an intended, confirmed use.
import subprocess  # nosec B404

import psutil

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

BYTES_PER_MB = 1024 * 1024
# Budget for an engine to publish its DevTools endpoint after launch.
_CDP_READY_TIMEOUT_SECONDS = 30.0
# Neither engine announces readiness, so where it publishes is asked until it answers.
_CDP_READY_POLL_SECONDS = 0.2
# How long a stopped engine gets to exit before it is killed.
_STOP_GRACE_SECONDS = 5.0


class EngineLaunchError(RuntimeError):
    """Raised when an engine process exits or never publishes its CDP endpoint."""


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


def _tree(root: psutil.Process) -> list[psutil.Process]:
    return [root, *root.children(recursive=True)]


def _rss_bytes(proc: psutil.Process) -> int:
    """Return a process's resident memory; 0 for a child that exited mid-walk (renderers come and go)."""
    try:
        rss: int = proc.memory_info().rss
    except psutil.NoSuchProcess:
        return 0
    return rss


def process_tree_rss_mb(pid: int) -> float | None:
    """Resident memory of a process and all its children, or None when it cannot be read."""
    try:
        return sum(_rss_bytes(proc) for proc in _tree(psutil.Process(pid))) / BYTES_PER_MB
    except psutil.Error:
        return None


class ProcessSampler:
    """Samples an engine process tree's RSS and CPU%.

    cpu_percent() is used in its non-blocking form: the first call on a
    process seeds the counter and reports 0.0, every later call reports the
    average since the previous one. A sample is a couple of syscalls with no
    sleep, which is what lets the host sample on events.
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._root = psutil.Process(pid)
        self._root.cpu_percent()

    @classmethod
    def for_pid(cls, pid: int) -> ProcessSampler | None:
        """Return a sampler for pid, or None: losing metrics must not fail a launch."""
        try:
            return cls(pid)
        # TypeError covers a pid that is not a usable process id at all; psutil
        # rejects it before it ever raises one of its own errors.
        except (psutil.Error, OSError, TypeError) as exc:
            log.warning(
                f"{LogTag.BROWSER} browser host resource sampler unavailable",
                error_type=type(exc).__name__,
                browser={"pid": pid},
            )
            return None

    def sample(self) -> tuple[float, float] | None:
        """(rss_mb, cpu_percent) for the tree, or None when it cannot be read: the metric goes missing, not the session."""
        try:
            procs = _tree(self._root)
            cpu = 0.0
            for proc in procs:
                with contextlib.suppress(psutil.NoSuchProcess):
                    cpu += proc.cpu_percent()
            return sum(_rss_bytes(proc) for proc in procs) / BYTES_PER_MB, cpu
        except (psutil.Error, OSError) as exc:
            log.warning(
                f"{LogTag.BROWSER} browser host resource sample failed",
                error_type=type(exc).__name__,
                browser={"pid": self._pid},
            )
            return None


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
    """Terminate whatever of procs is still running, then kill what outlives the grace period."""
    alive = procs
    for stop in (methodcaller("terminate"), methodcaller("kill")):
        for proc in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                stop(proc)
        _, alive = psutil.wait_procs(alive, timeout=_STOP_GRACE_SECONDS)
