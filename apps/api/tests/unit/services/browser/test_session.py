"""Tests for browser_session lifecycle — including the registry-write gate."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser import session as session_mod
from app.services.browser.exceptions import BrowserUnavailableError


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


def _make_session_fakes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    host = MagicMock(
        session_id="s1",
        context_id="ctx-1",
        cdp_ws="ws://x",  # NOSONAR
        live_ws="ws://live",  # NOSONAR
    )
    monkeypatch.setattr(session_mod.host_client, "create_session", AsyncMock(return_value=host))
    monkeypatch.setattr(session_mod.host_client, "delete_session", AsyncMock())
    monkeypatch.setattr(session_mod, "load_storage_state", AsyncMock(return_value=None))
    monkeypatch.setattr(session_mod, "save_storage_state", AsyncMock())
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=True))
    monkeypatch.setattr(session_mod, "unregister_session", AsyncMock())
    return host


async def test_registry_write_failure_aborts_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed ownership write must fail the session (releasing the host context)
    instead of handing the user a live-view link that can never authorize."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=False))

    with pytest.raises(BrowserUnavailableError, match="register"):
        async with session_mod.browser_session(user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the failed registration")

    # The host context was still released on the way out — never orphaned.
    session_mod.host_client.delete_session.assert_awaited()
    session_mod.unregister_session.assert_awaited()


async def test_registry_write_success_yields_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: registration succeeds, the session yields, and release runs."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u1", start_url="https://x") as s:
        assert s.session_id == "s1"
    session_mod.host_client.delete_session.assert_awaited_once()
    # With the id, not merely "was called": deregistering the wrong session (or
    # None) leaves this one's ownership entry behind, and the reaper then never
    # collects it.
    session_mod.unregister_session.assert_awaited_once_with("s1")


async def test_registration_failure_message_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=False))

    with pytest.raises(BrowserUnavailableError) as exc_info:
        async with session_mod.browser_session(user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the failed registration")

    assert str(exc_info.value) == "Could not register the browser session (storage unavailable)."


async def test_domain_derived_from_start_url_feeds_storage_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``domain_of(start_url)`` — not ``start_url`` itself — is what gets looked up."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u42", start_url="https://Example.com/page"):
        pass

    session_mod.load_storage_state.assert_awaited_once_with("u42", "example.com")


async def test_none_start_url_looks_up_with_none_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u1", start_url=None):
        pass

    session_mod.load_storage_state.assert_awaited_once_with("u1", None)


async def test_create_session_receives_the_loaded_storage_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)
    sentinel_state = {"cookies": ["loaded"]}
    monkeypatch.setattr(session_mod, "load_storage_state", AsyncMock(return_value=sentinel_state))

    async with session_mod.browser_session(user_id="u1", start_url="https://x"):
        pass

    session_mod.host_client.create_session.assert_awaited_once_with(sentinel_state)
    assert host is session_mod.host_client.create_session.return_value


async def test_session_fields_are_mapped_from_the_host_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each ``BrowserHostSession`` field must come from the matching host attribute —
    not a swapped one — and the live-view URL is derived from the session id."""
    _make_session_fakes(monkeypatch)
    host = MagicMock(
        session_id="sid-x",
        context_id="ctx-y",
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

    async with session_mod.browser_session(user_id="u1", start_url="https://x") as s:
        assert s.session_id == "sid-x"
        assert s.cdp_url == "ws://cdp-endpoint"
        assert s.context_id == "ctx-y"
        assert s.live_view_url == "LV:sid-x"
    assert live_view_calls == ["sid-x"]


async def test_register_session_called_with_session_id_user_id_and_live_ws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="user-77", start_url="https://x"):
        pass

    session_mod.register_session.assert_awaited_once_with(
        host.session_id, "user-77", live_ws=host.live_ws
    )


async def test_host_create_failure_skips_all_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the host never created a session, there is nothing to release — the
    finally block (register/delete/save/unregister) must not run at all."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod.host_client,
        "create_session",
        AsyncMock(side_effect=BrowserUnavailableError("host unreachable")),
    )

    with pytest.raises(BrowserUnavailableError, match="host unreachable"):
        async with session_mod.browser_session(user_id="u1", start_url="https://x"):
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
        async with session_mod.browser_session(user_id="u1", start_url="https://x"):
            raise ValueError("body boom")

    session_mod.host_client.delete_session.assert_awaited_once()
    session_mod.unregister_session.assert_awaited_once()


async def test_delete_session_called_with_this_sessions_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u1", start_url="https://x"):
        pass

    session_mod.host_client.delete_session.assert_awaited_once_with(host.session_id)


async def test_save_storage_state_called_with_user_domain_and_returned_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_session_fakes(monkeypatch)
    returned_state = {"cookies": ["returned"]}
    monkeypatch.setattr(
        session_mod.host_client, "delete_session", AsyncMock(return_value=returned_state)
    )

    async with session_mod.browser_session(user_id="u42", start_url="https://foo.example.com/x"):
        pass

    session_mod.save_storage_state.assert_awaited_once_with(
        "u42", "foo.example.com", returned_state
    )


async def test_release_failure_is_caught_logged_and_unregister_still_runs(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    """A release-time failure must not propagate out of the context manager (the
    body's own outcome should not be masked by a cleanup error), must be logged
    with the actual exception type, and unregister must still run."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(
        session_mod.host_client,
        "delete_session",
        AsyncMock(side_effect=RuntimeError("host down")),
    )

    async with session_mod.browser_session(user_id="u1", start_url="https://x"):
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

    async with session_mod.browser_session(user_id="u1", start_url="https://x"):
        pass

    session_mod.unregister_session.assert_awaited_once()
    assert len(fake_log.warning_calls) == 1
    _, kwargs = fake_log.warning_calls[0]
    assert kwargs["error_type"] == "ValueError"


async def test_log_set_and_info_calls_on_create_and_release(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u1", start_url="https://x"):
        pass

    assert {"browser": {"session_id": "s1", "operation": "create"}} in fake_log.set_calls
    messages = [message for message, _ in fake_log.info_calls]
    assert "[BROWSER] Browser session created" in messages
    assert "[BROWSER] Browser session released" in messages


# ---------------------------------------------------------------------------
# keep_session_alive — the handoff idle-clock keepalive
# ---------------------------------------------------------------------------


async def test_keep_session_alive_touches_the_session_each_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused handoff session gets no CDP/live-view traffic, so this loop is the
    only thing resetting the host's idle clock — it must actually touch every
    iteration, not just the first."""
    sleep_mock = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(session_mod.asyncio, "sleep", sleep_mock)
    touch = AsyncMock()
    monkeypatch.setattr(session_mod.host_client, "touch_session", touch)

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive("sess-1")

    assert touch.await_count == 2
    touch.assert_awaited_with("sess-1")


async def test_keep_session_alive_logs_a_failed_touch_and_keeps_looping(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    """A single failed touch must not break the loop -- the next iteration still
    tries again, since the alternative is the host reaping the browser mid-handoff."""
    sleep_mock = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(session_mod.asyncio, "sleep", sleep_mock)
    touch = AsyncMock(side_effect=[BrowserUnavailableError("host down"), None])
    monkeypatch.setattr(session_mod.host_client, "touch_session", touch)

    with pytest.raises(asyncio.CancelledError):
        await session_mod.keep_session_alive("sess-1")

    assert touch.await_count == 2
    assert len(fake_log.warning_calls) == 1
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] Browser handoff keepalive failed"
    assert kwargs["error_type"] == "BrowserUnavailableError"
    assert kwargs["browser"] == {"session_id": "sess-1", "operation": "handoff_keepalive"}


def _info(url: str | None) -> MagicMock:
    return MagicMock(url=url)


@pytest.mark.unit
class TestNavigatedAway:
    def test_true_when_it_lands_on_a_non_auth_page(self) -> None:
        assert session_mod._navigated_away("https://x.com/login", "https://x.com/home")
        assert session_mod._navigated_away("https://x.com/login", "https://x.com/")

    @pytest.mark.parametrize(
        "current",
        [
            "https://x.com/sessions/two-factor",
            "https://x.com/login/otp",
            "https://x.com/verify",
            "https://x.com/challenge/mfa",
            "https://y.com/signin",
        ],
    )
    def test_false_while_still_inside_the_auth_flow(self, current: str) -> None:
        """A login walks /login -> /two-factor -> /verify. Treating each hop as
        'signed in' woke the agent mid-2FA, which then handed off again — the user
        got interrupted twice and a model call was burned each time."""
        assert not session_mod._navigated_away("https://x.com/login", current)

    def test_false_for_same_page_ignoring_query(self) -> None:
        # A login flow adding ?return_to= on the same page is not a navigation.
        assert not session_mod._navigated_away(
            "https://x.com/login", "https://x.com/login?return_to=%2Fhome"
        )

    def test_false_when_either_url_missing(self) -> None:
        assert not session_mod._navigated_away(None, "https://x.com/home")
        assert not session_mod._navigated_away("https://x.com/login", None)


@pytest.mark.unit
class TestAutoResolveHandoffOnNavigation:
    async def test_resolves_after_navigating_away_and_staying(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A visible sign-in (URL leaves the login page for 2 stable polls) auto
        -completes the handoff via the same resolve_handoff the button uses."""
        monkeypatch.setattr(session_mod.asyncio, "sleep", AsyncMock())
        # start=login, then post-login twice (debounce needs 2 stable polls).
        monkeypatch.setattr(
            session_mod.host_client,
            "get_session",
            AsyncMock(side_effect=[_info("https://x/login"), _info("https://x/"), _info("https://x/")]),
        )
        resolve = AsyncMock()
        monkeypatch.setattr(session_mod, "resolve_handoff", resolve)

        await session_mod.auto_resolve_handoff_on_navigation("h1", "sess-1", "user-1")

        resolve.assert_awaited_once()
        args = resolve.await_args[0]
        assert args[0] == "h1"
        assert args[1] == session_mod.HandoffDecision.CONTINUE
        assert args[2] == "user-1"

    async def test_does_not_resolve_while_still_on_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(session_mod.asyncio, "sleep", AsyncMock())
        # never leaves the login page, then the session drops → loop exits.
        monkeypatch.setattr(
            session_mod.host_client,
            "get_session",
            AsyncMock(
                side_effect=[
                    _info("https://x/login"),
                    _info("https://x/login"),
                    BrowserUnavailableError("gone"),
                ]
            ),
        )
        resolve = AsyncMock()
        monkeypatch.setattr(session_mod, "resolve_handoff", resolve)

        await session_mod.auto_resolve_handoff_on_navigation("h1", "sess-1", "user-1")
        resolve.assert_not_awaited()

    async def test_transient_redirect_is_debounced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single off-login blip that snaps back must NOT resolve — the stable
        counter resets, so a mid-login redirect can't complete the handoff early."""
        monkeypatch.setattr(session_mod.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(
            session_mod.host_client,
            "get_session",
            AsyncMock(
                side_effect=[
                    _info("https://x/login"),
                    _info("https://x/interstitial"),  # blip (stable=1)
                    _info("https://x/login"),  # back → reset
                    _info("https://x/login"),
                    BrowserUnavailableError("gone"),
                ]
            ),
        )
        resolve = AsyncMock()
        monkeypatch.setattr(session_mod, "resolve_handoff", resolve)

        await session_mod.auto_resolve_handoff_on_navigation("h1", "sess-1", "user-1")
        resolve.assert_not_awaited()
