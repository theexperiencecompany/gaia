"""A session's context against an engine that answers CDP the way the engine does.

Each test asserts what the engine ends up holding (the context, its page, its
cookie jar, its download policy) or what the host hands back, never which
frames were sent: FakeEngine enforces the protocol, so a malformed command
fails the way it would against Chromium or Obscura.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast
from unittest.mock import MagicMock

from playwright.sync_api import StorageState
import pytest

from app.browser_host import chromium
from app.browser_host.cdp_mux import CdpMux
from app.browser_host.chromium import ChromiumHost, EngineUnresponsiveError, HostSession
from app.constants.log_tags import LogTag
from tests.unit.browser_host.conftest import DEFAULT_CONTEXT, FakeEngine, install_mux, make_host

pytestmark = pytest.mark.unit

# A session cookie (no expiry) and a persistent, locked-down one, in Playwright's shape.
_SESSION_COOKIE = {
    "name": "sid",
    "value": "abc",
    "domain": ".shop.test",
    "path": "/",
    "expires": -1,
    "httpOnly": False,
    "secure": False,
}
_LOGIN_COOKIE = {
    "name": "auth",
    "value": "tok",
    "domain": "shop.test",
    "path": "/account",
    "expires": 1893456000,
    "httpOnly": True,
    "secure": True,
    "sameSite": "Lax",
}


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    return cast(FakeEngine, install_mux(monkeypatch, FakeEngine()))


@pytest.fixture
def host(engine: FakeEngine) -> ChromiumHost:
    built = make_host()
    built._root_mux = cast(CdpMux, engine)
    return built


def _state(*cookies: dict[str, Any], origins: list[Any] | None = None) -> StorageState:
    return cast(StorageState, {"cookies": list(cookies), "origins": origins or []})


def _sampler(rss_mb: float) -> MagicMock:
    sampler = MagicMock()
    sampler.sample.return_value = (rss_mb, 5.0)
    return sampler


# --- create ---


async def test_a_new_session_opens_one_blank_page_in_its_own_context(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    before = time.monotonic()
    session = await host.create_context(None)
    after = time.monotonic()

    page = engine.pages[session.target_id]
    assert (page["context"], page["url"]) == (session.context_id, "about:blank")
    assert session.context_id in engine.contexts
    assert host.get(session.session_id) is session
    assert len(session.session_id) == 32
    assert before <= session.created_at == session.last_activity_at <= after


async def test_downloads_are_refused_in_the_new_context_and_nowhere_else(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    """A drive-by download is the cheapest way onto the host's disk; other sessions keep theirs."""
    session = await host.create_context(None)

    assert engine.contexts[session.context_id]["download"] == "deny"
    assert engine.contexts[DEFAULT_CONTEXT]["download"] is None


async def test_a_finished_create_hands_its_reservation_to_the_session(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counted twice, the second of two creates under a ceiling of two is refused."""
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 2)

    await host.create_context(None)
    await host.create_context(None)

    assert len(host._sessions) == 2


async def test_a_create_takes_the_sessions_first_resource_reading(host: ChromiumHost) -> None:
    host._sampler = _sampler(300.0)

    session = await host.create_context(None)

    snapshot = session.metrics.snapshot()
    assert snapshot["rss_mb"] is not None
    assert snapshot["rss_mb"]["count"] == 1


async def test_a_create_names_its_session_on_the_wide_event(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    session = await host.create_context(None)

    logger.set.assert_called_once_with(
        browser={"session_id": session.session_id, "operation": "create"}
    )


# --- storage state: seed on create, dump on dispose ---


async def test_a_saved_login_is_seeded_into_the_new_contexts_jar_only(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(_state(_SESSION_COOKIE, _LOGIN_COOKIE))

    jar = {c["name"]: c for c in engine.contexts[session.context_id]["cookies"]}
    assert set(jar) == {"sid", "auth"}
    assert jar["sid"]["session"] is True
    assert (jar["auth"]["expires"], jar["auth"]["sameSite"]) == (1893456000, "Lax")
    assert (jar["auth"]["httpOnly"], jar["auth"]["secure"], jar["auth"]["path"]) == (
        True,
        True,
        "/account",
    )
    assert engine.contexts[DEFAULT_CONTEXT]["cookies"] == []


async def test_a_cookie_saved_without_its_optional_fields_is_seeded_with_the_defaults(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(
        _state({"name": "sid", "value": "abc", "domain": "shop.test"})
    )

    (cookie,) = engine.contexts[session.context_id]["cookies"]
    assert (cookie["path"], cookie["secure"], cookie["httpOnly"], cookie["session"]) == (
        "/",
        False,
        False,
        True,
    )
    assert "sameSite" not in cookie


async def test_a_state_without_cookies_seeds_none(host: ChromiumHost, engine: FakeEngine) -> None:
    session = await host.create_context(cast(StorageState, {"origins": []}))

    assert engine.contexts[session.context_id]["cookies"] == []
    assert "Storage.setCookies" not in engine.methods


async def test_a_login_survives_the_round_trip_through_a_session(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    """What dispose returns is what the next session is seeded with; any drift logs the user out."""
    session = await host.create_context(_state(_SESSION_COOKIE, _LOGIN_COOKIE))

    state = await host.dispose_context(session.session_id)

    assert state["cookies"] == [_SESSION_COOKIE, _LOGIN_COOKIE]


async def test_the_dump_reads_localstorage_from_this_contexts_pages_only(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    engine.open_page(session.context_id, url="https://shop.test/cart", storage={"cart": "3"})
    engine.open_page(session.context_id, url="https://blank.test/", storage={})
    engine.open_page(DEFAULT_CONTEXT, url="https://other.test/", storage={"theirs": "x"})

    state = await host.storage_state(session.session_id)

    assert state["origins"] == [
        {"origin": "https://shop.test", "localStorage": [{"name": "cart", "value": "3"}]}
    ]
    assert engine.attached == {}, "every page the dump attached to is detached again"


# --- dispose ---


async def test_dispose_removes_the_context_from_the_engine(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)

    await host.dispose_context(session.session_id)

    assert session.context_id not in engine.contexts
    assert host.get(session.session_id) is None


async def test_dispose_takes_a_last_resource_reading(host: ChromiumHost) -> None:
    host._sampler = _sampler(300.0)
    session = await host.create_context(None)

    await host.dispose_context(session.session_id)

    rss = session.metrics.snapshot()["rss_mb"]
    assert rss is not None
    assert rss["count"] == 2


async def test_a_clean_dispose_reports_the_session_and_its_metrics(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await host.create_context(None)
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await host.dispose_context(session.session_id)

    logger.set.assert_called_once_with(
        browser={"session_id": session.session_id, "operation": "dispose"}
    )
    (ns_call,) = logger.set_ns.call_args_list
    assert ns_call.args == ("browser",)
    assert ns_call.kwargs["metrics"]["page_count"] == 1
    logger.error.assert_not_called()


async def test_a_dispose_that_lost_the_login_says_so(
    host: ChromiumHost, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await host.create_context(None)
    engine.send_error = RuntimeError("engine gone")
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    with pytest.raises(RuntimeError):
        await host.dispose_context(session.session_id)

    logger.error.assert_any_call(
        f"{LogTag.BROWSER} browser context disposed without saving its storage state",
        error_type="StorageDumpFailed",
    )


async def test_a_failed_context_dispose_is_warned_about_and_the_connection_still_closed(
    host: ChromiumHost, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await host.create_context(None)
    del engine.contexts[session.context_id]
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await host._close_session_connection(session)

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser host context dispose failed", error_type="CdpProtocolError"
    )
    assert engine.closed


async def test_a_closed_connection_is_not_asked_to_dispose_anything(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    await engine.close()

    await host._close_session_connection(session)

    assert "Target.disposeBrowserContext" not in engine.methods


# --- reading a live session ---


async def test_the_focused_page_is_the_primary_while_it_is_open(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    engine.open_page(session.context_id, url="https://shop.test/")

    assert await host.focused_target_id(session.session_id) == session.target_id


async def test_with_the_primary_closed_the_newest_page_of_this_context_is_focused(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    del engine.pages[session.target_id]
    older = engine.open_page(session.context_id, url="https://shop.test/a")
    engine.open_page(session.context_id, url="https://shop.test/b")
    newest = engine.open_page(session.context_id, url="https://shop.test/c")
    engine.open_page(session.context_id, url="https://shop.test/sw.js", kind="service_worker")
    engine.open_page(DEFAULT_CONTEXT, url="https://other.test/")

    assert older != newest
    assert await host.focused_target_id(session.session_id) == newest


async def test_a_context_with_no_page_left_falls_back_to_its_primary_id(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    del engine.pages[session.target_id]
    engine.open_page(DEFAULT_CONTEXT, url="https://other.test/")

    assert await host.focused_target_id(session.session_id) == session.target_id


async def test_session_info_reads_this_contexts_page(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    del engine.pages[session.target_id]
    engine.open_page(DEFAULT_CONTEXT, url="https://other.test/", title="Not yours")
    engine.open_page(session.context_id, url="https://shop.test/cart", title="Cart")

    info = await host.session_info(session.session_id)

    assert info["session_id"] == session.session_id
    assert info["live"] is True
    assert info["last_activity_at"] == session.last_activity_at
    assert (info["url"], info["title"]) == ("https://shop.test/cart", "Cart")


async def test_a_dead_session_reads_as_not_live_without_asking_the_engine(
    host: ChromiumHost, engine: FakeEngine
) -> None:
    session = await host.create_context(None)
    session.dead = True
    asked = len(engine.calls)

    info = await host.session_info(session.session_id)

    assert (info["live"], info["url"], info["title"]) == (False, None, None)
    assert len(engine.calls) == asked


async def test_an_unresponsive_engine_names_the_session_it_was_asked_about(
    host: ChromiumHost,
) -> None:
    session = await host.create_context(None)
    host._root_mux = None

    with pytest.raises(EngineUnresponsiveError) as err:
        await host.session_info(session.session_id)

    assert err.value.args == (session.session_id,)


async def test_an_unknown_session_names_the_id_it_was_asked_for(host: ChromiumHost) -> None:
    with pytest.raises(chromium.SessionNotFoundError) as err:
        await host.storage_state("nope")

    assert err.value.args == ("nope",)


async def test_a_dump_on_a_down_engine_names_its_session(host: ChromiumHost) -> None:
    session = await host.create_context(None)
    host._proc = None

    with pytest.raises(EngineUnresponsiveError) as err:
        await host.storage_state(session.session_id)

    assert err.value.args == (session.session_id,)


# --- metrics hooks ---


async def test_a_finished_navigation_takes_a_reading_only_when_one_was_started(
    host: ChromiumHost,
) -> None:
    host._sampler = _sampler(300.0)
    session = await host.create_context(None)

    host.note_navigation_finished(session.session_id)
    unmatched = session.metrics.snapshot()["rss_mb"]
    host.note_navigation_started(session.session_id)
    host.note_navigation_finished(session.session_id)
    matched = session.metrics.snapshot()["rss_mb"]

    assert unmatched is not None and matched is not None
    assert (unmatched["count"], matched["count"]) == (1, 2)


# --- idle reaping ---


def _idle(host: ChromiumHost, session_id: str, seconds: float) -> HostSession:
    session = host._sessions[session_id]
    session.last_activity_at = time.monotonic() - seconds
    return session


@pytest.fixture
def ttl_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 400)
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_MEMORY_SOFT_WATERMARK", 0.8)


@pytest.mark.usefixtures("ttl_400")
async def test_memory_pressure_reaps_idle_sessions_at_a_quarter_of_the_ttl(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = _idle(host, (await host.create_context(None)).session_id, 90).session_id
    reap = _idle(host, (await host.create_context(None)).session_id, 110).session_id
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (900.0, 1000.0))

    await host._reap_idle()

    assert set(host._sessions) == {keep}
    assert reap not in host._sessions


@pytest.mark.usefixtures("ttl_400")
async def test_without_pressure_the_full_ttl_applies(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _idle(host, (await host.create_context(None)).session_id, 110)
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (790.0, 1000.0))

    await host._reap_idle()

    assert host.get(session.session_id) is session


async def test_pressure_never_reaps_sooner_than_the_floor(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 60)
    keep = _idle(host, (await host.create_context(None)).session_id, 25).session_id
    reap = _idle(host, (await host.create_context(None)).session_id, 35).session_id
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (990.0, 1000.0))

    await host._reap_idle()

    assert set(host._sessions) == {keep}
    assert reap not in host._sessions


@pytest.mark.usefixtures("ttl_400")
async def test_an_unknown_memory_limit_is_never_read_as_pressure(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _idle(host, (await host.create_context(None)).session_id, 110)
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (900.0, 0.0))

    await host._reap_idle()

    assert host.get(session.session_id) is session


async def test_a_reap_keeps_going_past_a_session_disposed_mid_sweep(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    ids = [(await host.create_context(None)).session_id for _ in range(3)]
    for session_id in ids:
        _idle(host, session_id, 60)
    real_close = host._close_session_connection

    async def _close_and_race_a_dispose(session: HostSession) -> None:
        await real_close(session)
        host._sessions.pop(ids[1], None)  # the user disposed it while the reaper worked

    monkeypatch.setattr(host, "_close_session_connection", _close_and_race_a_dispose)

    await host._reap_idle()

    assert host._sessions == {}


async def test_a_reap_names_each_session_it_took(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    session_id = _idle(host, (await host.create_context(None)).session_id, 60).session_id
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await host._reap_idle()

    logger.set.assert_called_once_with(browser={"session_id": session_id, "operation": "idle_reap"})


# --- crash recovery ---


async def test_crash_recovery_reports_how_many_sessions_died(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    await host.create_context(None)
    await host.create_context(None)
    host._proc = MagicMock(returncode=-9)
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)
    relaunched = asyncio.Event()

    async def _relaunch() -> None:
        relaunched.set()

    monkeypatch.setattr(host, "_shutdown_chromium", _relaunch)
    monkeypatch.setattr(host, "_launch", _relaunch)

    await host._recover_crash()

    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser engine crashed; relaunching",
        browser={"operation": "crash_recover", "dead_sessions": 2},
    )
    assert relaunched.is_set()


# --- disposals racing the reaper ---


class _SlowDump(FakeEngine):
    """Hold the storage dump until the test lets it go, so something else can move first."""

    def __init__(self) -> None:
        super().__init__()
        self.dumping = asyncio.Event()
        self.release = asyncio.Event()

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        if method == "Storage.getCookies":
            self.dumping.set()
            await self.release.wait()
        return await super().send_raw(method, params, session_id)


async def test_a_dispose_whose_session_left_the_registry_mid_dump_still_returns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another path (a reap, a crash sweep) may drop the entry while the dump is in flight."""
    engine = cast(_SlowDump, install_mux(monkeypatch, _SlowDump()))
    host = make_host()
    host._root_mux = cast(CdpMux, engine)
    session = await host.create_context(_state(_LOGIN_COOKIE))
    dispose = asyncio.create_task(host.dispose_context(session.session_id))
    await engine.dumping.wait()

    host._sessions.pop(session.session_id)
    engine.release.set()

    assert (await dispose)["cookies"] == [_LOGIN_COOKIE]


async def test_a_reap_the_user_disposed_first_finishes_cleanly(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_IDLE_TTL_SECONDS", 10)
    session_id = _idle(host, (await host.create_context(None)).session_id, 60).session_id
    await host._lock.acquire()
    dispose = asyncio.create_task(host.dispose_context(session_id))
    await asyncio.sleep(0.01)  # the dispose reaches the registry lock first
    reap = asyncio.create_task(host._reap_idle())
    await asyncio.sleep(0.01)  # the reap queues behind it
    host._lock.release()

    await asyncio.gather(dispose, reap)

    assert host._sessions == {}
