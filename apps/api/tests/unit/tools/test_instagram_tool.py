"""Unit tests for app.agents.tools.integrations.instagram_tool.

Only the true I/O boundaries are faked: `proxy_request_sync` (routed through
a canned Instagram Graph API fake that records every request) and the
wide-event logger. Everything else — request assembly, defaults, 100/200-char
truncation, graceful degradation — runs for real, so the assertions pin the
exact payloads the tool produces and the exact requests it sends.

All expectations are hardcoded (never derived from module constants): a
mutated constant in the module under test must not be able to satisfy them.

The registration smoke test for this module also lives in
`test_integration_tools_proxy.py`; this file is the per-tool behavioral net.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.instagram_tool import register_instagram_custom_tools
from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput

MODULE = "app.agents.tools.integrations.instagram_tool"
USER_ID = "user-42"
AUTH_CREDS: dict[str, Any] = {"user_id": USER_ID}
EXECUTE_REQUEST = MagicMock()

ME_ENDPOINT = "https://graph.instagram.com/v18.0/me"
MEDIA_ENDPOINT = "https://graph.instagram.com/v18.0/me/media"
ME_FIELDS = (
    "id,name,username,account_type,media_count,"
    "followers_count,follows_count,biography"
)
MEDIA_FIELDS = (
    "id,caption,media_type,timestamp,like_count,comments_count,permalink"
)

MEDIA_ERROR_LOG = f"{LogTag.TOOL} Instagram media fetch failed"

DEFAULT_USER = {
    "id": None,
    "name": None,
    "username": None,
    "account_type": None,
    "media_count": 0,
    "followers": 0,
    "following": 0,
    "biography": "",
}


class FakeInstagramApi:
    """Routes proxy calls to canned Instagram responses and records every request."""

    def __init__(self) -> None:
        self.me: Any = {}
        self.media: Any = {}
        self.me_error: Exception | None = None
        self.media_error: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs["endpoint"] == ME_ENDPOINT:
            if self.me_error is not None:
                raise self.me_error
            return self.me
        if kwargs["endpoint"] == MEDIA_ENDPOINT:
            if self.media_error is not None:
                raise self.media_error
            return self.media
        raise AssertionError(f"unexpected endpoint: {kwargs['endpoint']}")


def _register() -> tuple[list[str], dict[str, Any]]:
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    names = register_instagram_custom_tools(composio)
    return names, captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _register()[1]


@pytest.fixture
def api() -> FakeInstagramApi:
    fake = FakeInstagramApi()
    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=fake),
        patch(f"{MODULE}.log") as logger,
    ):
        fake.log = logger
        yield fake


def _call(tools: dict[str, Any], credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = tools["CUSTOM_GATHER_CONTEXT"](
        GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS if credentials is None else credentials
    )
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_returns_the_single_advertised_tool_name(self) -> None:
        names, captured = _register()

        # A name in the list with no tool behind it is a tool the agent can
        # select and never execute.
        assert names == ["INSTAGRAM_CUSTOM_GATHER_CONTEXT"]
        assert names == [f"INSTAGRAM_{fn}" for fn in captured]

    def test_tool_is_registered_under_the_instagram_toolkit(self) -> None:
        composio = MagicMock()
        register_instagram_custom_tools(composio)

        composio.tools.custom_tool.assert_called_once_with(toolkit="INSTAGRAM")


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


class TestMissingUserId:
    @pytest.mark.parametrize(
        "credentials",
        [{}, {"user_id": None}, {"user_id": ""}, {"user_id": 0}, {"userId": "abc"}],
    )
    def test_unusable_credentials_raise_before_any_proxy_call(
        self, tools: Any, api: FakeInstagramApi, credentials: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError) as excinfo:
            _call(tools, credentials)

        assert str(excinfo.value) == "Missing user_id in auth_credentials"
        # Falling through with a blank user id would send the request as nobody.
        assert api.calls == []
        api.log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestGatherContextSuccess:
    def test_returns_the_full_snapshot(self, tools: Any, api: FakeInstagramApi) -> None:
        api.me = {
            "id": "u1",
            "name": "gaia_user",
            "username": "gaia.photo",
            "account_type": "BUSINESS",
            "media_count": 42,
            "followers_count": 1_200,
            "follows_count": 300,
            "biography": "Photographer",
        }
        api.media = {
            "data": [
                {
                    "id": "m1",
                    "caption": "Hello world",
                    "media_type": "IMAGE",
                    "timestamp": "2024-01-15T10:00:00+0000",
                    "like_count": 7,
                    "comments_count": 2,
                    "permalink": "https://www.instagram.com/p/m1/",
                },
                {
                    "id": "m2",
                    "caption": "",
                    "media_type": "VIDEO",
                    "timestamp": "2024-01-16T10:00:00+0000",
                    "like_count": 0,
                    "comments_count": 0,
                    "permalink": None,
                },
            ]
        }

        result = _call(tools)

        assert result == {
            "user": {
                "id": "u1",
                "name": "gaia_user",
                "username": "gaia.photo",
                "account_type": "BUSINESS",
                "media_count": 42,
                "followers": 1_200,
                "following": 300,
                "biography": "Photographer",
            },
            "recent_media": [
                {
                    "id": "m1",
                    "caption": "Hello world",
                    "media_type": "IMAGE",
                    "timestamp": "2024-01-15T10:00:00+0000",
                    "likes": 7,
                    "comments": 2,
                    "permalink": "https://www.instagram.com/p/m1/",
                },
                {
                    "id": "m2",
                    "caption": "",
                    "media_type": "VIDEO",
                    "timestamp": "2024-01-16T10:00:00+0000",
                    "likes": 0,
                    "comments": 0,
                    "permalink": None,
                },
            ],
        }
        # A clean snapshot must not log any failure.
        api.log.warning.assert_not_called()

    def test_sends_exactly_two_proxy_requests_in_order(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        _call(tools)

        assert len(api.calls) == 2
        assert api.calls[0] == {
            "user_id": USER_ID,
            "toolkit": "INSTAGRAM",
            "endpoint": ME_ENDPOINT,
            "method": "GET",
            "query": {"fields": ME_FIELDS},
        }
        assert api.calls[1] == {
            "user_id": USER_ID,
            "toolkit": "INSTAGRAM",
            "endpoint": MEDIA_ENDPOINT,
            "method": "GET",
            "query": {"limit": "5", "fields": MEDIA_FIELDS},
        }


# ---------------------------------------------------------------------------
# Missing optional fields -> defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_me_fields_fall_back_to_none_zero_and_empty_string(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        api.me = {"name": "only_name"}

        result = _call(tools)

        assert result["user"] == {**DEFAULT_USER, "name": "only_name"}
        api.log.warning.assert_not_called()

    def test_media_item_without_optional_fields(self, tools: Any, api: FakeInstagramApi) -> None:
        api.media = {"data": [{"id": "m9"}]}

        result = _call(tools)

        assert result["recent_media"] == [
            {
                "id": "m9",
                "caption": "",
                "media_type": None,
                "timestamp": None,
                "likes": 0,
                "comments": 0,
                "permalink": None,
            }
        ]
        api.log.warning.assert_not_called()

    def test_none_caption_and_none_biography_become_empty_strings(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        api.me = {"biography": None}
        api.media = {"data": [{"id": "m1", "caption": None}]}

        result = _call(tools)

        assert result["user"]["biography"] == ""
        assert result["recent_media"][0]["caption"] == ""
        api.log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_caption_is_truncated_to_100_chars(self, tools: Any, api: FakeInstagramApi) -> None:
        api.media = {"data": [{"id": "m1", "caption": "x" * 150}]}

        result = _call(tools)

        assert result["recent_media"][0]["caption"] == "x" * 100

    def test_biography_is_truncated_to_200_chars(self, tools: Any, api: FakeInstagramApi) -> None:
        api.me = {"biography": "y" * 250}

        result = _call(tools)

        assert result["user"]["biography"] == "y" * 200


# ---------------------------------------------------------------------------
# Empty / malformed proxy payloads
# ---------------------------------------------------------------------------


class TestEmptyResponses:
    @pytest.mark.parametrize("empty", [None, {}])
    def test_falsy_proxy_responses_yield_default_user_and_no_media(
        self, tools: Any, api: FakeInstagramApi, empty: Any
    ) -> None:
        api.me = empty
        api.media = empty

        result = _call(tools)

        assert result == {"user": dict(DEFAULT_USER), "recent_media": []}
        # `or {}` handles falsy payloads without treating them as failures.
        api.log.warning.assert_not_called()

    def test_data_present_but_empty(self, tools: Any, api: FakeInstagramApi) -> None:
        api.media = {"data": []}

        result = _call(tools)

        assert result["recent_media"] == []
        api.log.warning.assert_not_called()

    def test_data_key_missing_is_not_a_failure(self, tools: Any, api: FakeInstagramApi) -> None:
        # `.get("data", [])` must supply the default; dropping the default
        # would iterate `None` and log a spurious media failure.
        api.media = {"data_typo": []}

        result = _call(tools)

        assert result["recent_media"] == []
        api.log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Proxy failures -> graceful degradation + wide-event logging
# ---------------------------------------------------------------------------


class TestFetchFailures:
    def test_me_failure_propagates_and_no_media_request_is_sent(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        # The /me fetch is not wrapped in a try: a failed profile fetch must
        # surface to the caller instead of returning a silently empty user.
        api.me_error = RuntimeError("graph down")

        with pytest.raises(RuntimeError, match="graph down"):
            _call(tools)

        assert len(api.calls) == 1
        assert api.calls[0]["endpoint"] == ME_ENDPOINT
        api.log.warning.assert_not_called()

    def test_media_failure_is_logged_and_degrades_to_empty(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        err = RuntimeError("media down")
        api.media_error = err
        api.me = {"id": "u1", "name": "gaia_user"}

        result = _call(tools)

        assert result["user"]["id"] == "u1"
        assert result["user"]["name"] == "gaia_user"
        # The media section degrades to an empty list, never to None.
        assert result["recent_media"] == []
        # The failure is reported exactly once with the exact error type.
        api.log.warning.assert_called_once_with(
            MEDIA_ERROR_LOG, user_id=USER_ID, error_type="RuntimeError"
        )

    def test_malformed_media_data_degrades_identically(
        self, tools: Any, api: FakeInstagramApi
    ) -> None:
        # `data: None` makes the comprehension raise inside the try; the tool
        # must log the failure and return an empty media section rather than
        # crashing the whole snapshot.
        api.media = {"data": None}

        result = _call(tools)

        assert result["recent_media"] == []
        api.log.warning.assert_called_once_with(
            MEDIA_ERROR_LOG, user_id=USER_ID, error_type="TypeError"
        )
