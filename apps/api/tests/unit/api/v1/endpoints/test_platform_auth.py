"""Unit tests for the Discord/Slack OAuth callback endpoint.

``PLATFORM_CONFIGS`` is built at import time, so nothing that only imports
this module ever runs ``PlatformOAuthConfig.__init__`` or its default
extractor lambdas again. These tests construct configs and drive the shared
callback handler directly: the provider-shape accessors (where Slack's user
token and profile live versus Discord's) and the redirect contract are only
provable by executing them here.

The seams mocked are the provider HTTP calls, the OAuth state store, the link
service and the outbound greeting — never the handler under test.
"""

from collections.abc import Iterator
from typing import Any, ClassVar
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.api.v1.endpoints.platform_auth import (
    PLATFORM_CONFIGS,
    PlatformOAuthConfig,
    _handle_platform_oauth_callback,
    _redirect_url,
)
from app.models.platform_models import PlatformLinkResult

MODULE = "app.api.v1.endpoints.platform_auth"
STATE_SERVICE = "app.services.oauth.oauth_state_service.validate_and_consume_oauth_state"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.text = "provider said no"
        self._payload = payload if payload is not None else {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """Hands out queued responses; one instance per ``async with`` block."""

    queue: ClassVar[list[_FakeResponse]] = []
    requests: ClassVar[list[tuple[str, str]]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, url: str, **_kwargs: Any) -> _FakeResponse:
        _FakeAsyncClient.requests.append(("POST", url))
        return _FakeAsyncClient.queue.pop(0)

    async def get(self, url: str, **_kwargs: Any) -> _FakeResponse:
        _FakeAsyncClient.requests.append(("GET", url))
        return _FakeAsyncClient.queue.pop(0)


def _query(response: Any) -> dict[str, str]:
    parsed = urlparse(response.headers["location"])
    return {key: values[0] for key, values in parse_qs(parsed.query).items()}


@pytest.fixture
def provider_http() -> Iterator[type[_FakeAsyncClient]]:
    _FakeAsyncClient.queue = []
    _FakeAsyncClient.requests = []
    with patch(f"{MODULE}.httpx.AsyncClient", _FakeAsyncClient):
        yield _FakeAsyncClient


@pytest.fixture
def valid_state() -> Iterator[AsyncMock]:
    with patch(
        STATE_SERVICE,
        new_callable=AsyncMock,
        return_value={"user_id": "user-1", "redirect_path": "/settings"},
    ) as mock:
        yield mock


@pytest.fixture
def link_service() -> Iterator[AsyncMock]:
    result = PlatformLinkResult(
        status="linked",
        platform="discord",
        platform_user_id="p1",
        connected_at="2026-01-01T00:00:00Z",
        is_new_link=True,
    )
    with (
        patch(
            f"{MODULE}.PlatformLinkService.link_account",
            new_callable=AsyncMock,
            return_value=result,
        ) as mock,
        patch(f"{MODULE}.notify_account_linked", new_callable=AsyncMock),
    ):
        yield mock


class TestRedirectUrl:
    def test_appends_a_query_string_to_a_bare_path(self) -> None:
        assert _redirect_url("https://app.test", "/settings", ok="1") == (
            "https://app.test/settings?ok=1"
        )

    def test_appends_to_a_path_that_already_has_a_query(self) -> None:
        assert _redirect_url("https://app.test", "/settings?section=links", ok="1") == (
            "https://app.test/settings?section=links&ok=1"
        )

    def test_params_are_url_encoded(self) -> None:
        assert _redirect_url("https://app.test", "/x", value="a b&c") == (
            "https://app.test/x?value=a+b%26c"
        )


class TestDefaultExtractors:
    """The lambdas ``PlatformOAuthConfig.__init__`` installs when none are given."""

    def _config(self, **overrides: Any) -> PlatformOAuthConfig:
        defaults: dict[str, Any] = {
            "platform": "test",
            "token_url": "https://test/token",  # nosec B106 - not a password
            "get_client_id": lambda: "id",
            "get_client_secret": lambda: "secret",
            "get_redirect_uri": lambda: "https://app.test/cb",
            "extract_user_id": lambda token_data, access_token: "",
        }
        return PlatformOAuthConfig(**{**defaults, **overrides})

    def test_the_access_token_defaults_to_the_top_level_field(self) -> None:
        config = self._config()

        assert config.get_user_access_token({"access_token": "tok"}) == "tok"

    def test_a_missing_access_token_is_none_rather_than_empty(self) -> None:
        config = self._config()

        assert config.get_user_access_token({}) is None

    def test_the_default_profile_reads_discords_username_fields(self) -> None:
        config = self._config()

        profile = config.extract_profile_from_user_info(
            {"username": "handle", "global_name": "Display Name"}
        )

        assert profile == {"username": "handle", "display_name": "Display Name"}

    def test_the_display_name_falls_back_to_the_username(self) -> None:
        config = self._config()

        profile = config.extract_profile_from_user_info({"username": "handle"})

        assert profile == {"username": "handle", "display_name": "handle"}

    def test_an_explicit_extractor_replaces_the_default(self) -> None:
        config = self._config(get_user_access_token=lambda data: "override")

        assert config.get_user_access_token({"access_token": "tok"}) == "override"

    def test_extra_token_headers_default_to_empty(self) -> None:
        assert self._config().extra_token_headers == {}


class TestPlatformConfigs:
    def test_slack_reads_the_user_token_from_authed_user(self) -> None:
        slack = PLATFORM_CONFIGS["slack"]

        assert slack.get_user_access_token({"authed_user": {"access_token": "xoxp"}}) == "xoxp"

    def test_slack_reads_the_user_id_from_authed_user(self) -> None:
        slack = PLATFORM_CONFIGS["slack"]

        assert slack.extract_user_id({"authed_user": {"id": "U1"}}, "xoxp") == "U1"

    def test_slack_reads_the_profile_from_the_nested_user_object(self) -> None:
        slack = PLATFORM_CONFIGS["slack"]

        profile = slack.extract_profile_from_user_info({"user": {"id": "U1", "name": "aryan"}})

        assert profile == {"username": "aryan", "display_name": "aryan"}

    def test_discord_reads_the_user_token_from_the_top_level(self) -> None:
        discord = PLATFORM_CONFIGS["discord"]

        assert discord.get_user_access_token({"access_token": "tok"}) == "tok"


class TestCallbackEarlyExits:
    async def test_a_denied_authorization_reports_cancelled(self) -> None:
        response = await _handle_platform_oauth_callback(
            None, None, "access_denied", PLATFORM_CONFIGS["discord"]
        )

        assert _query(response)["oauth_error"] == "cancelled"

    async def test_any_other_provider_error_reports_failed(self) -> None:
        response = await _handle_platform_oauth_callback(
            None, None, "server_error", PLATFORM_CONFIGS["discord"]
        )

        assert _query(response)["oauth_error"] == "failed"

    @pytest.mark.parametrize(("code", "state"), [(None, "s"), ("c", None), (None, None)])
    async def test_a_missing_code_or_state_reports_missing_params(
        self, code: str | None, state: str | None
    ) -> None:
        response = await _handle_platform_oauth_callback(
            code, state, None, PLATFORM_CONFIGS["discord"]
        )

        assert _query(response)["oauth_error"] == "missing_params"

    async def test_an_unrecognised_state_token_reports_invalid_state(self) -> None:
        with patch(STATE_SERVICE, new_callable=AsyncMock, return_value=None):
            response = await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        assert _query(response)["oauth_error"] == "invalid_state"


class TestCallbackProviderExchange:
    async def test_a_non_200_token_exchange_reports_token_failed(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [_FakeResponse(401)]

        response = await _handle_platform_oauth_callback(
            "code", "state", None, PLATFORM_CONFIGS["discord"]
        )

        assert _query(response)["oauth_error"] == "token_failed"

    async def test_slacks_ok_false_body_reports_token_failed(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [_FakeResponse(200, {"ok": False, "error": "bad_code"})]

        response = await _handle_platform_oauth_callback(
            "code", "state", None, PLATFORM_CONFIGS["slack"]
        )

        assert _query(response)["oauth_error"] == "token_failed"

    async def test_a_failed_user_fetch_reports_user_fetch_failed(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [_FakeResponse(200, {"access_token": "tok"}), _FakeResponse(403)]

        response = await _handle_platform_oauth_callback(
            "code", "state", None, PLATFORM_CONFIGS["discord"]
        )

        assert _query(response)["oauth_error"] == "user_fetch_failed"

    async def test_a_transport_error_reports_failed(
        self, valid_state: AsyncMock, link_service: AsyncMock
    ) -> None:
        with patch(f"{MODULE}.httpx.AsyncClient", side_effect=RuntimeError("network down")):
            response = await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        assert _query(response)["oauth_error"] == "failed"


class TestCallbackLinking:
    async def test_discord_links_the_id_from_the_user_info_response(
        self,
        provider_http: type[_FakeAsyncClient],
        valid_state: AsyncMock,
        link_service: AsyncMock,
    ) -> None:
        provider_http.queue = [
            _FakeResponse(200, {"access_token": "tok"}),
            _FakeResponse(200, {"id": "D42", "username": "aryan", "global_name": "Aryan"}),
        ]

        response = await _handle_platform_oauth_callback(
            "code", "state", None, PLATFORM_CONFIGS["discord"]
        )

        link_service.assert_awaited_once_with(
            "user-1",
            "discord",
            "D42",
            profile={"username": "aryan", "display_name": "Aryan"},
        )
        assert _query(response) == {
            "oauth_success": "true",
            "integration": "discord",
        }

    async def test_a_user_info_response_without_an_id_falls_back_to_the_token_payload(
        self,
        provider_http: type[_FakeAsyncClient],
        valid_state: AsyncMock,
        link_service: AsyncMock,
    ) -> None:
        """Slack's users.identity nests the id, so the token payload is authoritative."""
        provider_http.queue = [
            _FakeResponse(200, {"ok": True, "authed_user": {"id": "U9", "access_token": "xoxp"}}),
            _FakeResponse(200, {"user": {"name": "aryan"}}),
        ]

        await _handle_platform_oauth_callback("code", "state", None, PLATFORM_CONFIGS["slack"])

        link_service.assert_awaited_once_with(
            "user-1",
            "slack",
            "U9",
            profile={"username": "aryan", "display_name": "aryan"},
        )

    async def test_an_already_linked_account_reports_already_linked(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [
            _FakeResponse(200, {"access_token": "tok"}),
            _FakeResponse(200, {"id": "D42", "username": "aryan"}),
        ]

        with patch(
            f"{MODULE}.PlatformLinkService.link_account",
            new_callable=AsyncMock,
            side_effect=ValueError("This discord account is already linked"),
        ):
            response = await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        assert _query(response)["oauth_error"] == "already_linked"

    async def test_any_other_link_rejection_reports_failed(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [
            _FakeResponse(200, {"access_token": "tok"}),
            _FakeResponse(200, {"id": "D42", "username": "aryan"}),
        ]

        with patch(
            f"{MODULE}.PlatformLinkService.link_account",
            new_callable=AsyncMock,
            side_effect=ValueError("platform_user_id must not be empty"),
        ):
            response = await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        assert _query(response)["oauth_error"] == "failed"

    async def test_the_greeting_only_fires_for_a_brand_new_link(
        self, provider_http: type[_FakeAsyncClient], valid_state: AsyncMock
    ) -> None:
        provider_http.queue = [
            _FakeResponse(200, {"access_token": "tok"}),
            _FakeResponse(200, {"id": "D42", "username": "aryan"}),
        ]
        relink = PlatformLinkResult(
            status="linked",
            platform="discord",
            platform_user_id="D42",
            connected_at="2026-01-01T00:00:00Z",
            is_new_link=False,
        )

        with (
            patch(
                f"{MODULE}.PlatformLinkService.link_account",
                new_callable=AsyncMock,
                return_value=relink,
            ),
            patch(f"{MODULE}.notify_account_linked", new_callable=AsyncMock) as notify,
        ):
            await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        notify.assert_not_awaited()

    async def test_success_returns_the_user_to_the_path_they_started_from(
        self,
        provider_http: type[_FakeAsyncClient],
        link_service: AsyncMock,
    ) -> None:
        provider_http.queue = [
            _FakeResponse(200, {"access_token": "tok"}),
            _FakeResponse(200, {"id": "D42", "username": "aryan"}),
        ]

        with patch(
            STATE_SERVICE,
            new_callable=AsyncMock,
            return_value={"user_id": "user-1", "redirect_path": "/integrations?tab=bots"},
        ):
            response = await _handle_platform_oauth_callback(
                "code", "state", None, PLATFORM_CONFIGS["discord"]
            )

        location = response.headers["location"]
        assert "/integrations?tab=bots&" in location
        assert _query(response)["oauth_success"] == "true"
