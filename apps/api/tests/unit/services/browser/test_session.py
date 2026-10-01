"""Tests for browser_session lifecycle — including the registry-write gate."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser import session as session_mod
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)
from app.services.browser.session import BrowserHostSession

# The host a session lives on; every host call must name it, primary or fallback.
_HOST = "http://browser-host:8930"


def _handle(session_id: str = "sess-1") -> BrowserHostSession:
    return BrowserHostSession(
        session_id=session_id,
        cdp_url="ws://cdp",  # NOSONAR
        live_view_url="https://live",
        host_url=_HOST,
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


def _login_on(host: str, value: str) -> dict[str, Any]:
    """Return a browser's state after signing in on host, the cookie valued so a save shows whose it was."""
    return {
        "cookies": [{"name": "session", "value": value, "domain": host, "path": "/"}],
        "origins": [],
    }


def _make_session_fakes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    host = MagicMock(
        session_id="s1",
        cdp_ws="ws://x",  # NOSONAR
        live_ws="ws://live",  # NOSONAR
    )
    monkeypatch.setattr(session_mod.host_client, "create_session", AsyncMock(return_value=host))
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=_login_on("x.com", "s1"))
    )
    monkeypatch.setattr(session_mod, "load_storage_state", AsyncMock(return_value=None))
    monkeypatch.setattr(session_mod, "save_storage_state", AsyncMock())
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=True))
    monkeypatch.setattr(session_mod, "unregister_session", AsyncMock())
    return host


async def test_registry_write_failure_aborts_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed ownership write must fail the session (releasing the host context) instead of handing the user a live-view link that can never authorize."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=False))

    with pytest.raises(BrowserUnavailableError, match="register"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the failed registration")

    # The host context was still released on the way out — never orphaned.
    session_mod.host_client.delete_session.assert_awaited()
    session_mod.unregister_session.assert_awaited()


async def test_registry_write_success_yields_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: registration succeeds, the session yields, and release runs."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as s:
        assert s.session_id == "s1"
    session_mod.host_client.delete_session.assert_awaited_once()
    # With the id, not merely "was called": deregistering the wrong session (or
    # None) leaves this one's ownership entry behind, and the reaper then never
    # collects it.
    session_mod.unregister_session.assert_awaited_once_with("s1")


async def test_domain_derived_from_start_url_feeds_storage_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Look up with domain_of(start_url), not start_url itself."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u42", start_url="https://Example.com/page"
    ):
        pass

    session_mod.load_storage_state.assert_awaited_once_with("u42", "example.com")


async def test_none_start_url_looks_up_with_none_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url=None):
        pass

    session_mod.load_storage_state.assert_awaited_once_with("u1", None)


async def test_create_session_receives_the_loaded_storage_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)
    sentinel_state = {"cookies": ["loaded"]}
    monkeypatch.setattr(session_mod, "load_storage_state", AsyncMock(return_value=sentinel_state))

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    session_mod.host_client.create_session.assert_awaited_once_with(sentinel_state, _HOST)
    assert host is session_mod.host_client.create_session.return_value


async def test_session_fields_are_mapped_from_the_host_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map each BrowserHostSession field from the matching host attribute, not a swapped one, and derive the live-view URL from the session id."""
    _make_session_fakes(monkeypatch)
    host = MagicMock(
        session_id="sid-x",
        cdp_ws="ws://cdp-endpoint",  # NOSONAR
        live_ws="ws://live-endpoint",  # NOSONAR
    )
    monkeypatch.setattr(session_mod.host_client, "create_session", AsyncMock(return_value=host))
    live_view_calls: list[str] = []
    monkeypatch.setattr(
        session_mod,
        "live_view_url",
        lambda session_id: live_view_calls.append(session_id) or f"LV:{session_id}",
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as s:
        assert s.session_id == "sid-x"
        assert s.cdp_url == "ws://cdp-endpoint"
        assert s.live_view_url == "LV:sid-x"
        assert s.host_url == _HOST
        # A later handover protects this site's login by it.
        assert s.start_domain == "x"
    assert live_view_calls == ["sid-x"]


async def test_the_wide_event_names_the_session_this_request_created(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    assert {"browser": {"session_id": "s1", "operation": "create"}} in fake_log.set_calls


async def test_register_session_called_with_session_id_user_id_and_live_ws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="user-77", start_url="https://x"
    ):
        pass

    session_mod.register_session.assert_awaited_once_with(
        host.session_id, "user-77", live_ws=host.live_ws
    )


async def test_host_create_failure_skips_all_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the host never created a session, there is nothing to release — the finally block (register/delete/save/unregister) must not run at all."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod.host_client,
        "create_session",
        AsyncMock(side_effect=BrowserUnavailableError("host unreachable")),
    )

    with pytest.raises(BrowserUnavailableError, match="host unreachable"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the host create failure")

    session_mod.register_session.assert_not_awaited()
    session_mod.host_client.delete_session.assert_not_awaited()
    session_mod.save_storage_state.assert_not_awaited()
    session_mod.unregister_session.assert_not_awaited()


async def test_body_exception_propagates_and_release_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)

    with pytest.raises(ValueError, match="body boom"):
        async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
            raise ValueError("body boom")

    session_mod.host_client.delete_session.assert_awaited_once()
    session_mod.unregister_session.assert_awaited_once()


async def test_delete_session_called_with_this_sessions_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    session_mod.host_client.delete_session.assert_awaited_once_with(host.session_id, _HOST)


async def test_save_storage_state_called_with_user_domain_and_returned_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run seeded from a saved login writes the rotated state back."""
    _make_session_fakes(monkeypatch)
    returned_state = _login_on("foo.example.com", "returned")
    monkeypatch.setattr(
        session_mod, "load_storage_state", AsyncMock(return_value={"cookies": ["seeded"]})
    )
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u42", start_url="https://foo.example.com/x"
    ):
        pass

    session_mod.save_storage_state.assert_awaited_once_with(
        "u42", "foo.example.com", returned_state
    )


async def test_a_run_that_never_signed_in_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a wikipedia.org language cookie was kept as a saved login and answered the next task in German."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://www.wikipedia.org"
    ):
        pass

    session_mod.save_storage_state.assert_not_awaited()


async def test_a_saved_login_the_site_asks_to_sign_in_over_again_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod, "load_storage_state", AsyncMock(return_value={"cookies": ["seeded"]})
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://foo.example.com/x"
    ) as session:
        session.forget_login("https://foo.example.com/login")

    session_mod.save_storage_state.assert_not_awaited()


async def test_a_run_whose_login_takeover_completed_saves_its_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    returned_state = _login_on("x.com", "signed-in")
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as session:
        session.mark_authenticated("https://x.com/home")

    session_mod.save_storage_state.assert_awaited_once_with("u1", "x.com", returned_state)


async def test_a_sign_in_is_saved_for_the_site_it_happened_on_whatever_the_run_started_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a login was keyed on the start URL's domain, so a run with none saved nothing."""
    _make_session_fakes(monkeypatch)
    returned_state = _login_on("the-internet.herokuapp.com", "signed-in")
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )

    async with session_mod.browser_session(host_url=_HOST, user_id="u1") as session:
        session.mark_authenticated("https://the-internet.herokuapp.com/secure")

    session_mod.save_storage_state.assert_awaited_once_with(
        "u1", "the-internet.herokuapp.com", returned_state
    )


#: The primary's live browser after the user signed in on flights.example.com.
_CARRIED_STATE = {
    "cookies": [
        {"name": "session", "value": "signed-in", "domain": "flights.example.com", "path": "/"}
    ],
    "origins": [
        {"origin": "https://flights.example.com", "localStorage": [{"name": "t", "value": "live"}]}
    ],
}
#: The user's saved login for news.example.com, holding an older flights cookie too.
_SAVED_NEWS_LOGIN = {
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
    monkeypatch: pytest.MonkeyPatch,
    *,
    fallback_error: Exception | None = None,
    fallback_release_error: Exception | None = None,
) -> None:
    """Open "primary" then "fallback"; each disposes to a state naming it, so a save shows whose it was."""
    _make_session_fakes(monkeypatch)
    opened = iter(["primary", "fallback"])

    async def _create(storage_state: Any, host_url: str) -> MagicMock:
        session_id = next(opened)
        if session_id == "fallback" and fallback_error is not None:
            raise fallback_error
        return MagicMock(session_id=session_id, context_id="c", cdp_ws="ws://c", live_ws="ws://l")

    async def _delete(session_id: str, host_url: str) -> dict[str, Any]:
        if session_id == "fallback" and fallback_release_error is not None:
            raise fallback_release_error
        return _login_on("x.com", session_id)

    monkeypatch.setattr(session_mod.host_client, "create_session", AsyncMock(side_effect=_create))
    monkeypatch.setattr(session_mod.host_client, "delete_session", AsyncMock(side_effect=_delete))
    monkeypatch.setattr(
        session_mod.host_client, "get_storage_state", AsyncMock(return_value=_CARRIED_STATE)
    )


async def test_a_session_opened_with_carried_state_saves_the_login_under_the_site_it_belongs_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    returned_state = _login_on("flights.example.com", "still signed in")
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )
    carried = session_mod.LiveSessionState(
        storage_state=_CARRIED_STATE, source=_signed_in_primary()
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://cdn.example.net/page", carried=carried
    ):
        pass

    session_mod.host_client.create_session.assert_awaited_once_with(_CARRIED_STATE, _HOST)
    # Saved where the login belongs, not under the page the run moved over on.
    session_mod.save_storage_state.assert_awaited_once_with(
        "u1", "flights.example.com", returned_state
    )


async def test_carried_state_the_user_never_approved_as_a_login_is_never_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    carried = session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=_handle())

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com", carried=carried
    ):
        pass

    session_mod.save_storage_state.assert_not_awaited()


async def test_a_session_opened_with_carried_state_is_also_signed_in_to_the_site_it_resumes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Carrying the primary's state stopped the fallback loading the saved login for the page it resumes on; the live cookies still win."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod, "load_storage_state", AsyncMock(return_value=_SAVED_NEWS_LOGIN)
    )
    carried = session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=_handle())

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://news.example.com/a", carried=carried
    ):
        pass

    session_mod.load_storage_state.assert_awaited_once_with("u1", "news.example.com")
    [(seeded, _)] = [call.args for call in session_mod.host_client.create_session.await_args_list]
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
) -> None:
    """Regression (Greptile on #876): the whole returned state was saved under every login site, so each record held the other's cookies."""
    _make_session_fakes(monkeypatch)
    returned_state = {
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
    monkeypatch.setattr(
        session_mod, "load_storage_state", AsyncMock(return_value=_SAVED_NEWS_LOGIN)
    )
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )
    carried = session_mod.LiveSessionState(
        storage_state=_CARRIED_STATE, source=_signed_in_primary()
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://news.example.com/a", carried=carried
    ):
        pass

    saved = {call.args[1]: call.args[2] for call in session_mod.save_storage_state.await_args_list}
    cookies, origins = returned_state["cookies"], returned_state["origins"]
    assert saved == {
        "flights.example.com": {"cookies": [cookies[0], cookies[2]], "origins": [origins[0]]},
        "news.example.com": {"cookies": [cookies[1], cookies[2]], "origins": [origins[1]]},
    }


#: The user's saved login for flights.example.com, from before the run signed out.
_SAVED_FLIGHTS_LOGIN = {
    "cookies": [
        {"name": "session", "value": "stale", "domain": "flights.example.com", "path": "/"},
        {"name": "sso", "value": "stale", "domain": ".example.com", "path": "/"},
    ],
    "origins": [
        {"origin": "https://flights.example.com", "localStorage": [{"name": "t", "value": "old"}]}
    ],
}


async def _seeded_fallback(
    monkeypatch: pytest.MonkeyPatch, carried: session_mod.LiveSessionState
) -> dict[str, Any]:
    """Open a fallback on flights.example.com over the saved flights login; return what it was seeded with."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod, "load_storage_state", AsyncMock(return_value=_SAVED_FLIGHTS_LOGIN)
    )
    async with session_mod.browser_session(
        host_url=_FALLBACK_HOST,
        user_id="u1",
        start_url="https://flights.example.com/",
        carried=carried,
    ):
        pass
    [(seeded, _)] = [call.args for call in session_mod.host_client.create_session.await_args_list]
    return seeded


async def test_a_sign_out_on_the_primary_is_not_undone_by_the_saved_login_on_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Greptile on #876): a logout cleared the site's cookies, and the overlay seeded the saved copies back into the fallback."""
    carried = session_mod.LiveSessionState(
        storage_state={"cookies": [], "origins": []}, source=_signed_in_primary()
    )

    seeded = await _seeded_fallback(monkeypatch, carried)

    assert seeded == {"cookies": [], "origins": []}


async def test_a_cookie_the_primary_deleted_stays_deleted_on_a_site_it_still_holds_cookies_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The carried state is the whole truth for a site it has cookies for, not an update to lay over the saved login."""
    after_logout = {
        "cookies": [{"name": "lang", "value": "en", "domain": "flights.example.com", "path": "/"}],
        "origins": [],
    }
    carried = session_mod.LiveSessionState(storage_state=after_logout, source=_handle())

    seeded = await _seeded_fallback(monkeypatch, carried)

    assert seeded == after_logout


async def test_handing_over_a_live_session_reads_its_state_and_names_it_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        session_mod.host_client, "get_storage_state", AsyncMock(return_value=_CARRIED_STATE)
    )
    primary = _signed_in_primary()

    state = await session_mod.hand_over_state(primary)

    session_mod.host_client.get_storage_state.assert_awaited_once_with("primary", _HOST)
    assert state == session_mod.LiveSessionState(storage_state=_CARRIED_STATE, source=primary)


async def test_handing_over_a_session_whose_engine_is_gone_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read used to swallow the failure and return None; the caller decides what a run without the state does."""
    monkeypatch.setattr(
        session_mod.host_client,
        "get_storage_state",
        AsyncMock(side_effect=BrowserSessionGone("Browser host returned 404")),
    )

    with pytest.raises(BrowserSessionGone):
        await session_mod.hand_over_state(_signed_in_primary())


async def test_a_login_carried_to_the_fallback_is_saved_once_from_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary is released after the fallback; saving from both wrote its older cookies over the fallback's."""
    _host_per_session(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as primary:
        primary.mark_authenticated("https://x.com/home")
        carried = await session_mod.hand_over_state(primary)
        async with session_mod.browser_session(
            host_url=_FALLBACK_HOST, user_id="u1", start_url="https://x.com/feed", carried=carried
        ):
            pass

    session_mod.save_storage_state.assert_awaited_once_with(
        "u1", "x.com", _login_on("x.com", "fallback")
    )


async def test_a_login_is_saved_from_the_primary_when_the_fallback_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handover cleared the primary's right to save before the fallback existed, so a full fallback host lost the login."""
    _host_per_session(monkeypatch, fallback_error=BrowserConcurrencyLimit("at capacity"))

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

    session_mod.save_storage_state.assert_awaited_once_with(
        "u1", "x.com", _login_on("x.com", "primary")
    )


@pytest.mark.regression
async def test_a_sign_in_asked_for_again_after_the_switch_is_saved_by_neither_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the fallback forgot the login it was asked to redo, and the primary, released later, saved it anyway."""
    _host_per_session(monkeypatch)

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x.com"
    ) as primary:
        primary.mark_authenticated("https://x.com/home")
        carried = await session_mod.hand_over_state(primary)
        async with session_mod.browser_session(
            host_url=_FALLBACK_HOST, user_id="u1", start_url="https://x.com/feed", carried=carried
        ) as fallback:
            fallback.forget_login("https://x.com/login")

    session_mod.save_storage_state.assert_not_awaited()


async def test_release_failure_is_caught_logged_and_unregister_still_runs(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    """A release-time failure must not propagate out of the context manager (the body's own outcome should not be masked by a cleanup error), must be logged with the actual exception type, and unregister must still run."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod.host_client,
        "delete_session",
        AsyncMock(side_effect=RuntimeError("host down")),
    )

    async with session_mod.browser_session(host_url=_HOST, user_id="u1", start_url="https://x"):
        pass

    session_mod.save_storage_state.assert_not_awaited()
    session_mod.unregister_session.assert_awaited_once()
    assert len(fake_log.warning_calls) == 1
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] Failed to release browser session"
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["browser"] == {"session_id": "s1", "operation": "release_failed"}


async def test_save_storage_state_failure_is_also_caught(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod, "save_storage_state", AsyncMock(side_effect=ValueError("disk full"))
    )

    async with session_mod.browser_session(
        host_url=_HOST, user_id="u1", start_url="https://x"
    ) as session:
        session.mark_authenticated("https://x.com/home")

    session_mod.unregister_session.assert_awaited_once()
    assert len(fake_log.warning_calls) == 1
    _, kwargs = fake_log.warning_calls[0]
    assert kwargs["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# keep_session_alive — the handoff idle-clock keepalive
# ---------------------------------------------------------------------------


async def test_keep_session_alive_touches_the_session_each_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused handoff session gets no CDP/live-view traffic, so this loop is the only thing resetting the host's idle clock — it must actually touch every iteration, not just the first."""
    sleep_mock = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(session_mod.asyncio, "sleep", sleep_mock)
    touch = AsyncMock()
    monkeypatch.setattr(session_mod.host_client, "touch_session", touch)

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive(_handle("sess-1"))

    assert touch.await_count == 2
    touch.assert_awaited_with("sess-1", _HOST)


async def test_keep_session_alive_waits_the_configured_keepalive_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interval is the whole point: it has to stay under the host's idle TTL, so a hardcoded or dropped delay silently lets the reaper win the race."""
    sleep_mock = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(session_mod.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(session_mod.host_client, "touch_session", AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive(_handle("sess-1"))

    sleep_mock.assert_awaited_with(session_mod.BROWSER_HANDOFF_KEEPALIVE_SECONDS)


async def test_keep_session_alive_logs_a_failed_touch_and_keeps_looping(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    """A single failed touch must not break the loop -- the next iteration still tries again, since the alternative is the host reaping the browser mid-handoff."""
    sleep_mock = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(session_mod.asyncio, "sleep", sleep_mock)
    touch = AsyncMock(side_effect=[BrowserUnavailableError("host down"), None])
    monkeypatch.setattr(session_mod.host_client, "touch_session", touch)

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive(_handle("sess-1"))

    assert touch.await_count == 2
    assert len(fake_log.warning_calls) == 1
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] Browser handoff keepalive failed"
    assert kwargs["error_type"] == "BrowserUnavailableError"
    assert kwargs["browser"] == {"session_id": "sess-1", "operation": "handoff_keepalive"}


@pytest.mark.unit
class TestEngineFailure:
    async def test_the_probe_asks_about_this_session_and_gives_up_quickly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wedged engine is what the probe detects; an unbounded read would wedge with it."""
        get = AsyncMock(return_value=MagicMock(live=True))
        monkeypatch.setattr(session_mod.host_client, "get_session", get)

        assert await session_mod.engine_failure(_handle("sess-9")) is None

        get.assert_awaited_once_with(
            "sess-9", _HOST, timeout=session_mod.BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS
        )
