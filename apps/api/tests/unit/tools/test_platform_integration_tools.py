"""Unit tests for the newer Composio integration tools.

Covers:
- google_maps_tool.py
- hubspot_tool.py
- instagram_tool.py
- microsoft_teams_tool.py
- reddit_tool.py

Same capture strategy as test_small_integration_tools.py: register the custom
tools against a capturing Composio mock, then invoke the inner functions
directly with mock auth_credentials. The seam here is ``proxy_request_sync``
(these tools proxy through the composio proxy client instead of execute_tool).
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.common_models import GatherContextInput
from app.utils.errors import AppError

FAKE_USER_ID = "user-123"
AUTH_CREDS_USER_ONLY: dict[str, Any] = {"user_id": FAKE_USER_ID}
EXECUTE_REQUEST = MagicMock()


def _make_capturing_composio() -> tuple[MagicMock, dict[str, Callable[..., Any]]]:
    """Create a Composio mock whose custom_tool decorator captures inner functions."""
    composio = MagicMock()
    captured: dict[str, Callable[..., Any]] = {}

    def _custom_tool(**kwargs: Any) -> Callable[..., Any]:
        def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio.tools.custom_tool = _custom_tool
    return composio, captured


# =============================================================================
# GOOGLE MAPS TOOLS
# =============================================================================

GOOGLE_MAPS_MODULE = "app.agents.tools.integrations.google_maps_tool"


class TestGoogleMapsGatherContext:
    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.google_maps_tool import (
            register_google_maps_custom_tools,
        )

        names = register_google_maps_custom_tools(composio)
        assert "GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{GOOGLE_MAPS_MODULE}.proxy_request_sync")
    def test_api_connected_when_geocode_returns_ok(self, mock_proxy: MagicMock) -> None:
        mock_proxy.return_value = {"status": "OK"}

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["api_connected"] is True
        assert result["status"] == "OK"
        assert "geocoding" in result["available_services"]

    @patch(f"{GOOGLE_MAPS_MODULE}.proxy_request_sync")
    def test_non_ok_status_means_not_connected(self, mock_proxy: MagicMock) -> None:
        mock_proxy.return_value = {"status": "REQUEST_DENIED"}

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["api_connected"] is False
        assert result["status"] == "REQUEST_DENIED"

    @patch(f"{GOOGLE_MAPS_MODULE}.proxy_request_sync")
    def test_proxy_exception_reports_error_status(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = RuntimeError("api down")

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["api_connected"] is False
        assert result["status"] == "ERROR"

    @patch(f"{GOOGLE_MAPS_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_app_error(self, mock_proxy: MagicMock) -> None:
        captured = self._register()
        with pytest.raises(AppError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# HUBSPOT TOOLS
# =============================================================================

HUBSPOT_MODULE = "app.agents.tools.integrations.hubspot_tool"


class TestHubSpotGatherContext:
    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.hubspot_tool import register_hubspot_custom_tools

        names = register_hubspot_custom_tools(composio)
        assert "HUBSPOT_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_basic_success(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "results": [
                    {
                        "id": "c1",
                        "properties": {
                            "firstname": "Ada",
                            "lastname": "L",
                            "email": "ada@x.com",
                            "hs_lead_status": "OPEN",
                        },
                    }
                ]
            },
            {
                "results": [
                    {
                        "id": "d1",
                        "properties": {
                            "dealname": "Big deal",
                            "amount": "1000",
                            "dealstage": "closedwon",
                            "closedate": "2026-01-01",
                        },
                    }
                ]
            },
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["contact_count"] == 1
        assert result["recent_contacts"][0]["email"] == "ada@x.com"
        assert result["recent_contacts"][0]["lead_status"] == "OPEN"
        assert result["deal_count"] == 1
        assert result["recent_deals"][0]["dealname"] == "Big deal"

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_deals_fetch_failure_keeps_contacts(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"results": [{"id": "c1", "properties": {}}]},
            RuntimeError("hubspot down"),
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["contact_count"] == 1
        assert result["recent_deals"] == []
        assert result["deal_count"] == 0

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        captured = self._register()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# INSTAGRAM TOOLS
# =============================================================================

INSTAGRAM_MODULE = "app.agents.tools.integrations.instagram_tool"


class TestInstagramGatherContext:
    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.instagram_tool import (
            register_instagram_custom_tools,
        )

        names = register_instagram_custom_tools(composio)
        assert "INSTAGRAM_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{INSTAGRAM_MODULE}.proxy_request_sync")
    def test_basic_success(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "id": "u1",
                "name": "Ada",
                "username": "ada",
                "account_type": "BUSINESS",
                "media_count": 3,
            },
            {
                "data": [
                    {
                        "id": "m1",
                        "caption": "a caption",
                        "media_type": "IMAGE",
                        "timestamp": "t",
                        "like_count": 4,
                        "comments_count": 1,
                        "permalink": "https://ig/p1",
                    },
                ]
            },
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["username"] == "ada"
        assert result["user"]["media_count"] == 3
        assert result["recent_media"][0]["caption"] == "a caption"
        assert result["recent_media"][0]["likes"] == 4

    @patch(f"{INSTAGRAM_MODULE}.proxy_request_sync")
    def test_media_fetch_failure_returns_empty_media(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"id": "u1", "username": "ada"},
            RuntimeError("graph api down"),
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["username"] == "ada"
        assert result["recent_media"] == []

    @patch(f"{INSTAGRAM_MODULE}.proxy_request_sync")
    def test_caption_and_biography_are_truncated(self, mock_proxy: MagicMock) -> None:
        long_caption = "c" * 500
        long_bio = "b" * 500
        mock_proxy.side_effect = [
            {"id": "u1", "username": "ada", "biography": long_bio},
            {"data": [{"id": "m1", "caption": long_caption, "media_type": "IMAGE"}]},
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert len(result["recent_media"][0]["caption"]) == 100
        assert len(result["user"]["biography"]) == 200

    @patch(f"{INSTAGRAM_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        captured = self._register()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# MICROSOFT TEAMS TOOLS
# =============================================================================

TEAMS_MODULE = "app.agents.tools.integrations.microsoft_teams_tool"


class TestMicrosoftTeamsGatherContext:
    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.microsoft_teams_tool import (
            register_microsoft_teams_custom_tools,
        )

        names = register_microsoft_teams_custom_tools(composio)
        assert "MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_basic_success(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "displayName": "Ada", "mail": "ada@x.com"},
            {"value": [{"id": "t1", "displayName": "Eng", "description": "team"}]},
            {
                "value": [
                    {
                        "id": "c1",
                        "topic": "Design",
                        "chatType": "group",
                        "lastMessagePreview": {"body": {"content": "hi all"}, "isRead": False},
                    },
                    {
                        "id": "c2",
                        "topic": "Read chat",
                        "chatType": "oneOnOne",
                        "lastMessagePreview": {"body": {"content": "old"}, "isRead": True},
                    },
                    {"id": "c3", "topic": "No preview", "chatType": "group"},
                ]
            },
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["display_name"] == "Ada"
        assert result["user"]["email"] == "ada@x.com"
        assert result["team_count"] == 1
        assert result["teams"][0]["name"] == "Eng"
        assert result["chat_count"] == 3
        assert result["unread_chat_count"] == 1
        unread_chat = next(c for c in result["recent_chats"] if c["id"] == "c1")
        assert unread_chat["is_read"] is False
        assert unread_chat["last_message_preview"] == "hi all"

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_partial_failures_degrade_gracefully(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            RuntimeError("me down"),
            {"value": [{"id": "t1", "displayName": "Eng"}]},
            RuntimeError("chats down"),
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"] == {}
        assert result["team_count"] == 1
        assert result["chat_count"] == 0
        assert result["unread_chat_count"] == 0

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        captured = self._register()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# REDDIT TOOLS
# =============================================================================

REDDIT_MODULE = "app.agents.tools.integrations.reddit_tool"


class TestRedditGatherContext:
    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.reddit_tool import register_reddit_custom_tools

        names = register_reddit_custom_tools(composio)
        assert "REDDIT_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_basic_success(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "name": "ada",
                "id": "u1",
                "link_karma": 10,
                "comment_karma": 5,
                "total_karma": 15,
                "is_gold": True,
            },
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "display_name": "python",
                                "title": "Python subreddit",
                                "subscribers": 1000,
                            }
                        }
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "msg1",
                                "subject": "Hey",
                                "author": "bob",
                                "created_utc": 123,
                            }
                        }
                    ]
                }
            },
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["name"] == "ada"
        assert result["user"]["is_gold"] is True
        assert result["subscribed_subreddits"][0]["name"] == "python"
        assert result["subscribed_subreddits"][0]["subscribers"] == 1000
        assert result["unread_message_count"] == 1
        assert result["unread_messages"][0]["subject"] == "Hey"

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_failed_fetches_return_empty_sections(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            RuntimeError("me down"),
            {"data": {"children": []}},
            RuntimeError("messages down"),
        ]

        captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["name"] is None  # /me failed -> defaults only
        assert result["user"]["link_karma"] == 0
        assert result["subscribed_subreddits"] == []
        assert result["unread_message_count"] == 0

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_app_error(self, mock_proxy: MagicMock) -> None:
        captured = self._register()
        with pytest.raises(AppError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})
