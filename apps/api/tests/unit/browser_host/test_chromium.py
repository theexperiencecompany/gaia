"""Regressions in ``ChromiumHost``'s session lifecycle.

Covers four related bugs, all rooted in the same root-CDP connection being a
single shared, unbounded resource:

  * a CDP call with no timeout could hang its caller forever (``cdp_call``),
  * ``create_context`` used to hold the session lock across that CDP I/O, so
    one wedged create blocked every other user's create too,
  * a hung/failed storage dump on dispose left the session (and its capacity
    slot) in the registry forever,
  * ``healthz`` reported healthy on process liveness alone, so a wedged-but-
    alive Chromium never triggered an orchestrator restart.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import chromium
from app.browser_host.chromium import (
    AtCapacityError,
    CDPTimeoutError,
    ChromiumHost,
    HostSession,
    cdp_call,
)
from app.config.settings import settings


class _FakeCDP:
    """A programmable fake for the one method the host actually calls: ``send_raw``.

    ``hang_on``/``hang_call_count`` pre-allocate an ``asyncio.Event`` per
    expected call to a method that then hangs forever — the caller awaits the
    event to know the fake call has started, without any real sleep or a
    racy poll loop. ``fail_on_first_call`` raises once per named method, then
    falls through to ``responses`` on subsequent calls.
    """

    def __init__(
        self,
        *,
        responses: dict[str, dict[str, Any]] | None = None,
        hang_on: str | None = None,
        hang_call_count: int = 0,
        fail_on_first_call: dict[str, Exception] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.hang_on = hang_on
        self.call_started = [asyncio.Event() for _ in range(hang_call_count)]
        self.fail_on_first_call = dict(fail_on_first_call or {})
        self._call_counts: dict[str, int] = {}

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self._call_counts[method] = self._call_counts.get(method, 0) + 1
        if method in self.fail_on_first_call and self._call_counts[method] == 1:
            raise self.fail_on_first_call[method]
        if method == self.hang_on:
            idx = self._call_counts[method] - 1
            if idx < len(self.call_started):
                self.call_started[idx].set()
            await asyncio.Event().wait()  # never resolves
        return self.responses.get(method, {})


def _make_host(cdp: _FakeCDP) -> ChromiumHost:
    """A ``ChromiumHost`` wired to a fake CDP client, no real Chromium involved."""
    host = ChromiumHost()
    host._cdp = cdp
    host._proc = MagicMock(returncode=None)  # chromium_up == True
    return host


async def _cancel(*tasks: asyncio.Task[Any]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


# --- BUG 1: unbounded CDP calls could wedge the host forever ---


@pytest.mark.unit
async def test_cdp_call_raises_cdptimeouterror_instead_of_hanging_forever() -> None:
    """``cdp_use``'s ``send_raw`` awaits its future with no timeout of its own."""
    fake_cdp = _FakeCDP(hang_on="Target.getTargets", hang_call_count=1)

    start = time.monotonic()
    with pytest.raises(CDPTimeoutError):
        await cdp_call(fake_cdp, "Target.getTargets", timeout=0.05)
    elapsed = time.monotonic() - start

    # The whole point of the fix: control comes back promptly, not after
    # Chromium wedges forever.
    assert elapsed < 2.0


# --- BUG 2: create_context held the session lock across CDP I/O ---


@pytest.mark.unit
async def test_create_context_second_call_is_not_blocked_by_a_hung_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged first create must not hold the session lock across its CDP I/O."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 10)
    fake_cdp = _FakeCDP(hang_on="Target.createBrowserContext", hang_call_count=2)
    host = _make_host(fake_cdp)

    task1 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(fake_cdp.call_started[0].wait(), timeout=1.0)

    task2 = asyncio.create_task(host.create_context(None))
    # If create_context still held the lock across CDP I/O, task2 would never
    # even reach its own CDP call — it would sit blocked acquiring the lock
    # behind task1, which never releases it.
    await asyncio.wait_for(fake_cdp.call_started[1].wait(), timeout=1.0)

    await _cancel(task1, task2)


@pytest.mark.unit
async def test_reserve_slot_counts_in_flight_creates_toward_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-flight reservations must count toward BROWSER_HOST_MAX_SESSIONS, not just finished sessions."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 2)
    fake_cdp = _FakeCDP(hang_on="Target.createBrowserContext", hang_call_count=2)
    host = _make_host(fake_cdp)

    task1 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(fake_cdp.call_started[0].wait(), timeout=1.0)
    task2 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(fake_cdp.call_started[1].wait(), timeout=1.0)

    # Neither in-flight create has landed in `_sessions` yet, but both slots
    # are reserved — a third caller must be rejected.
    with pytest.raises(AtCapacityError):
        await host.create_context(None)

    await _cancel(task1, task2)


@pytest.mark.unit
async def test_create_context_failure_releases_its_reserved_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A create that fails its CDP work must give its reserved slot back."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    fake_cdp = _FakeCDP(
        fail_on_first_call={"Target.createBrowserContext": RuntimeError("boom")},
        responses={
            "Target.createBrowserContext": {"browserContextId": "ctx-2"},
            "Target.createTarget": {"targetId": "target-2"},
        },
    )
    host = _make_host(fake_cdp)

    with pytest.raises(RuntimeError, match="boom"):
        await host.create_context(None)

    # If the reservation leaked, this second call — the only slot the host
    # has — would raise AtCapacityError instead of proceeding.
    session = await host.create_context(None)
    assert session.context_id == "ctx-2"


# --- BUG 3: a hung/failed storage dump leaked a capacity slot forever ---


@pytest.mark.unit
async def test_dispose_context_removes_session_when_storage_dump_raises() -> None:
    """The registry slot must free even when the storage_state dump blows up."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)
    session = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0.0,
        last_activity_at=0.0,
    )
    host._sessions["s1"] = session

    with (
        patch.object(
            host, "_dump_storage_state", new=AsyncMock(side_effect=RuntimeError("dump failed"))
        ),
        patch.object(host, "_dispose_context_id", new=AsyncMock()) as mock_dispose,
    ):
        with pytest.raises(RuntimeError, match="dump failed"):
            await host.dispose_context("s1")
        mock_dispose.assert_awaited_once_with("ctx1")

    # A session stuck here forever burns one of only BROWSER_HOST_MAX_SESSIONS
    # slots, with no way for a caller to ever reclaim it.
    assert host.get("s1") is None


# --- BUG 4: /healthz reported healthy for a wedged-but-alive Chromium ---


@pytest.mark.unit
async def test_healthz_reports_unresponsive_when_cdp_probe_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process liveness alone must not be enough to report ``ok``."""
    monkeypatch.setattr(chromium, "_CDP_HEALTH_TIMEOUT_SECONDS", 0.05)
    fake_cdp = _FakeCDP(hang_on="Target.getTargets", hang_call_count=1)
    host = _make_host(fake_cdp)

    result = await host.healthz()

    assert result == {
        "ok": False,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": False,
    }


@pytest.mark.unit
async def test_healthz_reports_responsive_when_cdp_probe_succeeds() -> None:
    fake_cdp = _FakeCDP(responses={"Target.getTargets": {"targetInfos": []}})
    host = _make_host(fake_cdp)

    result = await host.healthz()

    assert result == {
        "ok": True,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": True,
    }


# --- BUG 5: an idle sweep must not reap a session that is still inside its TTL ---


@pytest.mark.unit
async def test_reap_idle_keeps_a_session_sitting_exactly_on_the_ttl_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The TTL is the point at which a session becomes reapable, not before it."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 60)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    host = _make_host(_FakeCDP())
    on_the_line = HostSession(
        session_id="edge",
        context_id="ctx-edge",
        target_id="t1",
        created_at=0.0,
        last_activity_at=940.0,  # idle for exactly the TTL
    )
    just_over = HostSession(
        session_id="over",
        context_id="ctx-over",
        target_id="t2",
        created_at=0.0,
        last_activity_at=939.0,
    )
    host._sessions = {"edge": on_the_line, "over": just_over}

    await host._reap_idle()

    assert set(host._sessions) == {"edge"}


@pytest.mark.unit
async def test_reap_idle_spares_a_session_someone_is_watching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live viewer holds the context open however long the tab sits idle."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 60)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    host = _make_host(_FakeCDP())
    watched = HostSession(
        session_id="watched",
        context_id="ctx-watched",
        target_id="t1",
        created_at=0.0,
        last_activity_at=0.0,
        viewer_count=1,
    )
    host._sessions = {"watched": watched}

    await host._reap_idle()

    assert set(host._sessions) == {"watched"}


# --- BUG 6: a crash-recovered session must be marked dead, not silently forgotten ---


@pytest.mark.unit
async def test_recover_crash_marks_every_session_dead_before_dropping_it() -> None:
    """A caller still holding a session must be able to tell it did not survive."""
    host = _make_host(_FakeCDP())
    session = HostSession(
        session_id="s1",
        context_id="ctx1",
        target_id="t1",
        created_at=0.0,
        last_activity_at=0.0,
    )
    host._sessions = {"s1": session}
    host._proc = MagicMock(returncode=-11)  # the real precondition: engine is down
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()

    await host._recover_crash()

    assert session.dead is True
    assert host._sessions == {}
    assert host.get("s1") is None


# --- fast-respawn supervisor: relaunch on process exit, not on the reaper's sweep ---


class _FakeProc:
    """A stand-in engine process whose exit the test drives explicitly."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.pid = 4242
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def die(self, code: int = -11) -> None:
        self.returncode = code
        self._exited.set()


@pytest.mark.unit
async def test_process_watcher_relaunches_engine_the_instant_it_dies() -> None:
    """A segfault must trigger recovery immediately, not wait for the 15s reaper."""
    host = _make_host(_FakeCDP())
    host._recover_crash = AsyncMock()
    proc = _FakeProc()

    task = asyncio.create_task(host._watch_process(proc))  # type: ignore[arg-type]
    await asyncio.sleep(0)  # let the watcher reach proc.wait()
    proc.die(-11)
    await task

    host._recover_crash.assert_awaited_once()


@pytest.mark.unit
async def test_process_watcher_treats_deliberate_stop_as_shutdown_not_crash() -> None:
    """A process that exits because ``stop()`` terminated it must not be relaunched."""
    host = _make_host(_FakeCDP())
    host._recover_crash = AsyncMock()
    host._stopping = True
    proc = _FakeProc()

    task = asyncio.create_task(host._watch_process(proc))  # type: ignore[arg-type]
    proc.die(0)
    await task

    host._recover_crash.assert_not_awaited()


@pytest.mark.unit
async def test_recover_crash_noops_when_engine_already_back_up() -> None:
    """The reaper and the watcher both route to recovery; the loser must not relaunch a second engine."""
    host = _make_host(_FakeCDP())  # _make_host leaves the proc alive (chromium_up)
    host._launch = AsyncMock()
    host._shutdown_chromium = AsyncMock()
    session = HostSession(
        session_id="s1", context_id="c1", target_id="t1", created_at=0.0, last_activity_at=0.0
    )
    host._sessions = {"s1": session}

    await host._recover_crash()

    host._launch.assert_not_awaited()
    assert session.dead is False
    assert host._sessions == {"s1": session}
