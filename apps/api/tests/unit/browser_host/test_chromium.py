"""Regressions in ChromiumHost's session lifecycle.

Covers bugs rooted in how the host talks to the engine:

  * a CDP call with no timeout could hang its caller forever (cdp_call),
  * create_context used to hold the session lock across that CDP I/O, so
    one wedged create blocked every other user's create too,
  * a hung/failed storage dump on dispose left the session (and its capacity
    slot) in the registry forever,
  * healthz reported healthy on process liveness alone, so a wedged-but-
    alive Chromium never triggered an orchestrator restart,
  * every session's work rode one shared connection, which on Obscura (where
    contexts never cross connections, and their ids collide) meant every task
    died with "Browser context not found".
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import chromium
from app.browser_host.chromium import (
    AtCapacityError,
    CDPTimeoutError,
    ChromiumHost,
    cdp_call,
)
from app.config.settings import settings
from tests.unit.browser_host.conftest import FakeMux, install_mux, make_host, make_session


async def _cancel(*tasks: asyncio.Task[Any]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


# --- BUG 1: unbounded CDP calls could wedge the host forever ---


@pytest.mark.unit
async def test_cdp_call_raises_cdptimeouterror_instead_of_hanging_forever() -> None:
    """CdpMux.send_raw awaits its future with no timeout of its own."""
    transport = FakeMux(hang_on="Target.getTargets", hang_call_count=1)

    # The whole point of the fix: control comes back, instead of parking on a
    # future the wedged engine will never resolve.
    with pytest.raises(CDPTimeoutError):
        await cdp_call(transport, "Target.getTargets", timeout=0.05)


# --- BUG 2: create_context held the session lock across CDP I/O ---


@pytest.mark.unit
async def test_create_context_second_call_is_not_blocked_by_a_hung_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged first create must not hold the session lock across its CDP I/O."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 10)
    mux = install_mux(
        monkeypatch, FakeMux(hang_on="Target.createBrowserContext", hang_call_count=2)
    )
    host = make_host()

    task1 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(mux.call_started[0].wait(), timeout=1.0)

    task2 = asyncio.create_task(host.create_context(None))
    # If create_context still held the lock across CDP I/O, task2 would never
    # even reach its own CDP call — it would sit blocked acquiring the lock
    # behind task1, which never releases it.
    await asyncio.wait_for(mux.call_started[1].wait(), timeout=1.0)

    await _cancel(task1, task2)


@pytest.mark.unit
async def test_reserve_slot_counts_in_flight_creates_toward_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-flight reservations must count toward BROWSER_HOST_MAX_SESSIONS, not just finished sessions."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 2)
    mux = install_mux(
        monkeypatch, FakeMux(hang_on="Target.createBrowserContext", hang_call_count=2)
    )
    host = make_host()

    task1 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(mux.call_started[0].wait(), timeout=1.0)
    task2 = asyncio.create_task(host.create_context(None))
    await asyncio.wait_for(mux.call_started[1].wait(), timeout=1.0)

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
    install_mux(
        monkeypatch,
        FakeMux(
            {"Target.createBrowserContext": {"browserContextId": "ctx-2"}},
            fail_on_first_call={"Target.createBrowserContext": RuntimeError("boom")},
        ),
    )
    host = make_host()

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
    host = make_host()
    session = make_session(mux=FakeMux())
    host._sessions["s1"] = session

    with patch.object(
        host, "_dump_storage_state", new=AsyncMock(side_effect=RuntimeError("dump failed"))
    ):
        with pytest.raises(RuntimeError, match="dump failed"):
            await host.dispose_context("s1")

    # The context is disposed over the session's own connection, and the
    # connection itself is closed — otherwise the socket outlives the session.
    assert ("Target.disposeBrowserContext", {"browserContextId": "ctx1"}, None) in session.mux.calls
    assert session.mux.closed is True
    # A session stuck here forever burns one of only BROWSER_HOST_MAX_SESSIONS
    # slots, with no way for a caller to ever reclaim it.
    assert host.get("s1") is None


# --- BUG 4: /healthz reported healthy for a wedged-but-alive Chromium ---


@pytest.mark.unit
async def test_healthz_reports_unresponsive_when_cdp_probe_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process liveness alone must not be enough to report ok."""
    monkeypatch.setattr(chromium, "_CDP_HEALTH_TIMEOUT_SECONDS", 0.05)
    host = make_host()
    host._root_mux = FakeMux(hang_on="Target.getTargets", hang_call_count=1)

    result = await host.healthz()

    assert result == {
        "ok": False,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": False,
    }


@pytest.mark.unit
async def test_healthz_reports_responsive_when_cdp_probe_succeeds() -> None:
    host = make_host()
    host._root_mux = FakeMux({"Target.getTargets": {"targetInfos": []}})

    result = await host.healthz()

    assert result == {
        "ok": True,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": True,
    }


@pytest.mark.unit
async def test_healthz_probes_the_root_connection_not_any_session_connection() -> None:
    """A health probe asks whether the engine answers at all, so it stays on the root socket."""
    host = make_host()
    root = FakeMux({"Target.getTargets": {"targetInfos": []}})
    host._root_mux = root
    session = make_session(mux=FakeMux())
    host._sessions["s1"] = session

    result = await host.healthz()

    assert result["cdp_responsive"] is True
    assert root.methods == ["Target.getTargets"]
    assert session.mux.calls == []


@pytest.mark.unit
async def test_create_context_on_a_host_that_never_started_says_so_and_frees_its_slot() -> None:
    """The rollback must not close a connection that was never opened, or it buries the real error."""
    host = ChromiumHost()  # no root websocket url: the engine was never launched

    with pytest.raises(RuntimeError, match="browser host is not started"):
        await host.create_context(None)

    assert host._pending_slots == 0


@pytest.mark.unit
async def test_healthz_does_not_probe_a_dead_engine_even_with_a_connection_object() -> None:
    """A dead process cannot answer, so the probe is skipped rather than left to time out."""
    host = make_host()
    host._proc = MagicMock(returncode=0)  # chromium_up is False
    root = FakeMux({"Target.getTargets": {"targetInfos": []}})
    host._root_mux = root

    result = await host.healthz()

    assert result["cdp_responsive"] is False
    assert root.calls == []


@pytest.mark.unit
async def test_healthz_reports_a_missing_root_connection_without_calling_it_an_error() -> None:
    """No connection yet is a state, not a failure, so nothing is dialled and nothing is logged."""
    host = make_host()
    host._root_mux = None

    with patch.object(chromium, "log") as mock_log:
        result = await host.healthz()

    assert result["cdp_responsive"] is False
    assert result["chromium_up"] is True
    mock_log.error.assert_not_called()


# --- BUG 5: an idle sweep must not reap a session that is still inside its TTL ---


@pytest.mark.unit
async def test_reap_idle_keeps_a_session_sitting_exactly_on_the_ttl_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The TTL is the point at which a session becomes reapable, not before it."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 60)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    host = make_host()
    on_the_line = make_session(
        session_id="edge",
        context_id="ctx-edge",
        last_activity_at=940.0,  # idle for exactly the TTL
    )
    just_over = make_session(
        session_id="over",
        context_id="ctx-over",
        target_id="t2",
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
    host = make_host()
    watched = replace(make_session(session_id="watched", context_id="ctx-watched"), viewer_count=1)
    host._sessions = {"watched": watched}

    await host._reap_idle()

    assert set(host._sessions) == {"watched"}
    assert watched.mux.closed is False


# --- BUG 6: a crash-recovered session must be marked dead, not silently forgotten ---


@pytest.mark.unit
async def test_recover_crash_marks_every_session_dead_before_dropping_it() -> None:
    """A caller still holding a session must be able to tell it did not survive."""
    host = make_host()
    session = make_session()
    host._sessions = {"s1": session}
    host._proc = MagicMock(returncode=-11)  # the real precondition: engine is down
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()

    await host._recover_crash()

    assert session.dead is True
    assert host._sessions == {}
    assert host.get("s1") is None


# --- BUG 7: one shared connection per host, on an engine that isolates connections ---


@pytest.mark.unit
async def test_create_context_opens_and_starts_exactly_one_connection(
    monkeypatch: pytest.MonkeyPatch, mux: FakeMux
) -> None:
    """A session IS its connection: one socket, dialed at the engine's root url, and started."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    host = make_host()

    session = await host.create_context(None)

    assert session.mux is mux
    assert mux.urls == [host.root_ws_url]
    assert mux.started == 1
    assert mux.closed is False


@pytest.mark.unit
async def test_create_context_closes_the_connection_when_its_cdp_work_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection opened before the failure has no session to carry it — it must not leak."""
    monkeypatch.setattr(settings, "BROWSER_HOST_MAX_SESSIONS", 5)
    mux = install_mux(
        monkeypatch,
        FakeMux(fail_on_first_call={"Target.createTarget": RuntimeError("no target")}),
    )
    host = make_host()

    with pytest.raises(RuntimeError, match="no target"):
        await host.create_context(None)

    assert mux.started == 1
    assert mux.closed is True
    assert host._sessions == {}


@pytest.mark.unit
async def test_dispose_context_closes_the_sessions_connection() -> None:
    """Closing the socket is what frees the session on a per-connection engine."""
    host = make_host()
    session = make_session(context_id="ctx-bye")
    host._sessions["s1"] = session

    await host.dispose_context("s1")

    assert (
        "Target.disposeBrowserContext",
        {"browserContextId": "ctx-bye"},
        None,
    ) in session.mux.calls
    assert session.mux.closed is True


@pytest.mark.unit
async def test_reap_idle_closes_the_connection_of_every_session_it_reaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reaped session whose socket stays open leaks a connection the host can never find again."""
    monkeypatch.setattr(settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    monkeypatch.setattr(chromium, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    host = make_host()
    first = make_session(session_id="a", context_id="ctx-a", last_activity_at=0.0)
    second = make_session(session_id="b", context_id="ctx-b", last_activity_at=0.0)
    host._sessions = {"a": first, "b": second}

    await host._reap_idle()

    assert host._sessions == {}
    assert [first.mux.closed, second.mux.closed] == [True, True]
    assert first.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx-a"}]
    assert second.mux.params_for("Target.disposeBrowserContext") == [{"browserContextId": "ctx-b"}]


@pytest.mark.unit
async def test_recover_crash_closes_the_connection_of_every_dead_session() -> None:
    """The engine is gone, so every session socket is broken — close them or their waiters hang."""
    host = make_host()
    first = make_session(session_id="s1")
    second = make_session(session_id="s2", context_id="ctx2")
    host._sessions = {"s1": first, "s2": second}
    host._proc = MagicMock(returncode=-11)
    host._shutdown_chromium = AsyncMock()
    host._launch = AsyncMock()

    await host._recover_crash()

    assert [first.mux.closed, second.mux.closed] == [True, True]
    # The engine is down, so no dispose is attempted over a dead socket.
    assert first.mux.calls == [] and second.mux.calls == []


@pytest.mark.unit
async def test_focused_target_id_asks_the_sessions_own_connection() -> None:
    """Obscura isolates every connection, so asking the root connection returns another world's targets."""
    host = make_host()
    root = FakeMux(
        {"Target.getTargets": {"targetInfos": [{"type": "page", "targetId": "wrong-world"}]}}
    )
    host._root_mux = root
    session = make_session(
        target_id="t-primary",
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-primary"},
                        {"type": "page", "browserContextId": "ctx1", "targetId": "t-second"},
                    ]
                }
            }
        ),
    )
    host._sessions["s1"] = session

    assert await host.focused_target_id("s1") == "t-primary"
    assert session.mux.methods == ["Target.getTargets"]
    assert root.calls == []


@pytest.mark.unit
async def test_dump_origins_asks_the_sessions_own_connection() -> None:
    """The pages a session can see live on its connection, never on the host's root connection."""
    host = make_host()
    root = FakeMux({"Target.getTargets": {"targetInfos": []}})
    host._root_mux = root
    session = make_session(
        mux=FakeMux(
            {
                "Target.getTargets": {
                    "targetInfos": [{"targetId": "t1", "type": "page", "browserContextId": "ctx1"}]
                },
                "Target.attachToTarget": {"sessionId": "sess-1"},
                "Runtime.evaluate": {
                    "result": {
                        "value": {
                            "origin": "https://a.test",
                            "localStorage": [{"name": "k", "value": "v"}],
                        }
                    }
                },
            }
        )
    )

    origins = await host._dump_origins(session)

    assert origins == [{"origin": "https://a.test", "localStorage": [{"name": "k", "value": "v"}]}]
    assert root.calls == []


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
    host = ChromiumHost()
    proc = _FakeProc()
    host._proc = proc  # type: ignore[assignment]  # assigns a _FakeProc stub to the typed asyncio Process attribute

    async def recover() -> None:
        host._stopping.set()  # one recovery, then the loop exits

    host._recover_crash = AsyncMock(side_effect=recover)

    task = asyncio.create_task(host._watch_loop())
    await asyncio.sleep(0)  # let the watcher reach proc.wait()
    proc.die(-11)
    await task

    host._recover_crash.assert_awaited_once()


@pytest.mark.unit
async def test_process_watcher_treats_deliberate_stop_as_shutdown_not_crash() -> None:
    """A process that exits because stop() terminated it must not be relaunched."""
    host = ChromiumHost()
    host._recover_crash = AsyncMock()
    proc = _FakeProc()
    host._proc = proc  # type: ignore[assignment]  # assigns a _FakeProc stub to the typed asyncio Process attribute

    task = asyncio.create_task(host._watch_loop())
    await asyncio.sleep(0)  # park the watcher on proc.wait()
    host._stopping.set()  # stop() flips this, then terminates the process
    proc.die(0)
    await task

    host._recover_crash.assert_not_awaited()


@pytest.mark.unit
async def test_recover_crash_noops_when_engine_already_back_up() -> None:
    """The reaper and the watcher both route to recovery; the loser must not relaunch a second engine."""
    host = make_host()  # make_host leaves the proc alive (chromium_up)
    host._launch = AsyncMock()
    host._shutdown_chromium = AsyncMock()
    session = make_session(context_id="c1")
    host._sessions = {"s1": session}

    await host._recover_crash()

    host._launch.assert_not_awaited()
    assert session.dead is False
    assert session.mux.closed is False
    assert host._sessions == {"s1": session}
