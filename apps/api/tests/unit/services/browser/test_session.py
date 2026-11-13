"""Tests for browser_session lifecycle — including the registry-write gate."""

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

from playwright.sync_api import StorageState
import pytest

from app.constants.browser import (
    BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS,
    BROWSER_SESSION_LEASE_RENEW_SECONDS,
    BrowserEngine,
    EngineFailure,
)
from app.services.browser import session as session_mod
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)
from app.services.browser.session import BrowserHostSession
from tests.unit.services.browser.conftest import FakeHostClient

# The host a session lives on; every host call must name it, primary or fallback.
_HOST = "http://browser-host:8930"


def _handle(session_id: str = "sess-1") -> BrowserHostSession:
    return BrowserHostSession(
        session_id=session_id,
        cdp_url="ws://cdp",  # NOSONAR
        host_url=_HOST,
        engine=BrowserEngine.CHROMIUM,
        fortress=False,
    )


class _FakeLog:
    """Records structured-logging calls so tests can pin exact fields."""

    def __init__(self) -> None:
        self.set_calls: list[dict[str, Any]] = []
        self.info_calls: list[tuple[str, dict[str, Any]]] = []
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def set(self, **kwargs: Any) -> None:
        self.set_calls.append(kwargs)

    def info(self, message: str, /, **kwargs: Any) -> None:
        self.info_calls.append((message, kwargs))

    def warning(self, message: str, /, **kwargs: Any) -> None:
        self.warning_calls.append((message, kwargs))


@pytest.fixture
def fake_log(monkeypatch: pytest.MonkeyPatch) -> _FakeLog:
    fl = _FakeLog()
    monkeypatch.setattr(session_mod, "log", fl)
    return fl


def _login_on(host: str, value: str) -> StorageState:
    """Return a browser's state after signing in on host, the cookie valued so a save shows whose it was."""
    return {
        "cookies": [{"name": "session", "value": value, "domain": host, "path": "/"}],
        "origins": [],
    }


@dataclass(frozen=True)
class _SessionFakes:
    """The login store and session registry a browser_session talks to, as mocks a test asserts on."""

    load_storage_state: AsyncMock
    save_storage_state: AsyncMock
    register_session: AsyncMock
    unregister_session: AsyncMock


def _make_session_fakes(monkeypatch: pytest.MonkeyPatch) -> _SessionFakes:
    fakes = _SessionFakes(
        load_storage_state=AsyncMock(return_value=None),
        save_storage_state=AsyncMock(),
        register_session=AsyncMock(return_value=True),
        unregister_session=AsyncMock(),
    )
    for name in (
        "load_storage_state",
        "save_storage_state",
        "register_session",
        "unregister_session",
    ):
        monkeypatch.setattr(session_mod, name, getattr(fakes, name))
    return fakes


async def test_registry_write_failure_aborts_before_yield(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """A failed ownership write must fail the session (releasing the host context) instead of handing the user a live-view link that can never authorize."""
    fakes = _make_session_fakes(monkeypatch)
    fakes.register_session.return_value = False

    with pytest.raises(BrowserUnavailableError, match="register"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the failed registration")

    # The host context was still released on the way out — never orphaned.
    assert host_client.deleted == [("s1", _HOST)]
    fakes.unregister_session.assert_awaited()


async def test_registry_write_success_yields_and_releases(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Happy path: registration succeeds, the session yields, and release runs."""
    fakes = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as s:
        assert s.session_id == "s1"
    assert host_client.deleted == [("s1", _HOST)]
    # With the id, not merely "was called": deregistering the wrong session (or
    # None) leaves this one's ownership entry behind, and the reaper then never
    # collects it.
    fakes.unregister_session.assert_awaited_once_with("s1")


async def test_domain_derived_from_start_url_feeds_storage_lookup(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Look up with host_of(start_url), not start_url itself."""
    fakes = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u42", start_url="https://Example.com/page"
    ):
        pass

    fakes.load_storage_state.assert_awaited_once_with("u42", "example.com")


async def test_none_start_url_looks_up_with_none_domain(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url=None):
        pass

    fakes.load_storage_state.assert_awaited_once_with("u1", None)


async def test_create_session_receives_the_loaded_storage_state(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    sentinel_state = {"cookies": ["loaded"]}
    fakes.load_storage_state.return_value = sentinel_state

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    assert host_client.created == [(sentinel_state, _HOST)]


async def test_session_fields_are_mapped_from_the_host_response(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Map each BrowserHostSession field from the matching host attribute, not a swapped one."""
    _make_session_fakes(monkeypatch)
    host_client.ids = ["sid-x"]
    host_client.engine = BrowserEngine.OBSCURA
    host_client.fortress = True

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as s:
        assert s.session_id == "sid-x"
        assert s.cdp_url == "ws://host/cdp/sid-x"
        assert s.host_url == _HOST
        assert s.engine is BrowserEngine.OBSCURA
        assert s.fortress is True
        # A later handover protects this site's login by it.
        assert s.start_domain == "x"


async def test_the_wide_event_names_the_session_this_request_created(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient, fake_log: _FakeLog
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    assert {"browser": {"session_id": "s1", "operation": "create"}} in fake_log.set_calls


async def test_register_session_called_with_session_id_user_id_and_live_ws(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="user-77", start_url="https://x"
    ):
        pass

    fakes.register_session.assert_awaited_once_with("s1", "user-77", live_ws="ws://host/live/s1")


async def test_host_create_failure_skips_all_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """If the host never created a session, there is nothing to release — the finally block (register/delete/save/unregister) must not run at all."""
    fakes = _make_session_fakes(monkeypatch)
    host_client.create_errors["s1"] = BrowserUnavailableError("host unreachable")

    with pytest.raises(BrowserUnavailableError, match="host unreachable"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the host create failure")

    fakes.register_session.assert_not_awaited()
    assert host_client.deleted == []
    fakes.save_storage_state.assert_not_awaited()
    fakes.unregister_session.assert_not_awaited()


async def test_body_exception_propagates_and_release_still_runs(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)

    with pytest.raises(ValueError, match="body boom"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            raise ValueError("body boom")

    assert host_client.deleted == [("s1", _HOST)]
    fakes.unregister_session.assert_awaited_once()


async def test_delete_session_called_with_this_sessions_id(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    assert host_client.deleted == [("s1", _HOST)]


async def test_save_storage_state_called_with_user_domain_and_returned_state(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """A run seeded from a saved login writes the rotated state back."""
    fakes = _make_session_fakes(monkeypatch)
    returned_state = _login_on("foo.example.com", "returned")
    fakes.load_storage_state.return_value = {"cookies": ["seeded"]}
    host_client.states["s1"] = returned_state

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u42", start_url="https://foo.example.com/x"
    ):
        pass

    fakes.save_storage_state.assert_awaited_once_with("u42", "foo.example.com", returned_state)


async def test_a_run_that_never_signed_in_saves_nothing(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient
) -> None:
    """Regression: a wikipedia.org language cookie was kept as a saved login and answered the next task in German."""
    fakes = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://www.wikipedia.org"
    ):
        pass

    fakes.save_storage_state.assert_not_awaited()


async def test_a_saved_login_the_site_asks_to_sign_in_over_again_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    fakes.load_storage_state.return_value = {"cookies": ["seeded"]}

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://foo.example.com/x"
    ) as session:
        session.forget_login("https://foo.example.com/login")

    fakes.save_storage_state.assert_not_awaited()


async def test_a_run_whose_login_takeover_completed_saves_its_state(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    returned_state = _login_on("x.com", "signed-in")
    host_client.states["s1"] = returned_state

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as session:
        session.mark_authenticated("https://x.com/home")

    fakes.save_storage_state.assert_awaited_once_with("u1", "x.com", returned_state)


async def test_a_sign_in_is_saved_for_the_site_it_happened_on_whatever_the_run_started_on(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Regression: a login was keyed on the start URL's domain, so a run with none saved nothing."""
    fakes = _make_session_fakes(monkeypatch)
    returned_state = _login_on("the-internet.herokuapp.com", "signed-in")
    host_client.states["s1"] = returned_state

    async with session_mod.browser_session(host_url=_HOST, user_id="u1") as session:
        session.mark_authenticated("https://the-internet.herokuapp.com/secure")

    fakes.save_storage_state.assert_awaited_once_with(
        "u1", "the-internet.herokuapp.com", returned_state
    )


#: The primary's live browser after the user signed in on flights.example.com.
_CARRIED_STATE: StorageState = {
    "cookies": [
        {"name": "session", "value": "signed-in", "domain": "flights.example.com", "path": "/"}
    ],
    "origins": [
        {"origin": "https://flights.example.com", "localStorage": [{"name": "t", "value": "live"}]}
    ],
}
#: The user's saved login for news.example.com, holding an older flights cookie too.
_SAVED_NEWS_LOGIN: StorageState = {
    "cookies": [
        {"name": "session", "value": "stale", "domain": "flights.example.com", "path": "/"},
        {"name": "sid", "value": "reader", "domain": "news.example.com", "path": "/"},
    ],
    "origins": [
        {"origin": "https://flights.example.com", "localStorage": [{"name": "t", "value": "old"}]},
        {"origin": "https://news.example.com", "localStorage": [{"name": "k", "value": "v"}]},
    ],
}
_FALLBACK_HOST = "http://fallback-host:8931"


def _signed_in_primary() -> BrowserHostSession:
    primary = _handle("primary")
    primary.mark_authenticated("https://flights.example.com/account")
    return primary


def _host_per_session(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient
) -> _SessionFakes:
    """Open "primary" then "fallback"; each disposes to a state naming it, so a save shows whose it was."""
    fakes = _make_session_fakes(monkeypatch)
    host_client.ids = ["primary", "fallback"]
    host_client.states = {name: _login_on("x.com", name) for name in host_client.ids}
    return fakes


async def test_a_session_opened_with_carried_state_saves_the_login_under_the_site_it_belongs_to(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    returned_state = _login_on("flights.example.com", "still signed in")
    host_client.states["s1"] = returned_state
    carried = session_mod.LiveSessionState(
        storage_state=_CARRIED_STATE, source=_signed_in_primary()
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://cdn.example.net/page", carried=carried
    ):
        pass

    assert host_client.created == [(_CARRIED_STATE, _HOST)]
    # Saved where the login belongs, not under the page the run moved over on.
    fakes.save_storage_state.assert_awaited_once_with("u1", "flights.example.com", returned_state)


async def test_carried_state_the_user_never_approved_as_a_login_is_never_saved(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    carried = session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=_handle())

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com", carried=carried
    ):
        pass

    fakes.save_storage_state.assert_not_awaited()


async def test_a_session_opened_with_carried_state_is_also_signed_in_to_the_site_it_resumes_on(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Carrying the primary's state stopped the fallback loading the saved login for the page it resumes on; the live cookies still win."""
    fakes = _make_session_fakes(monkeypatch)
    fakes.load_storage_state.return_value = _SAVED_NEWS_LOGIN
    carried = session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=_handle())

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://news.example.com/a", carried=carried
    ):
        pass

    fakes.load_storage_state.assert_awaited_once_with("u1", "news.example.com")
    [(seeded, _)] = host_client.created
    assert sorted((c["domain"], c["name"], c["value"]) for c in seeded["cookies"]) == [
        ("flights.example.com", "session", "signed-in"),
        ("news.example.com", "sid", "reader"),
    ]
    assert sorted((o["origin"], o["localStorage"][0]["value"]) for o in seeded["origins"]) == [
        ("https://flights.example.com", "live"),
        ("https://news.example.com", "v"),
    ]


async def test_each_site_a_carried_session_saves_gets_only_its_own_cookies_and_storage(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Regression (Greptile on #876): the whole returned state was saved under every login site, so each record held the other's cookies."""
    fakes = _make_session_fakes(monkeypatch)
    returned_state: StorageState = {
        "cookies": [
            {"name": "session", "value": "f", "domain": "flights.example.com", "path": "/"},
            {"name": "sid", "value": "n", "domain": "news.example.com", "path": "/"},
            {"name": "sso", "value": "s", "domain": ".example.com", "path": "/"},
        ],
        "origins": [
            {"origin": "https://flights.example.com", "localStorage": []},
            {"origin": "https://news.example.com", "localStorage": []},
        ],
    }
    fakes.load_storage_state.return_value = _SAVED_NEWS_LOGIN
    host_client.states["s1"] = returned_state
    carried = session_mod.LiveSessionState(
        storage_state=_CARRIED_STATE, source=_signed_in_primary()
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://news.example.com/a", carried=carried
    ):
        pass

    saved = {call.args[1]: call.args[2] for call in fakes.save_storage_state.await_args_list}
    cookies, origins = returned_state["cookies"], returned_state["origins"]
    assert saved == {
        "flights.example.com": {"cookies": [cookies[0], cookies[2]], "origins": [origins[0]]},
        "news.example.com": {"cookies": [cookies[1], cookies[2]], "origins": [origins[1]]},
    }


#: The user's saved login for flights.example.com, from before the run signed out.
_SAVED_FLIGHTS_LOGIN: StorageState = {
    "cookies": [
        {"name": "session", "value": "stale", "domain": "flights.example.com", "path": "/"},
        {"name": "sso", "value": "stale", "domain": ".example.com", "path": "/"},
    ],
    "origins": [
        {"origin": "https://flights.example.com", "localStorage": [{"name": "t", "value": "old"}]}
    ],
}


async def _seeded_fallback(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
    carried: session_mod.LiveSessionState,
) -> Any:
    """Open a fallback on flights.example.com over the saved flights login; return what it was seeded with."""
    fakes = _make_session_fakes(monkeypatch)
    fakes.load_storage_state.return_value = _SAVED_FLIGHTS_LOGIN
    async with session_mod.browser_session(
        host_url=_FALLBACK_HOST,
        user_id="u1",
        start_url="https://flights.example.com/",
        carried=carried,
    ):
        pass
    [(seeded, _)] = host_client.created
    return seeded


async def test_a_sign_out_on_the_primary_is_not_undone_by_the_saved_login_on_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Regression (Greptile on #876): a logout cleared the site's cookies, and the overlay seeded the saved copies back into the fallback."""
    signed_out: StorageState = {
        "cookies": [],
        "origins": [{"origin": "https://flights.example.com", "localStorage": []}],
    }
    carried = session_mod.LiveSessionState(storage_state=signed_out, source=_signed_in_primary())

    seeded = await _seeded_fallback(monkeypatch, host_client, carried)

    assert seeded == signed_out


async def test_saved_storage_the_live_browser_had_no_page_on_is_kept_for_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """A browser reports localStorage only for pages it has open, so silence is not a cleared store."""
    carried = session_mod.LiveSessionState(
        storage_state={"cookies": [], "origins": []}, source=_signed_in_primary()
    )

    seeded = await _seeded_fallback(monkeypatch, host_client, carried)

    assert seeded == {"cookies": [], "origins": _SAVED_FLIGHTS_LOGIN["origins"]}


async def test_a_cookie_the_primary_deleted_stays_deleted_on_a_site_it_still_holds_cookies_for(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """The carried state is the whole truth for a site it has cookies for, not an update to lay over the saved login."""
    after_logout: StorageState = {
        "cookies": [{"name": "lang", "value": "en", "domain": "flights.example.com", "path": "/"}],
        "origins": [],
    }
    carried = session_mod.LiveSessionState(storage_state=after_logout, source=_handle())

    seeded = await _seeded_fallback(monkeypatch, host_client, carried)

    assert seeded["cookies"] == after_logout["cookies"]


async def test_handing_over_a_live_session_reads_its_state_and_names_it_the_source(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    host_client.states["primary"] = _CARRIED_STATE
    primary = _signed_in_primary()

    state = await session_mod.hand_over_state(primary)

    assert host_client.reads == [("primary", _HOST)]
    assert state == session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=primary)


async def test_handing_over_a_session_whose_engine_is_gone_raises(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """The read used to swallow the failure and return None; the caller decides what a run without the state does."""
    host_client.gone.add("primary")

    with pytest.raises(BrowserSessionGone):
        await session_mod.hand_over_state(_signed_in_primary())


async def test_a_login_carried_to_the_fallback_is_saved_once_from_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """The primary is released after the fallback; saving from both wrote its older cookies over the fallback's."""
    fakes = _host_per_session(monkeypatch, host_client)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as primary:
        primary.mark_authenticated("https://x.com/home")
        carried = await session_mod.hand_over_state(primary)
        async with session_mod.browser_session(
            host_url=_FALLBACK_HOST, user_id="u1", start_url="https://x.com/feed", carried=carried
        ):
            pass

    fakes.save_storage_state.assert_awaited_once_with("u1", "x.com", _login_on("x.com", "fallback"))


async def test_a_login_is_saved_from_the_primary_when_the_fallback_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """The handover cleared the primary's right to save before the fallback existed, so a full fallback host lost the login."""
    fakes = _host_per_session(monkeypatch, host_client)
    host_client.create_errors["fallback"] = BrowserConcurrencyLimit("at capacity")

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as primary:
        primary.mark_authenticated("https://x.com/home")
        carried = await session_mod.hand_over_state(primary)
        with pytest.raises(BrowserConcurrencyLimit):
            async with session_mod.browser_session(
                host_url=_FALLBACK_HOST,
                user_id="u1",
                start_url="https://x.com/feed",
                carried=carried,
            ):
                pytest.fail("the fallback opened on a full host")

    fakes.save_storage_state.assert_awaited_once_with("u1", "x.com", _login_on("x.com", "primary"))


async def test_a_sign_in_asked_for_again_after_the_switch_is_saved_by_neither_browser(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    """Regression: the fallback forgot the login it was asked to redo, and the primary, released later, saved it anyway."""
    fakes = _host_per_session(monkeypatch, host_client)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as primary:
        primary.mark_authenticated("https://x.com/home")
        carried = await session_mod.hand_over_state(primary)
        async with session_mod.browser_session(
            host_url=_FALLBACK_HOST, user_id="u1", start_url="https://x.com/feed", carried=carried
        ) as fallback:
            fallback.forget_login("https://x.com/login")

    fakes.save_storage_state.assert_not_awaited()


async def test_release_failure_is_caught_logged_and_unregister_still_runs(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient, fake_log: _FakeLog
) -> None:
    """A release-time failure must not propagate out of the context manager (the body's own outcome should not be masked by a cleanup error), must be logged with the actual exception type, and unregister must still run."""
    fakes = _make_session_fakes(monkeypatch)
    host_client.delete_errors["s1"] = RuntimeError("host down")

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    fakes.save_storage_state.assert_not_awaited()
    fakes.unregister_session.assert_awaited_once()
    assert len(fake_log.warning_calls) == 1
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] Failed to release browser session"
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["browser"] == {"session_id": "s1", "operation": "release_failed"}


async def test_save_storage_state_failure_is_also_caught(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient, fake_log: _FakeLog
) -> None:
    fakes = _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod, "save_storage_state", AsyncMock(side_effect=ValueError("disk full"))
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as session:
        session.mark_authenticated("https://x.com/home")

    fakes.unregister_session.assert_awaited_once()
    assert len(fake_log.warning_calls) == 1
    _, kwargs = fake_log.warning_calls[0]
    assert kwargs["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# keep_session_alive — the run's lease on its session
# ---------------------------------------------------------------------------


async def test_the_lease_is_renewed_every_interval_and_a_failed_renewal_is_retried(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient, fake_log: _FakeLog
) -> None:
    """The host disposes a session whose lease runs out, so one failed renewal must not end the loop."""
    sleep_mock = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)
    host_client.renew_errors = [BrowserUnavailableError("host down")]

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive(_handle("sess-1"))

    sleep_mock.assert_awaited_with(BROWSER_SESSION_LEASE_RENEW_SECONDS)
    assert host_client.renewals == [("sess-1", _HOST)] * 2
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] Browser session lease renewal failed"
    assert kwargs["error_type"] == "BrowserUnavailableError"
    assert kwargs["browser"] == {"session_id": "sess-1", "operation": "lease_renewal"}


async def test_a_session_its_host_lost_is_marked_gone_and_renewed_no_more(
    monkeypatch: pytest.MonkeyPatch, host_client: FakeHostClient, fake_log: _FakeLog
) -> None:
    """A paused run's handoff ends on the mark; renewing a session the host no longer has would only fail again."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    host_client.gone.add("sess-1")
    handle = _handle("sess-1")

    await asyncio.wait_for(session_mod.keep_session_alive(handle), timeout=1)

    assert handle.gone.is_set()
    assert host_client.renewals == [("sess-1", _HOST)]
    [(message, kwargs)] = fake_log.warning_calls
    assert message == "[BROWSER] Browser session gone from its host"
    assert kwargs["browser"] == {"session_id": "sess-1", "operation": "lease_renewal"}


async def test_a_session_holds_its_lease_for_exactly_its_life(
    monkeypatch: pytest.MonkeyPatch,
    host_client: FakeHostClient,
) -> None:
    _make_session_fakes(monkeypatch)
    held: list[str] = []
    holding, let_go = asyncio.Event(), asyncio.Event()

    async def _hold(session: BrowserHostSession) -> None:
        held.append(session.session_id)
        holding.set()
        try:
            await asyncio.Event().wait()
        finally:
            let_go.set()

    monkeypatch.setattr(session_mod, "keep_session_alive", _hold)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        await asyncio.wait_for(holding.wait(), 1.0)
        assert held == ["s1"]
        assert not let_go.is_set()
    await asyncio.wait_for(let_go.wait(), 1.0)


@pytest.mark.unit
class TestEngineFailure:
    async def test_the_probe_asks_about_this_session_and_gives_up_quickly(
        self, host_client: FakeHostClient
    ) -> None:
        """A wedged engine is what the probe detects; an unbounded read would wedge with it."""
        assert await session_mod.engine_failure(_handle("sess-9")) is None

        assert host_client.probes == [("sess-9", _HOST, BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS)]

    async def test_a_session_the_host_lost_or_holds_dead_is_gone(
        self, host_client: FakeHostClient
    ) -> None:
        host_client.live = False
        assert await session_mod.engine_failure(_handle("sess-9")) is EngineFailure.SESSION_GONE
        host_client.gone.add("sess-9")
        assert await session_mod.engine_failure(_handle("sess-9")) is EngineFailure.SESSION_GONE
