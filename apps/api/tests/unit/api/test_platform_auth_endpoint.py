"""Unit tests for the platform OAuth endpoints (app/api/v1/endpoints/platform_auth.py).

Covers the Discord/Slack OAuth callback success path and its analytics capture.
"""

from typing import ClassVar
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.platform_models import PlatformLinkCompletion, PlatformLinkResult
from app.utils.errors import create_error

_MODULE = "app.api.v1.endpoints.platform_auth"
BASE = "/api/v1/platform-auth"


class _FakeTokenResponse:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"access_token": "tok_abc"}


class _FakeUserInfoResponse:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"id": "DISC1", "username": "user", "global_name": "User"}


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient covering the token + user-info calls."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def post(self, *args: object, **kwargs: object) -> _FakeTokenResponse:
        return _FakeTokenResponse()

    async def get(self, *args: object, **kwargs: object) -> _FakeUserInfoResponse:
        return _FakeUserInfoResponse()


class TestPlatformOAuthCallback:
    """GET /api/v1/platform-auth/{platform}/callback"""

    async def test_discord_callback_captures_connected_event(self, client: AsyncClient) -> None:
        completion = PlatformLinkCompletion(
            link=PlatformLinkResult(
                status="linked",
                platform="discord",
                platform_user_id="DISC1",
                connected_at="2024-01-01T00:00:00Z",
                is_new_link=True,
            ),
            first_contact_delivered=True,
        )
        with (
            patch(
                "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
                new_callable=AsyncMock,
                return_value={"user_id": "uid1", "redirect_path": "/settings"},
            ) as mock_validate,
            patch(f"{_MODULE}.httpx.AsyncClient", new=_FakeAsyncClient),
            patch(
                f"{_MODULE}.complete_platform_link",
                new_callable=AsyncMock,
                return_value=completion,
            ) as mock_complete,
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "s1"},
                follow_redirects=False,
            )

        # The signed state param must reach validation verbatim — a mutated
        # call that drops or replaces the argument would silently accept
        # forged callbacks.
        mock_validate.assert_called_once_with("s1")
        assert resp.status_code in (302, 307)
        assert "oauth_success=true" in resp.headers["location"]
        # Explicit user id, not the request context: the platform OAuth
        # redirect carries no WorkOS session, so a context capture would land
        # the link on an anonymous profile.
        # One implementation of the link's follow-through (greeting, account
        # sync, analytics) for every route that creates a link: this one used
        # to inline three of the four and skip the sync.
        mock_complete.assert_awaited_once()
        assert mock_complete.await_args.args == ("uid1", "discord", "DISC1")

    async def test_a_link_owned_by_another_account_redirects_with_already_linked(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
                new_callable=AsyncMock,
                return_value={"user_id": "uid1", "redirect_path": "/settings"},
            ),
            patch(f"{_MODULE}.httpx.AsyncClient", new=_FakeAsyncClient),
            patch(
                f"{_MODULE}.complete_platform_link",
                new_callable=AsyncMock,
                side_effect=create_error(
                    message="already linked", why="other account", fix="unlink", status_code=409
                ),
            ),
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "s1"},
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "oauth_error=already_linked" in resp.headers["location"]

    async def test_callback_invalid_state_redirects_with_error(self, client: AsyncClient) -> None:
        """A consumed/invalid state token must bounce to the UI error path."""
        with patch(
            "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "bad"},
                follow_redirects=False,
            )
        assert resp.status_code in (302, 307)
        assert "oauth_error=invalid_state" in resp.headers["location"]

    async def test_callback_missing_params_redirects_with_error(self, client: AsyncClient) -> None:
        """Missing code/state must bounce before any provider call is made."""
        resp = await client.get(f"{BASE}/discord/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "oauth_error=missing_params" in resp.headers["location"]


class _RecordingClient(_FakeAsyncClient):
    """Records the provider calls so the wire shape can be asserted exactly."""

    posts: ClassVar[list[tuple[tuple[object, ...], dict[str, object]]]] = []
    token_response: ClassVar[object] = _FakeTokenResponse()

    async def post(self, *args: object, **kwargs: object) -> object:
        _RecordingClient.posts.append((args, kwargs))
        return _RecordingClient.token_response


class _FailedTokenResponse:
    status_code = 400
    text = "invalid_grant"

    @staticmethod
    def json() -> dict:
        return {}


class _SlackRefusedTokenResponse:
    status_code = 200
    text = "ok false"

    @staticmethod
    def json() -> dict:
        return {"ok": False, "error": "invalid_code"}


class TestExchangeCode:
    """The token exchange is the one call whose exact wire shape the provider checks."""

    def setup_method(self) -> None:
        _RecordingClient.posts = []
        _RecordingClient.token_response = _FakeTokenResponse()

    async def test_posts_the_authorization_code_grant_to_the_token_url(self) -> None:
        from app.api.v1.endpoints.platform_auth import PLATFORM_CONFIGS, _exchange_code

        config = PLATFORM_CONFIGS["discord"]
        with (
            patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingClient),
            patch(f"{_MODULE}.settings") as settings,
        ):
            settings.DISCORD_OAUTH_CLIENT_ID = "cid"
            settings.DISCORD_OAUTH_CLIENT_SECRET = "csecret"
            settings.DISCORD_OAUTH_REDIRECT_URI = "https://api.test/cb"
            token_data = await _exchange_code(config, "c1")

        assert token_data == {"access_token": "tok_abc"}
        assert _RecordingClient.posts == [
            (
                ("https://discord.com/api/oauth2/token",),
                {
                    "data": {
                        "client_id": "cid",
                        "client_secret": "csecret",
                        "code": "c1",
                        "redirect_uri": "https://api.test/cb",
                        "grant_type": "authorization_code",
                    },
                    "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                },
            )
        ]

    async def test_a_refused_exchange_is_logged_with_the_providers_answer(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _exchange_code,
        )

        _RecordingClient.token_response = _FailedTokenResponse()
        with (
            patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingClient),
            patch(f"{_MODULE}.log") as log,
            pytest.raises(_CallbackRefused) as refused,
        ):
            await _exchange_code(PLATFORM_CONFIGS["discord"], "c1")

        assert refused.value.oauth_error == "token_failed"
        assert str(refused.value) == "token_failed"
        log.error.assert_called_once_with(
            "[API] Platform token exchange failed",
            platform="discord",
            status_code=400,
            error="invalid_grant",
        )

    async def test_slack_saying_ok_false_is_a_refused_exchange(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _exchange_code,
        )

        _RecordingClient.token_response = _SlackRefusedTokenResponse()
        with (
            patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingClient),
            pytest.raises(_CallbackRefused) as refused,
        ):
            await _exchange_code(PLATFORM_CONFIGS["slack"], "c1")

        assert refused.value.oauth_error == "token_failed"


class TestDiscordStyleProfile:
    def test_prefers_the_global_name_for_display(self) -> None:
        from app.api.v1.endpoints.platform_auth import _discord_style_profile

        assert _discord_style_profile({"username": "u", "global_name": "G"}) == {
            "username": "u",
            "display_name": "G",
        }

    def test_falls_back_to_the_username_when_there_is_no_global_name(self) -> None:
        from app.api.v1.endpoints.platform_auth import _discord_style_profile

        assert _discord_style_profile({"username": "u"}) == {
            "username": "u",
            "display_name": "u",
        }


class TestBounce:
    async def test_every_redirect_lands_on_the_frontend(self, client: AsyncClient) -> None:
        from app.config.settings import settings

        resp = await client.get(f"{BASE}/discord/callback", follow_redirects=False)

        assert resp.headers["location"].startswith(settings.FRONTEND_URL)


class _SlackOkTokenResponse:
    status_code = 200
    text = "ok"

    @staticmethod
    def json() -> dict:
        return {"ok": True, "authed_user": {"id": "SLACK1", "access_token": "xoxp-1"}}


class _FailedUserInfoResponse:
    status_code = 403
    text = "forbidden"

    @staticmethod
    def json() -> dict:
        return {}


class _NoIdUserInfoResponse:
    status_code = 200
    text = "no id"

    @staticmethod
    def json() -> dict:
        return {"name": "n"}


class _RecordingGetClient(_FakeAsyncClient):
    """Records the user-info GET so its exact wire shape can be asserted."""

    gets: ClassVar[list[tuple[tuple[object, ...], dict[str, object]]]] = []
    user_response: ClassVar[object] = _FakeUserInfoResponse()

    async def get(self, *args: object, **kwargs: object) -> object:
        _RecordingGetClient.gets.append((args, kwargs))
        return _RecordingGetClient.user_response


class _RecordingExtractor:
    """An ``extract_user_id`` that records exactly how it was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> str:
        self.calls.append((args, kwargs))
        return "UID_FROM_TOKEN"


def _config_with(extractor: _RecordingExtractor, *, user_info_url: str | None):
    from app.api.v1.endpoints.platform_auth import PlatformOAuthConfig

    return PlatformOAuthConfig(
        platform="fake",
        token_url="https://fake.test/token",  # nosec B106 - test URL, not a password
        get_client_id=lambda: "cid",
        get_client_secret=lambda: "csecret",
        get_redirect_uri=lambda: "https://api.test/cb",
        extract_user_id=extractor,
        user_info_url=user_info_url,
        get_user_access_token=lambda _data: "tokX",
        extract_profile_from_user_info=lambda user_data: {"username": user_data.get("name")},
    )


class TestExchangeCodeSlackEnvelope:
    """Slack answers 200 with an ``ok`` flag; the flag, not the status, decides."""

    def setup_method(self) -> None:
        _RecordingClient.posts = []
        _RecordingClient.token_response = _FakeTokenResponse()

    async def test_slack_saying_ok_true_is_accepted(self) -> None:
        from app.api.v1.endpoints.platform_auth import PLATFORM_CONFIGS, _exchange_code

        _RecordingClient.token_response = _SlackOkTokenResponse()
        with patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingClient):
            token_data = await _exchange_code(PLATFORM_CONFIGS["slack"], "c1")

        # Reading any key other than "ok" would find nothing here and refuse a
        # perfectly good exchange.
        assert token_data == {"ok": True, "authed_user": {"id": "SLACK1", "access_token": "xoxp-1"}}

    async def test_slack_ok_false_is_logged_with_the_providers_error_code(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _exchange_code,
        )

        _RecordingClient.token_response = _SlackRefusedTokenResponse()
        with (
            patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingClient),
            patch(f"{_MODULE}.log") as log,
            pytest.raises(_CallbackRefused),
        ):
            await _exchange_code(PLATFORM_CONFIGS["slack"], "c1")

        log.error.assert_called_once_with("[API] Slack OAuth failed", error="invalid_code")


class TestResolvePlatformUser:
    """The user id/profile resolution and the exact user-info call it makes."""

    def setup_method(self) -> None:
        _RecordingGetClient.gets = []
        _RecordingGetClient.user_response = _FakeUserInfoResponse()

    async def test_without_a_user_info_url_the_id_comes_from_the_token_response(self) -> None:
        from app.api.v1.endpoints.platform_auth import _resolve_platform_user

        extractor = _RecordingExtractor()
        config = _config_with(extractor, user_info_url=None)
        token_data = {"access_token": "tokX"}
        with patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingGetClient):
            resolved = await _resolve_platform_user(config, token_data)

        assert resolved == ("UID_FROM_TOKEN", {})
        # Both the payload and the access token, in that order — the extractor
        # is the only thing that knows where a platform hides its user id.
        assert extractor.calls == [((token_data, "tokX"), {})]
        # No user-info URL means no user-info call.
        assert _RecordingGetClient.gets == []

    async def test_user_info_is_fetched_as_a_bearer_token_for_that_access_token(self) -> None:
        from app.api.v1.endpoints.platform_auth import PLATFORM_CONFIGS, _resolve_platform_user

        with patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingGetClient):
            resolved = await _resolve_platform_user(
                PLATFORM_CONFIGS["discord"], {"access_token": "tok_abc"}
            )

        assert _RecordingGetClient.gets == [
            (
                ("https://discord.com/api/users/@me",),
                {"headers": {"Authorization": "Bearer tok_abc"}},
            )
        ]
        assert resolved == ("DISC1", {"username": "user", "display_name": "User"})

    async def test_a_refused_user_info_call_is_logged_with_the_providers_answer(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _resolve_platform_user,
        )

        _RecordingGetClient.user_response = _FailedUserInfoResponse()
        with (
            patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingGetClient),
            patch(f"{_MODULE}.log") as log,
            pytest.raises(_CallbackRefused) as refused,
        ):
            await _resolve_platform_user(PLATFORM_CONFIGS["discord"], {"access_token": "tok_abc"})

        assert refused.value.oauth_error == "user_fetch_failed"
        log.error.assert_called_once_with(
            "[API] Platform user fetch failed",
            platform="discord",
            status_code=403,
            error="forbidden",
        )

    async def test_a_user_info_payload_without_an_id_falls_back_to_the_token_response(self) -> None:
        from app.api.v1.endpoints.platform_auth import _resolve_platform_user

        extractor = _RecordingExtractor()
        config = _config_with(extractor, user_info_url="https://fake.test/me")
        token_data = {"access_token": "tokX"}
        _RecordingGetClient.user_response = _NoIdUserInfoResponse()
        with patch(f"{_MODULE}.httpx.AsyncClient", new=_RecordingGetClient):
            resolved = await _resolve_platform_user(config, token_data)

        assert resolved == ("UID_FROM_TOKEN", {"username": "n"})
        assert extractor.calls == [((token_data, "tokX"), {})]


class TestLinkPlatformAccount:
    """Linking passes the profile through and audits the outcome."""

    async def test_the_profile_reaches_the_link_and_the_new_link_is_audited(self) -> None:
        from app.api.v1.endpoints.platform_auth import PLATFORM_CONFIGS, _link_platform_account

        profile: dict[str, str | None] = {"username": "u", "display_name": "U"}
        completion = PlatformLinkCompletion(
            link=PlatformLinkResult(
                status="linked",
                platform="discord",
                platform_user_id="DISC1",
                connected_at="2024-01-01T00:00:00Z",
                is_new_link=True,
            ),
            first_contact_delivered=True,
        )
        with (
            patch(
                f"{_MODULE}.complete_platform_link",
                new_callable=AsyncMock,
                return_value=completion,
            ) as mock_complete,
            patch(f"{_MODULE}.log") as log,
        ):
            await _link_platform_account("uid1", PLATFORM_CONFIGS["discord"], "DISC1", profile)

        assert mock_complete.await_args.args == ("uid1", "discord", "DISC1")
        # The profile is what puts a username on the linked account; dropping
        # it or forcing it to None links a nameless stub.
        assert mock_complete.await_args.kwargs == {"profile": profile}
        log.audit.assert_called_once_with(
            "platform account linked",
            actor="uid1",
            resource="DISC1",
            provider="discord",
            is_new_link=True,
        )

    async def test_a_conflict_is_marked_already_linked_on_the_event(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _link_platform_account,
        )

        with (
            patch(
                f"{_MODULE}.complete_platform_link",
                new_callable=AsyncMock,
                side_effect=create_error(
                    message="already linked", why="other account", fix="unlink", status_code=409
                ),
            ),
            patch(f"{_MODULE}.log") as log,
            pytest.raises(_CallbackRefused) as refused,
        ):
            await _link_platform_account("uid1", PLATFORM_CONFIGS["discord"], "DISC1", {})

        assert refused.value.oauth_error == "already_linked"
        log.set.assert_called_once_with(outcome="already_linked")
        log.audit.assert_not_called()

    async def test_any_other_link_failure_is_logged_and_audited_with_the_error_type(self) -> None:
        from app.api.v1.endpoints.platform_auth import (
            PLATFORM_CONFIGS,
            _CallbackRefused,
            _link_platform_account,
        )

        boom = create_error(message="link broke", why="db down", fix="retry", status_code=500)
        with (
            patch(f"{_MODULE}.complete_platform_link", new_callable=AsyncMock, side_effect=boom),
            patch(f"{_MODULE}.log") as log,
            pytest.raises(_CallbackRefused) as refused,
        ):
            await _link_platform_account("uid1", PLATFORM_CONFIGS["discord"], "DISC1", {})

        assert refused.value.oauth_error == "failed"
        log.error.assert_called_once_with(
            "[API] Failed to link account",
            platform="discord",
            user_id="uid1",
            error_type=type(boom).__name__,
            error=str(boom),
        )
        log.audit.assert_called_once_with(
            "platform account link failed",
            actor="uid1",
            resource="DISC1",
            provider="discord",
            error_type=type(boom).__name__,
        )


def _frontend(path_and_query: str) -> str:
    from app.config.settings import settings

    return f"{settings.FRONTEND_URL}{path_and_query}"


_FALLBACK = "/settings?section=linked-accounts"


class TestCallbackRedirectTargets:
    """Every bounce lands on an exact URL — the query string is the contract with the UI."""

    async def test_a_cancelled_authorization_bounces_to_the_linked_accounts_page(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            f"{BASE}/discord/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        assert resp.headers["location"] == _frontend(f"{_FALLBACK}&oauth_error=cancelled")

    async def test_any_other_provider_error_bounces_as_a_plain_failure(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            f"{BASE}/discord/callback", params={"error": "server_error"}, follow_redirects=False
        )
        assert resp.headers["location"] == _frontend(f"{_FALLBACK}&oauth_error=failed")

    async def test_a_code_without_a_state_is_missing_params(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"{BASE}/discord/callback", params={"code": "c1"}, follow_redirects=False
        )
        assert resp.headers["location"] == _frontend(f"{_FALLBACK}&oauth_error=missing_params")

    async def test_an_invalid_state_bounces_to_the_linked_accounts_page(
        self, client: AsyncClient
    ) -> None:
        with patch(
            "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "bad"},
                follow_redirects=False,
            )
        assert resp.headers["location"] == _frontend(f"{_FALLBACK}&oauth_error=invalid_state")

    async def test_success_returns_to_the_stored_redirect_path_naming_the_integration(
        self, client: AsyncClient
    ) -> None:
        completion = PlatformLinkCompletion(
            link=PlatformLinkResult(
                status="linked",
                platform="discord",
                platform_user_id="DISC1",
                connected_at="2024-01-01T00:00:00Z",
                is_new_link=True,
            ),
            first_contact_delivered=True,
        )
        with (
            patch(
                "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
                new_callable=AsyncMock,
                return_value={"user_id": "uid1", "redirect_path": "/settings"},
            ),
            patch(f"{_MODULE}.httpx.AsyncClient", new=_FakeAsyncClient),
            patch(
                f"{_MODULE}.complete_platform_link",
                new_callable=AsyncMock,
                return_value=completion,
            ),
            patch(f"{_MODULE}.log") as log,
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "s1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == _frontend(
            "/settings?oauth_success=true&integration=discord"
        )
        log.set.assert_any_call(
            user={"id": "uid1"}, platform="discord", operation="platform_oauth_callback"
        )
        log.set.assert_any_call(profile_fields_extracted=["username", "display_name"])
        log.set.assert_any_call(outcome="success")

    async def test_an_unexpected_error_marks_the_call_failed_and_bounces(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
                new_callable=AsyncMock,
                return_value={"user_id": "uid1", "redirect_path": "/settings"},
            ),
            patch(
                f"{_MODULE}._exchange_code",
                new_callable=AsyncMock,
                side_effect=ValueError("boom"),
            ),
            patch(f"{_MODULE}.log") as log,
        ):
            resp = await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "s1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == _frontend("/settings?oauth_error=failed")
        log.set.assert_any_call(outcome="failed")
        log.error.assert_called_once_with(
            "[API] Platform OAuth callback error",
            platform="discord",
            error_type="ValueError",
            error="boom",
            exc_info=True,
        )


class TestCallbackHandsEachStepWhatItNeeds:
    async def test_the_code_and_the_profile_reach_the_exchange_and_the_link(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state",
                new_callable=AsyncMock,
                return_value={"user_id": "uid1", "redirect_path": "/settings"},
            ),
            patch(
                f"{_MODULE}._exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "tok_abc"},
            ) as exchange,
            patch(
                f"{_MODULE}._resolve_platform_user",
                new_callable=AsyncMock,
                return_value=("DISC1", {"username": "user", "display_name": "User"}),
            ),
            patch(f"{_MODULE}._link_platform_account", new_callable=AsyncMock) as link,
        ):
            await client.get(
                f"{BASE}/discord/callback",
                params={"code": "c1", "state": "s1"},
                follow_redirects=False,
            )

        from app.api.v1.endpoints.platform_auth import PLATFORM_CONFIGS

        exchange.assert_awaited_once_with(PLATFORM_CONFIGS["discord"], "c1")
        link.assert_awaited_once_with(
            "uid1",
            PLATFORM_CONFIGS["discord"],
            "DISC1",
            {"username": "user", "display_name": "User"},
        )
