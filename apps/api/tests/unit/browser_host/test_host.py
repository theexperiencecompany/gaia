"""The browser host's session registry, leases, admission and engine supervision.

Sessions run against FakeEngine (contexts, pages, cookies and storage are real
state) and engines are StubEngines, so these assert what the host ends up
holding and doing, never which frames it sent in which order.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from playwright.sync_api import StorageState
import pytest

from app.browser_host import host as host_mod
from app.browser_host.cdp_mux import CdpCommandError
from app.browser_host.host import (
    AtCapacityError,
    BrowserHost,
    EngineUnresponsiveError,
    SessionNotFoundError,
)
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import BrowserEngine, EngineExit, HostAdmissionRefusal
from tests.unit.browser_host.conftest import (
    FAKE_ROOT_WS_URL,
    FakeEngine,
    FakeMux,
    StubEngine,
    as_engine,
    install_launcher,
    install_mux,
    make_host,
)

_ORIGIN = "https://app.example.com"
_LOGIN: StorageState = {
    "cookies": [
        {
            "name": "sid",
            "value": "secret",
            "domain": ".example.com",
            "path": "/",
            "expires": 1_900_000_000,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }
    ],
    "origins": [{"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "t-1"}]}],
}


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    return cast(FakeEngine, install_mux(monkeypatch, FakeEngine()))


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


# --- a session: its context, its seeded login, its dump ---


@pytest.mark.unit
async def test_a_new_session_is_its_own_context_with_one_page_the_host_holds(
    engine: FakeEngine,
) -> None:
    host = make_host()

    session = await host.create_context(None)

    context = engine.contexts[session.context_id]
    assert context["download"] == "deny"
    assert [t for t, p in engine.pages.items() if p["context"] == session.context_id] == [
        session.target_id
    ]
    assert engine.sessions[session.page_session] == session.target_id
    assert ("Page.enable", None, session.page_session) in engine.calls
    assert host.get(session.session_id) is session
    assert session.token
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_a_saved_login_is_seeded_into_its_context_and_its_page(engine: FakeEngine) -> None:
    host = make_host()

    session = await host.create_context(_LOGIN)

    assert engine.contexts[session.context_id]["cookies"][0]["value"] == "secret"
    assert engine.contexts[""]["cookies"] == []
    scripts = engine.pages[session.target_id]["scripts"]
    assert len(scripts) == 1
    assert _ORIGIN in scripts[0]
    assert "t-1" in scripts[0]


@pytest.mark.unit
async def test_a_login_survives_the_round_trip_through_a_session(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(_LOGIN)
    page = engine.pages[session.target_id]
    page["url"], page["storage"] = f"{_ORIGIN}/home", {"token": "t-2"}
    samples = session.metrics.rss_mb.count

    state = await host.dispose_context(session.session_id)

    assert session.metrics.rss_mb.count == samples + 1
    cookie = state["cookies"][0]
    assert (cookie["name"], cookie["value"], cookie["domain"]) == ("sid", "secret", ".example.com")
    assert cookie.get("sameSite") == "Lax"
    assert state["origins"] == [
        {"origin": _ORIGIN, "localStorage": [{"name": "token", "value": "t-2"}]}
    ]
    assert session.context_id not in engine.contexts
    assert engine.close_count == 1
    assert host.get(session.session_id) is None


@pytest.mark.unit
async def test_the_dump_reports_a_cleared_store_but_no_opaque_origin(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    engine.pages[session.target_id]["url"] = f"{_ORIGIN}/signed-out"
    engine.open_page(session.context_id, url="about:blank")
    engine.open_page("someone-else", url="https://other.example/", storage={"k": "v"})

    state = await host.storage_state(session.session_id)

    assert state["origins"] == [{"origin": _ORIGIN, "localStorage": []}]
    assert host.get(session.session_id) is session


@pytest.mark.unit
async def test_a_page_that_cannot_be_read_is_left_out_not_the_dump(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    engine.pages[session.target_id].update(url=f"{_ORIGIN}/", storage={"a": "1"})
    broken = engine.open_page(session.context_id, url="https://broken.example/", storage={"b": "2"})
    engine.unreadable.add(broken)

    state = await host.storage_state(session.session_id)

    assert state["origins"] == [{"origin": _ORIGIN, "localStorage": [{"name": "a", "value": "1"}]}]
    assert engine.detached and all(s != session.page_session for s in engine.detached)
    assert session.page_session in engine.sessions


@pytest.mark.unit
async def test_a_dump_that_fails_still_ends_the_session(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    engine.hang_on = "Storage.getCookies"
    engine.send_error = None

    async def _dump_then_fail() -> None:
        await engine.hang_started.wait()
        engine.hang_on = None
        engine.send_error = CdpCommandError({"message": "gone"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.gather(
            asyncio.wait_for(host.dispose_context(session.session_id), 0.05), _dump_then_fail()
        )
    await _settle()

    assert host.get(session.session_id) is None
    assert engine.close_count == 1


@pytest.mark.unit
async def test_a_session_on_a_down_engine_refuses_its_dump(engine: FakeEngine) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    stub.is_alive = False

    with pytest.raises(EngineUnresponsiveError):
        await host.storage_state(session.session_id)
    with pytest.raises(EngineUnresponsiveError):
        await host.dispose_context(session.session_id)
    assert host.get(session.session_id) is None
    assert "Target.disposeBrowserContext" not in engine.methods


@pytest.mark.unit
async def test_an_unknown_session_is_not_found_everywhere() -> None:
    host = make_host()
    with pytest.raises(SessionNotFoundError):
        await host.dispose_context("ghost")
    with pytest.raises(SessionNotFoundError):
        await host.storage_state("ghost")
    with pytest.raises(SessionNotFoundError):
        await host.session_info("ghost")
    with pytest.raises(SessionNotFoundError):
        host.renew_lease("ghost")


# --- how a session ends: lease, connection, create failure ---


@pytest.mark.unit
async def test_a_session_whose_lease_is_not_renewed_is_disposed(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_mod, "BROWSER_SESSION_LEASE_SECONDS", 0.02)
    host = make_host()
    session = await host.create_context(None)

    await asyncio.wait_for(engine.wait_closed(), 1.0)
    await _settle()

    assert host.get(session.session_id) is None
    assert session.context_id not in engine.contexts


@pytest.mark.unit
async def test_a_renewed_lease_replaces_the_one_it_renews(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    first = cast(asyncio.TimerHandle, session.lease)

    host.renew_lease(session.session_id)

    renewed = cast(asyncio.TimerHandle, session.lease)
    assert first.cancelled()
    assert not renewed.cancelled()
    assert renewed.when() >= first.when()
    assert renewed.when() - asyncio.get_running_loop().time() == pytest.approx(
        host_mod.BROWSER_SESSION_LEASE_SECONDS, abs=1.0
    )


@pytest.mark.unit
async def test_a_disposed_session_holds_no_lease_to_run_out(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    lease = cast(asyncio.TimerHandle, session.lease)

    await host.dispose_context(session.session_id)

    assert lease.cancelled()
    assert session.lease is None
    assert engine.methods.count("Target.disposeBrowserContext") == 1


@pytest.mark.unit
async def test_a_session_whose_connection_drops_is_gone(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)

    await engine.close()
    await _settle()

    assert host.get(session.session_id) is None
    assert session.lease is None


@pytest.mark.unit
async def test_a_failed_create_frees_its_slot_and_its_connection(engine: FakeEngine) -> None:
    host = make_host()
    engine.send_error = CdpCommandError({"message": "boom"})

    with pytest.raises(CdpCommandError):
        await host.create_context(None)

    assert host._pending_slots == 0
    assert host._sessions == {}
    assert engine.close_count == 1


@pytest.mark.unit
async def test_a_create_with_no_engine_serving_says_so_and_frees_its_slot() -> None:
    host = BrowserHost(on_fatal=MagicMock())

    with pytest.raises(EngineUnresponsiveError):
        await host.create_context(None)
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_a_create_refused_by_a_dead_engine_leaves_it_counted_idle() -> None:
    stub = StubEngine()
    stub.is_alive = False
    host = make_host(stub)

    with pytest.raises(EngineUnresponsiveError):
        await host.create_context(None)
    assert host._creating[as_engine(stub)] == 0


# --- admission ---


def _memory(monkeypatch: pytest.MonkeyPatch, used: float, limit: float) -> None:
    monkeypatch.setattr(host_mod, "memory_usage_mb", lambda: (used, limit))


@pytest.mark.unit
async def test_a_create_is_admitted_up_to_the_watermark_exactly(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.5)
    _memory(monkeypatch, 450.0, 1000.0)
    host = make_host()

    await host.create_context(None)
    with pytest.raises(AtCapacityError) as refused:
        await host.create_context(None)

    assert refused.value.gate is HostAdmissionRefusal.MEMORY
    assert str(refused.value) == "at capacity (memory)"
    assert (refused.value.used_mb, refused.value.limit_mb) == (450.0, 1000.0)
    assert refused.value.sessions == 1
    assert refused.value.pending == 0
    assert refused.value.projected_mb > 500.0


@pytest.mark.unit
async def test_the_session_ceiling_is_a_backstop_that_zero_turns_off(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    host = make_host()
    await host.create_context(None)
    with pytest.raises(AtCapacityError) as refused:
        await host.create_context(None)
    assert refused.value.gate is HostAdmissionRefusal.SESSION_CEILING

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 0)
    await host.create_context(None)
    assert len(host._sessions) == 2


@pytest.mark.unit
async def test_a_refused_create_waits_for_a_session_to_end_before_its_429(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    monkeypatch.setattr(host_mod, "_ADMISSION_WAIT_SECONDS", 5.0)
    host = make_host()
    first = await host.create_context(None)

    waiting = asyncio.create_task(host.create_context(None))
    await _settle()
    assert not waiting.done()
    await host.dispose_context(first.session_id)
    second = await asyncio.wait_for(waiting, 1.0)

    assert host.get(second.session_id) is second


@pytest.mark.unit
async def test_every_create_in_flight_reserves_its_cost(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 1.0)
    _memory(monkeypatch, 0.0, 90.0)
    host = make_host()
    engine.hang_on = "Target.createBrowserContext"
    first = asyncio.create_task(host.create_context(None))
    await engine.hang_started.wait()

    with pytest.raises(AtCapacityError) as refused:
        await host.create_context(None)

    assert refused.value.pending == 1
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_the_next_sessions_cost_is_the_serving_engines_measured_average_floored(
    engine: FakeEngine,
) -> None:
    stub = StubEngine(rss_mb=500.0)
    stub.base_rss_mb = 100.0
    host = make_host(stub)
    assert host._estimate_session_cost_mb() == host_mod._SESSION_COST_FLOOR_MB

    await host.create_context(None)
    await host.create_context(None)
    assert host._estimate_session_cost_mb() == 200.0

    stub.current_rss_mb = 110.0
    assert host._estimate_session_cost_mb() == host_mod._SESSION_COST_FLOOR_MB
    stub.current_rss_mb = None
    assert host._estimate_session_cost_mb() == host_mod._SESSION_COST_FLOOR_MB
    host._engine = None
    assert host._estimate_session_cost_mb() == host_mod._SESSION_COST_FLOOR_MB


# --- engines: supervision, failure, recycling ---


@pytest.mark.unit
async def test_start_launches_the_configured_engine_and_watches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    monkeypatch.setattr(host_mod, "resolve_chromium_path", lambda: "/opt/chrome")
    stub = StubEngine()
    install_launcher(monkeypatch, stub)
    host = BrowserHost(on_fatal=MagicMock())

    await host.start()

    assert host._chromium_path == "/opt/chrome"
    assert host.engine_up
    assert as_engine(stub) in host._supervisors
    await host.stop()
    assert stub.shutdowns == [True]
    assert not host.engine_up


@pytest.mark.unit
async def test_an_obscura_host_never_resolves_a_chromium_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    resolve = MagicMock()
    monkeypatch.setattr(host_mod, "resolve_chromium_path", resolve)
    install_launcher(monkeypatch, StubEngine())
    host = BrowserHost(on_fatal=MagicMock())

    await host.start()

    resolve.assert_not_called()
    await host.stop()


@pytest.mark.unit
async def test_a_failed_engine_takes_its_sessions_with_it_and_is_replaced(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = StubEngine(), StubEngine()
    install_launcher(monkeypatch, first, second)
    on_fatal = MagicMock()
    host = BrowserHost(on_fatal=on_fatal)
    await host.start()
    session = await host.create_context(None)

    first.fail(EngineExit.STOPPED_ANSWERING)
    for _ in range(20):
        await asyncio.sleep(0)
        if host._engine is as_engine(second):
            break

    assert host.get(session.session_id) is None
    assert engine.closed
    assert first.shutdowns == [False]
    assert host._engine is as_engine(second)
    on_fatal.assert_not_called()
    await host.stop()


@pytest.mark.unit
async def test_a_host_that_cannot_relaunch_its_engine_gives_up_for_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = StubEngine()
    launched = install_launcher(monkeypatch, first)
    on_fatal = MagicMock()
    host = BrowserHost(on_fatal=on_fatal)
    await host.start()
    assert launched == [first]

    first.fail()
    for _ in range(20):
        await asyncio.sleep(0)
        if on_fatal.called:
            break

    on_fatal.assert_called_once_with()
    assert host.failed
    assert not host.engine_up


@pytest.mark.unit
async def test_a_stopping_host_does_not_relaunch_a_failed_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = StubEngine()
    install_launcher(monkeypatch, first, StubEngine())
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()
    host._stopping.set()

    await host._engine_lost(as_engine(first))

    assert host._engine is as_engine(first)


async def _session_on(host: BrowserHost, monkeypatch: pytest.MonkeyPatch) -> str:
    install_mux(monkeypatch, FakeEngine())
    return (await host.create_context(None)).session_id


@pytest.mark.unit
async def test_an_engine_over_its_limit_drains_while_a_fresh_one_takes_new_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", 1000)
    old, fresh = StubEngine(rss_mb=900.0), StubEngine(rss_mb=100.0)
    install_launcher(monkeypatch, old, fresh)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()
    leaving = await _session_on(host, monkeypatch)
    staying = await _session_on(host, monkeypatch)

    old.current_rss_mb = 1200.0
    await host.dispose_context(leaving)

    assert host._engine is as_engine(fresh)
    assert as_engine(old) in host._retiring
    assert old.shutdowns == []
    newcomer = await _session_on(host, monkeypatch)
    assert host._sessions[newcomer].engine is as_engine(fresh)

    await host.dispose_context(staying)
    assert old.shutdowns == [True]
    assert host._retiring == set()
    await host.stop()


@pytest.mark.unit
async def test_an_idle_engine_over_its_limit_is_replaced_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", 1000)
    old, fresh = StubEngine(rss_mb=1200.0), StubEngine()
    install_launcher(monkeypatch, old, fresh)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()

    await host.dispose_context(await _session_on(host, monkeypatch))

    assert host._engine is as_engine(fresh)
    assert old.shutdowns == [True]
    assert host._retiring == set()
    await host.stop()


@pytest.mark.parametrize(("limit", "rss"), [(1000, 1000.0), (None, 5000.0), (1000, None)])
@pytest.mark.unit
async def test_an_engine_within_its_limit_or_unmeasured_keeps_serving(
    monkeypatch: pytest.MonkeyPatch, limit: int | None, rss: float | None
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", limit)
    stub = StubEngine()
    stub.current_rss_mb = rss
    launched = install_launcher(monkeypatch, stub, StubEngine())
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()

    await host.dispose_context(await _session_on(host, monkeypatch))

    assert launched == [stub]
    await host.stop()


@pytest.mark.unit
async def test_a_replacement_that_fails_to_launch_leaves_the_old_engine_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", 1000)
    old = StubEngine(rss_mb=2000.0)
    install_launcher(monkeypatch, old)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()

    await host.dispose_context(await _session_on(host, monkeypatch))

    assert host._engine is as_engine(old)
    assert old.shutdowns == []
    await host.stop()


# --- what the host reports ---


@pytest.mark.unit
async def test_session_info_reads_the_focused_page_and_answers_on_the_root(
    engine: FakeEngine,
) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    second = engine.open_page(session.context_id, url="https://second.example/")
    host.note_focus(session.session_id, second)

    info = await host.session_info(session.session_id)

    assert info["live"] is True
    assert info["url"] == "https://second.example/"
    stub.answers = False
    with pytest.raises(EngineUnresponsiveError):
        await host.session_info(session.session_id)


@pytest.mark.unit
async def test_session_info_on_a_closed_focused_tab_has_no_page(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    host.note_focus(session.session_id, "closed-tab")

    info = await host.session_info(session.session_id)

    assert (info["url"], info["title"]) == (None, None)


@pytest.mark.unit
async def test_the_streamed_page_is_the_focused_then_the_sessions_own_then_the_newest(
    engine: FakeEngine,
) -> None:
    host = make_host()
    session = await host.create_context(None)
    newest = engine.open_page(session.context_id, url="https://n.example/")

    assert await host.focused_target_id(session) == session.target_id
    host.note_focus(session.session_id, newest)
    assert await host.focused_target_id(session) == newest
    host.note_focus(session.session_id, "closed")
    assert await host.focused_target_id(session) == session.target_id
    del engine.pages[session.target_id]
    assert await host.focused_target_id(session) == newest
    del engine.pages[newest]
    assert await host.focused_target_id(session) is None


@pytest.mark.unit
async def test_a_focus_move_wakes_whoever_watches_once(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    watched = session.focus_moved

    host.note_focus(session.session_id, session.target_id)
    assert not watched.is_set()
    host.note_focus(session.session_id, "other")

    assert watched.is_set()
    assert not session.focus_moved.is_set()
    host.note_focus("ghost", "other")


@pytest.mark.unit
async def test_healthz_is_a_round_trip_on_the_serving_engine() -> None:
    stub = StubEngine()
    host = make_host(stub)
    assert await host.healthz() == {
        "ok": True,
        "sessions": 0,
        "engine_up": True,
        "cdp_responsive": True,
    }
    stub.answers = False
    assert (await host.healthz())["ok"] is False
    host._engine = None
    assert await host.healthz() == {
        "ok": False,
        "sessions": 0,
        "engine_up": False,
        "cdp_responsive": False,
    }


@pytest.mark.unit
async def test_a_navigation_is_timed_and_sampled_only_when_one_was_started(
    engine: FakeEngine,
) -> None:
    host = make_host()
    session = await host.create_context(None)
    samples = session.metrics.rss_mb.count

    host.note_navigation_finished(session.session_id)
    assert session.metrics.navigation_count == 0
    assert session.metrics.rss_mb.count == samples
    host.note_navigation_started(session.session_id)
    host.note_navigation_finished(session.session_id)
    host.note_page_created(session.session_id)

    assert session.metrics.navigation_count == 1
    assert session.metrics.rss_mb.count == samples + 1
    assert session.metrics.page_count == 2
    for hook in (
        host.note_navigation_started,
        host.note_navigation_finished,
        host.note_page_created,
    ):
        hook("ghost")


@pytest.mark.unit
async def test_stop_releases_every_session_timer_and_engine(engine: FakeEngine) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    lease = cast(Any, session.lease)

    await host.stop()

    assert lease.cancelled()
    assert stub.shutdowns == [True]
    assert host._engine is None


@pytest.mark.unit
async def test_a_dispose_logs_the_lost_login_when_the_dump_fails(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host()
    session = await host.create_context(None)
    engine.send_error = CdpCommandError({"message": "gone"})
    error = MagicMock()
    monkeypatch.setattr(host_mod.log, "error", error)

    with pytest.raises(CdpCommandError):
        await host.dispose_context(session.session_id)

    assert error.call_args.kwargs["error_type"] == "StorageDumpFailed"


@pytest.mark.unit
async def test_a_failed_context_dispose_is_warned_about_and_the_connection_still_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = install_mux(
        monkeypatch,
        FakeMux({"Target.attachToTarget": {}, "Target.createTarget": {"targetId": "t"}}),
    )
    host = make_host()
    session = await host.create_context(None)
    mux.send_error = CdpCommandError({"message": "no such context"})
    warning = MagicMock()
    monkeypatch.setattr(host_mod.log, "warning", warning)

    await host._end_session(session, host_mod.HostSessionEnd.DISPOSED)

    assert warning.call_args.kwargs["error_type"] == "CdpCommandError"
    assert mux.closed


@pytest.mark.unit
async def test_an_engine_that_launches_for_the_host_is_supervised_until_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubEngine()
    install_launcher(monkeypatch, stub)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()
    supervisor = host._supervisors[as_engine(stub)]

    await host._stop_engine(as_engine(stub))
    await asyncio.sleep(0)

    assert supervisor.cancelled()
    assert as_engine(stub) not in host._supervisors


@pytest.mark.unit
async def test_resource_sampling_needs_a_session_and_a_sampler(engine: FakeEngine) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    taken = session.metrics.rss_mb.count

    stub.sampler.sample = MagicMock(return_value=None)
    host.sample_resources(session.session_id)
    stub.sampler = None
    host.sample_resources(session.session_id)
    host.sample_resources("ghost")

    assert session.metrics.rss_mb.count == taken


@pytest.mark.unit
async def test_a_create_through_an_attach_the_engine_never_answers_fails_as_unresponsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = install_mux(monkeypatch, FakeMux({"Target.createTarget": {"targetId": "t"}}))
    mux.hang_on = "Target.attachToTarget"
    monkeypatch.setattr(host_mod, "BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS", 0.01)
    host = make_host()

    with pytest.raises(host_mod.CDPTimeoutError):
        await host.create_context(None)
    assert host._pending_slots == 0


@pytest.mark.unit
async def test_the_launch_hands_the_learned_user_agent_to_the_next_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = AsyncMock(return_value=(as_engine(StubEngine()), "Mozilla Chrome/1"))
    monkeypatch.setattr(host_mod, "launch_engine", launch)
    host = BrowserHost(on_fatal=MagicMock())

    await host._launch()
    await host._launch()

    assert launch.await_args_list[1].args[2] == "Mozilla Chrome/1"
    await host.stop()


# --- what the host reports about itself, and the small contracts behind it ---


class _Log:
    """Records the host's log calls, so what an operator reads is pinned by its fields."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((level, args, kwargs))

        return record

    def of(self, level: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for lvl, args, kwargs in self.calls if lvl == level]


@pytest.fixture
def host_log(monkeypatch: pytest.MonkeyPatch) -> _Log:
    recorder = _Log()
    monkeypatch.setattr(host_mod, "log", recorder)
    return recorder


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    names: list[str] = []
    real = host_mod.spawn_logged_task

    def _spawn(operation: str, coro: Any) -> Any:
        names.append(operation)
        return real(operation, coro)

    monkeypatch.setattr(host_mod, "spawn_logged_task", _spawn)
    return names


@pytest.mark.unit
async def test_a_fresh_host_has_not_failed_and_launches_with_nothing_learned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = AsyncMock(return_value=(as_engine(StubEngine()), None))
    monkeypatch.setattr(host_mod, "launch_engine", launch)
    host = BrowserHost(on_fatal=MagicMock())

    await host._launch()

    assert host.failed is False
    assert launch.await_args.args == (browser_host_settings.BROWSER_ENGINE, None, None)
    await host.stop()


@pytest.mark.unit
async def test_a_create_opens_its_context_on_the_serving_engine_and_says_so(
    engine: FakeEngine, host_log: _Log
) -> None:
    host = make_host()

    session = await host.create_context(None)

    assert engine.urls == [FAKE_ROOT_WS_URL]
    assert engine.params_for("Target.createBrowserContext") == [{"disposeOnDetach": True}]
    assert engine.pages[session.target_id]["url"] == "about:blank"
    assert session.metrics.rss_mb.count == 1
    assert len(session.token) >= 43
    assert ({"browser": {"session_id": session.session_id, "operation": "create"}},) in [
        (kwargs,) for args, kwargs in host_log.of("set")
    ]
    engine.emit({"method": "Page.frameNavigated", "sessionId": session.page_session, "params": {}})


@pytest.mark.unit
async def test_a_create_with_no_engine_says_which_way_it_failed() -> None:
    host = BrowserHost(on_fatal=MagicMock())

    with pytest.raises(EngineUnresponsiveError) as refused:
        await host.create_context(None)

    assert refused.value.args == ("no browser engine is serving",)


@pytest.mark.unit
async def test_two_creates_in_flight_keep_their_engine_busy_until_both_are_done(
    engine: FakeEngine,
) -> None:
    stub = StubEngine()
    host = make_host(stub)
    engine.hang_on = "Target.createBrowserContext"
    first = asyncio.create_task(host.create_context(None))
    second = asyncio.create_task(host.create_context(None))
    await _settle()

    first.cancel()
    await asyncio.gather(first, return_exceptions=True)

    assert host._engine_idle(as_engine(stub)) is False
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    assert host._engine_idle(as_engine(stub)) is True


@pytest.mark.unit
async def test_a_session_ending_reports_how_with_its_metrics(
    engine: FakeEngine, host_log: _Log, monkeypatch: pytest.MonkeyPatch, spawned: list[str]
) -> None:
    monkeypatch.setattr(host_mod, "BROWSER_SESSION_LEASE_SECONDS", 0.0)
    host = make_host()
    session = await host.create_context(None)
    await asyncio.wait_for(engine.wait_closed(), 1.0)
    await _settle()

    assert spawned == ["browser_session_lease_expired"]
    assert {"browser": {"session_id": session.session_id, "operation": "lease_expired"}} in [
        kwargs for _, kwargs in host_log.of("set")
    ]
    [(args, kwargs)] = host_log.of("set_ns")
    assert args == ("browser",)
    assert kwargs["metrics"]["page_count"] == 1


@pytest.mark.unit
async def test_a_dispose_is_not_mistaken_for_a_lost_connection(
    engine: FakeEngine, spawned: list[str]
) -> None:
    host = make_host()
    session = await host.create_context(None)

    await host.dispose_context(session.session_id)
    await _settle()

    assert spawned == []


@pytest.mark.unit
async def test_a_dropped_connection_ends_its_session_as_lost(
    engine: FakeEngine, host_log: _Log, spawned: list[str]
) -> None:
    host = make_host()
    session = await host.create_context(None)

    await engine.close()
    await _settle()

    assert spawned == ["browser_session_connection_lost"]
    assert {"browser": {"session_id": session.session_id, "operation": "connection_lost"}} in [
        kwargs for _, kwargs in host_log.of("set")
    ]


@pytest.mark.unit
async def test_a_stopping_host_does_not_treat_its_closing_connections_as_lost(
    engine: FakeEngine, spawned: list[str]
) -> None:
    host = make_host()
    session = await host.create_context(None)
    watch = cast(asyncio.Task[None], session.connection_watch)

    host._stopping.set()
    await engine.close()
    await _settle()

    assert spawned == []
    assert watch.done()


@pytest.mark.unit
async def test_stop_cancels_every_sessions_connection_watch(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    watch = cast(asyncio.Task[None], session.connection_watch)

    await host.stop()
    await _settle()

    assert watch.cancelled()


@pytest.mark.unit
async def test_a_failed_engine_is_reported_with_why_and_how_many_sessions_it_took(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch, host_log: _Log
) -> None:
    first, second = StubEngine(), StubEngine()
    install_launcher(monkeypatch, first, second)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()
    await host.create_context(None)

    first.fail(EngineExit.STOPPED_ANSWERING)
    for _ in range(20):
        await asyncio.sleep(0)

    [(args, kwargs)] = host_log.of("error")
    assert "engine failed" in args[0]
    assert kwargs == {
        "error_type": "EngineExit",
        "browser": {"operation": "engine_failed", "reason": "stopped_answering"},
    }
    assert {"browser": {"operation": "engine_relaunched", "dead_sessions": 1}} in [
        kwargs for _, kwargs in host_log.of("set")
    ]
    await host.stop()


@pytest.mark.unit
async def test_a_relaunch_that_fails_is_reported_before_the_host_gives_up(
    monkeypatch: pytest.MonkeyPatch, host_log: _Log
) -> None:
    first = StubEngine()
    install_launcher(monkeypatch, first)
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()

    first.fail()
    for _ in range(20):
        await asyncio.sleep(0)

    relaunch = host_log.of("error")[-1]
    assert "could not be relaunched" in relaunch[0][0]
    assert relaunch[1] == {"error_type": "IndexError"}


@pytest.mark.unit
async def test_a_retiring_engine_that_fails_is_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    serving, retiring = StubEngine(), StubEngine()
    host = make_host(serving)
    host._retiring.add(as_engine(retiring))

    await host._engine_lost(as_engine(retiring))

    assert host._retiring == set()
    assert retiring.shutdowns == [False]
    assert host._engine is as_engine(serving)


@pytest.mark.unit
async def test_a_retiring_engine_keeps_running_while_any_of_its_sessions_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retiring = StubEngine()
    host = make_host(StubEngine())
    install_mux(monkeypatch, FakeEngine())
    host._engine = as_engine(retiring)
    one = await host.create_context(None)
    install_mux(monkeypatch, FakeEngine())
    two = await host.create_context(None)
    host._engine = as_engine(StubEngine())
    host._retiring.add(as_engine(retiring))

    await host.dispose_context(one.session_id)
    assert retiring.shutdowns == []
    await host.dispose_context(two.session_id)

    assert retiring.shutdowns == [True]


@pytest.mark.unit
async def test_a_replacement_and_its_failure_are_each_reported(
    monkeypatch: pytest.MonkeyPatch, host_log: _Log
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", 1000)
    old = StubEngine(rss_mb=1600.4)
    install_launcher(monkeypatch, old, StubEngine())
    host = BrowserHost(on_fatal=MagicMock())
    await host.start()

    await host.dispose_context(await _session_on(host, monkeypatch))

    [(args, kwargs)] = host_log.of("warning")
    assert "replaced over its memory limit" in args[0]
    assert kwargs == {"browser": {"operation": "recycle", "rss_mb": 1600, "limit_mb": 1000}}

    host_log.calls.clear()
    host._engine = as_engine(StubEngine(rss_mb=2000.0))
    install_launcher(monkeypatch)
    await host.dispose_context(await _session_on(host, monkeypatch))
    [(args, kwargs)] = host_log.of("error")
    assert "replacement failed to launch" in args[0]
    assert kwargs == {"error_type": "IndexError"}
    await host.stop()


@pytest.mark.unit
async def test_the_launch_names_the_configured_engine_and_the_resolved_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = AsyncMock(return_value=(as_engine(StubEngine()), "UA"))
    monkeypatch.setattr(host_mod, "launch_engine", launch)
    host = BrowserHost(on_fatal=MagicMock())
    host._chromium_path = "/opt/chrome"
    host._user_agent = "Earlier UA"

    await host._launch()

    assert launch.await_args.args == (
        browser_host_settings.BROWSER_ENGINE,
        "/opt/chrome",
        "Earlier UA",
    )
    await host.stop()


@pytest.mark.unit
async def test_the_ceiling_counts_creates_still_in_flight(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 3)
    host = make_host()
    await host.create_context(None)
    engine.hang_on = "Target.createBrowserContext"
    in_flight = [asyncio.create_task(host.create_context(None)) for _ in range(2)]
    await _settle()

    with pytest.raises(AtCapacityError) as refused:
        await host.create_context(None)

    assert (refused.value.sessions, refused.value.pending) == (1, 2)
    for task in in_flight:
        task.cancel()
    await asyncio.gather(*in_flight, return_exceptions=True)


@pytest.mark.unit
async def test_a_short_admission_wait_still_admits_once_a_session_ends(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    monkeypatch.setattr(host_mod, "_ADMISSION_WAIT_SECONDS", 0.9)
    host = make_host()
    first = await host.create_context(None)
    waiting = asyncio.create_task(host.create_context(None))
    await _settle()

    await host.dispose_context(first.session_id)

    assert host.get((await asyncio.wait_for(waiting, 1.0)).session_id) is not None


@pytest.mark.unit
async def test_only_this_contexts_pages_are_ever_streamed(engine: FakeEngine) -> None:
    host = make_host()
    session = await host.create_context(None)
    foreign = engine.open_page("someone-else", url="https://theirs.example/")
    host.note_focus(session.session_id, foreign)
    del engine.pages[session.target_id]

    assert await host.focused_target_id(session) is None


@pytest.mark.unit
async def test_session_info_is_its_whole_view_inside_the_liveness_budget(
    engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    engine.pages[session.target_id].update(url="https://x.example/", title="X")

    info = await host.session_info(session.session_id)

    assert set(info) == {"session_id", "live", "url", "title", "metrics"}
    assert (info["session_id"], info["url"], info["title"]) == (
        session.session_id,
        "https://x.example/",
        "X",
    )
    assert info["metrics"] == session.metrics.snapshot() | {
        "session_lifetime_seconds": info["metrics"]["session_lifetime_seconds"]
    }
    assert stub.asked_within == [host_mod.BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS]
    getinfo = [c for c in engine.calls if c[0] == "Target.getTargetInfo"]
    assert getinfo[-1][1] == {"targetId": session.target_id}

    await engine.close()
    assert (await host.session_info(session.session_id))["live"] is False


@pytest.mark.unit
async def test_an_unresponsive_engine_names_the_session_asked_about(engine: FakeEngine) -> None:
    stub = StubEngine()
    host = make_host(stub)
    session = await host.create_context(None)
    stub.answers = False

    with pytest.raises(EngineUnresponsiveError) as refused:
        await host.session_info(session.session_id)

    assert refused.value.args == (session.session_id,)
    stub.is_alive = False
    with pytest.raises(EngineUnresponsiveError) as down:
        await host.storage_state(session.session_id)
    assert down.value.args == (session.session_id,)
    with pytest.raises(SessionNotFoundError) as missing:
        await host.storage_state("ghost")
    assert missing.value.args == ("ghost",)


@pytest.mark.unit
async def test_healthz_asks_within_its_own_budget() -> None:
    stub = StubEngine()

    await make_host(stub).healthz()

    assert stub.asked_within == [5.0]


@pytest.mark.unit
async def test_a_page_whose_meta_cannot_be_read_is_reported_without_one(
    monkeypatch: pytest.MonkeyPatch, host_log: _Log
) -> None:
    mux = install_mux(monkeypatch, FakeMux({"Target.createTarget": {"targetId": "t"}}))
    host = make_host()
    session = await host.create_context(None)
    assert await host._focused_page_meta(session) == (None, None)

    mux.send_error = CdpCommandError({"message": "gone"})
    assert await host._focused_page_meta(session) == (None, None)

    [(args, kwargs)] = host_log.of("warning")
    assert "page meta unread" in args[0]
    assert kwargs == {"error_type": "CdpCommandError"}
    asked = [c for c in mux.calls if c[0] == "Target.getTargetInfo"]
    assert asked[0][1] == {"targetId": "t"}


@pytest.mark.unit
async def test_a_lost_login_and_a_failed_context_dispose_are_each_reported(
    engine: FakeEngine, host_log: _Log
) -> None:
    host = make_host()
    session = await host.create_context(None)
    engine.send_error = CdpCommandError({"message": "gone"})

    with pytest.raises(CdpCommandError):
        await host.dispose_context(session.session_id)

    [(warning_args, warning_kwargs)] = host_log.of("warning")
    assert "context dispose failed" in warning_args[0]
    assert warning_kwargs == {"error_type": "CdpCommandError"}
    [(error_args, _)] = host_log.of("error")
    assert "without saving its storage state" in error_args[0]


@pytest.mark.unit
async def test_a_page_too_busy_to_say_where_it_is_reads_as_nowhere_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = install_mux(monkeypatch, FakeMux({"Target.createTarget": {"targetId": "t"}}))
    host = make_host()
    session = await host.create_context(None)
    mux.hang_on = "Target.getTargetInfo"
    monkeypatch.setattr(host_mod, "BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS", 0.01)

    assert await asyncio.wait_for(host._focused_page_meta(session), 1.0) == (None, None)
