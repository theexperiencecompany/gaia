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
    composio.tool_kwargs: list[dict[str, Any]] = []

    def _custom_tool(**kwargs: Any) -> Callable[..., Any]:
        composio.tool_kwargs.append(kwargs)

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
HUBSPOT_CONTACTS_ENDPOINT = "https://api.hubapi.com/crm/v3/objects/contacts"
HUBSPOT_DEALS_ENDPOINT = "https://api.hubapi.com/crm/v3/objects/deals"
HUBSPOT_CONTACTS_QUERY: dict[str, Any] = {
    "limit": 10,
    "properties": "firstname,lastname,email,hs_lead_status",
    "sort": "-createdate",
}
HUBSPOT_DEALS_QUERY: dict[str, Any] = {
    "limit": 10,
    "properties": "dealname,amount,dealstage,closedate",
    "sort": "-createdate",
}
HUBSPOT_EMPTY_RESULT: dict[str, Any] = {
    "recent_contacts": [],
    "recent_deals": [],
    "contact_count": 0,
    "deal_count": 0,
}


class TestHubSpotGatherContext:
    def _register(self) -> tuple[MagicMock, dict[str, Callable[..., Any]]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.hubspot_tool import register_hubspot_custom_tools

        names = register_hubspot_custom_tools(composio)
        assert names == ["HUBSPOT_CUSTOM_GATHER_CONTEXT"]
        return composio, captured

    def _assert_proxy_call(
        self, mock_proxy: MagicMock, index: int, *, endpoint: str, query: dict[str, Any]
    ) -> None:
        assert mock_proxy.call_args_list[index].kwargs == {
            "user_id": FAKE_USER_ID,
            "toolkit": "HUBSPOT",
            "endpoint": endpoint,
            "method": "GET",
            "query": query,
        }

    def test_registers_custom_tool_with_hubspot_toolkit(self) -> None:
        composio, _ = self._register()
        assert composio.tool_kwargs == [{"toolkit": "HUBSPOT"}]

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_basic_success(self, mock_log: MagicMock, mock_proxy: MagicMock) -> None:
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

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 2
        self._assert_proxy_call(mock_proxy, 0, endpoint=HUBSPOT_CONTACTS_ENDPOINT, query=HUBSPOT_CONTACTS_QUERY)
        self._assert_proxy_call(mock_proxy, 1, endpoint=HUBSPOT_DEALS_ENDPOINT, query=HUBSPOT_DEALS_QUERY)
        assert result == {
            "recent_contacts": [
                {
                    "id": "c1",
                    "firstname": "Ada",
                    "lastname": "L",
                    "email": "ada@x.com",
                    "lead_status": "OPEN",
                }
            ],
            "recent_deals": [
                {
                    "id": "d1",
                    "dealname": "Big deal",
                    "amount": "1000",
                    "dealstage": "closedwon",
                    "closedate": "2026-01-01",
                }
            ],
            "contact_count": 1,
            "deal_count": 1,
        }
        mock_log.set.assert_called_once_with(
            tool={"integration": "hubspot", "action": "gather_context"}
        )
        mock_log.debug.assert_not_called()

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_contacts_fetch_failure_keeps_deals(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            RuntimeError("hubspot down"),
            {"results": [{"id": "d1", "properties": {}}]},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 2
        assert result == {
            "recent_contacts": [],
            "recent_deals": [
                {"id": "d1", "dealname": None, "amount": None, "dealstage": None, "closedate": None}
            ],
            "contact_count": 0,
            "deal_count": 1,
        }
        mock_log.set.assert_called_once_with(
            tool={"integration": "hubspot", "action": "gather_context"}
        )
        mock_log.debug.assert_called_once_with(
            "[TOOL] HubSpot contacts fetch failed", error_type="RuntimeError"
        )

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_deals_fetch_failure_keeps_contacts(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {"results": [{"id": "c1", "properties": {}}]},
            RuntimeError("hubspot down"),
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 2
        assert result == {
            "recent_contacts": [
                {"id": "c1", "firstname": None, "lastname": None, "email": None, "lead_status": None}
            ],
            "recent_deals": [],
            "contact_count": 1,
            "deal_count": 0,
        }
        mock_log.set.assert_called_once_with(
            tool={"integration": "hubspot", "action": "gather_context"}
        )
        mock_log.debug.assert_called_once_with(
            "[TOOL] HubSpot deals fetch failed", error_type="RuntimeError"
        )

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_none_responses_yield_empty_sections_without_failure_logs(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [None, None]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result == HUBSPOT_EMPTY_RESULT
        mock_log.debug.assert_not_called()

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_empty_payloads_yield_empty_sections_without_failure_logs(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [{}, {}]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result == HUBSPOT_EMPTY_RESULT
        mock_log.debug.assert_not_called()

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    @patch(f"{HUBSPOT_MODULE}.log")
    def test_missing_results_key_is_not_an_error(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [{"unexpected": 1}, {"unexpected": 2}]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result == HUBSPOT_EMPTY_RESULT
        mock_log.debug.assert_not_called()

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_missing_properties_fields_become_none(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "results": [
                    {"id": "bare"},
                    {"id": "partial", "properties": {"firstname": "Only"}},
                ]
            },
            {
                "results": [
                    {"id": "d-bare"},
                    {"id": "d-partial", "properties": {"dealname": "Only"}},
                ]
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["recent_contacts"] == [
            {
                "id": "bare",
                "firstname": None,
                "lastname": None,
                "email": None,
                "lead_status": None,
            },
            {
                "id": "partial",
                "firstname": "Only",
                "lastname": None,
                "email": None,
                "lead_status": None,
            },
        ]
        assert result["recent_deals"] == [
            {
                "id": "d-bare",
                "dealname": None,
                "amount": None,
                "dealstage": None,
                "closedate": None,
            },
            {
                "id": "d-partial",
                "dealname": "Only",
                "amount": None,
                "dealstage": None,
                "closedate": None,
            },
        ]
        assert result["contact_count"] == 2
        assert result["deal_count"] == 2

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_multiple_items_preserve_order_and_count(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"results": [{"id": "c1", "properties": {}}, {"id": "c2", "properties": {}}]},
            {
                "results": [
                    {"id": "d1", "properties": {}},
                    {"id": "d2", "properties": {}},
                    {"id": "d3", "properties": {}},
                ]
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert [c["id"] for c in result["recent_contacts"]] == ["c1", "c2"]
        assert [d["id"] for d in result["recent_deals"]] == ["d1", "d2", "d3"]
        assert result["contact_count"] == 2
        assert result["deal_count"] == 3

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(ValueError) as exc_info:
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"
        mock_proxy.assert_not_called()

    @patch(f"{HUBSPOT_MODULE}.proxy_request_sync")
    def test_empty_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(ValueError) as exc_info:
            captured["CUSTOM_GATHER_CONTEXT"](
                GatherContextInput(), EXECUTE_REQUEST, {"user_id": ""}
            )
        assert str(exc_info.value) == "Missing user_id in auth_credentials"
        mock_proxy.assert_not_called()


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
    def _register(self) -> tuple[MagicMock, dict[str, Callable[..., Any]]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.microsoft_teams_tool import (
            register_microsoft_teams_custom_tools,
        )

        names = register_microsoft_teams_custom_tools(composio)
        assert names == ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]
        return composio, captured

    def _assert_proxy_call(
        self, mock_proxy: MagicMock, index: int, *, endpoint: str, query: dict[str, Any]
    ) -> None:
        assert mock_proxy.call_args_list[index].kwargs == {
            "user_id": FAKE_USER_ID,
            "toolkit": "MICROSOFT_TEAMS",
            "endpoint": endpoint,
            "method": "GET",
            "query": query,
        }

    def test_registers_custom_tool_with_teams_toolkit(self) -> None:
        composio, _ = self._register()
        assert composio.tool_kwargs == [{"toolkit": "MICROSOFT_TEAMS"}]

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_basic_success(self, mock_log: MagicMock, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "id": "me1",
                "displayName": "Ada",
                "mail": "ada@x.com",
                "userPrincipalName": "upn@x.com",
            },
            {"value": [{"id": "t1", "displayName": "Eng", "description": "team"}]},
            {
                "value": [
                    {
                        "id": "c1",
                        "topic": "Design",
                        "chatType": "group",
                        "lastMessagePreview": {
                            "body": {"content": "hi all"},
                            "isRead": False,
                        },
                    },
                    {
                        "id": "c2",
                        "topic": "Read chat",
                        "chatType": "oneOnOne",
                        "lastMessagePreview": {
                            "body": {"content": "old"},
                            "isRead": True,
                        },
                    },
                    {"id": "c3", "topic": "No preview", "chatType": "group"},
                ]
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 3
        self._assert_proxy_call(
            mock_proxy,
            0,
            endpoint="https://graph.microsoft.com/v1.0/me",
            query={"$select": "id,displayName,mail,userPrincipalName"},
        )
        self._assert_proxy_call(
            mock_proxy,
            1,
            endpoint="https://graph.microsoft.com/v1.0/me/joinedTeams",
            query={"$select": "id,displayName,description"},
        )
        self._assert_proxy_call(
            mock_proxy,
            2,
            endpoint="https://graph.microsoft.com/v1.0/me/chats",
            query={"$expand": "lastMessagePreview", "$top": 10},
        )
        assert result == {
            "user": {"id": "me1", "display_name": "Ada", "email": "ada@x.com"},
            "teams": [{"id": "t1", "name": "Eng", "description": "team"}],
            "recent_chats": [
                {
                    "id": "c1",
                    "topic": "Design",
                    "chat_type": "group",
                    "last_message_preview": "hi all",
                    "is_read": False,
                },
                {
                    "id": "c2",
                    "topic": "Read chat",
                    "chat_type": "oneOnOne",
                    "last_message_preview": "old",
                    "is_read": True,
                },
                {
                    "id": "c3",
                    "topic": "No preview",
                    "chat_type": "group",
                    "last_message_preview": None,
                    "is_read": True,
                },
            ],
            "team_count": 1,
            "chat_count": 3,
            "unread_chat_count": 1,
        }
        mock_log.set.assert_called_once_with(
            tool={"integration": "microsoft_teams", "action": "gather_context"}
        )
        mock_log.debug.assert_not_called()

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_email_uses_mail_when_present(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "mail": "ada@x.com", "userPrincipalName": "upn@x.com"},
            {},
            {},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["email"] == "ada@x.com"

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_email_falls_back_to_upn_when_mail_missing(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "userPrincipalName": "ada@corp.com"},
            {},
            {},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["email"] == "ada@corp.com"

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_email_falls_back_to_upn_when_mail_empty(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "mail": "", "userPrincipalName": "ada@corp.com"},
            {},
            {},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["email"] == "ada@corp.com"

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})
        mock_proxy.assert_not_called()

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_empty_user_id_raises_value_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](
                GatherContextInput(), EXECUTE_REQUEST, {"user_id": ""}
            )
        mock_proxy.assert_not_called()

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_none_responses_yield_defaults_without_failure_logs(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [None, None, None]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result == {
            "user": {"id": None, "display_name": None, "email": None},
            "teams": [],
            "recent_chats": [],
            "team_count": 0,
            "chat_count": 0,
            "unread_chat_count": 0,
        }
        mock_log.debug.assert_not_called()

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_empty_payloads_yield_defaults_without_failure_logs(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [{}, {}, {}]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result == {
            "user": {"id": None, "display_name": None, "email": None},
            "teams": [],
            "recent_chats": [],
            "team_count": 0,
            "chat_count": 0,
            "unread_chat_count": 0,
        }
        mock_log.debug.assert_not_called()

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_unread_counting_and_is_read_boundaries(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {},
            {},
            {
                "value": [
                    {
                        "id": "unread",
                        "lastMessagePreview": {"body": {"content": "x"}, "isRead": False},
                    },
                    {
                        "id": "read",
                        "lastMessagePreview": {"body": {"content": "x"}, "isRead": True},
                    },
                    {"id": "no-isread", "lastMessagePreview": {"body": {"content": "x"}}},
                    {"id": "empty-preview", "lastMessagePreview": {}},
                    {"id": "no-preview"},
                ]
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["unread_chat_count"] == 1
        by_id = {c["id"]: c for c in result["recent_chats"]}
        assert by_id["unread"]["is_read"] is False
        assert by_id["read"]["is_read"] is True
        assert by_id["no-isread"]["is_read"] is True
        assert by_id["empty-preview"]["is_read"] is True
        assert by_id["no-preview"]["is_read"] is True
        assert by_id["no-isread"]["last_message_preview"] == "x"
        assert by_id["empty-preview"]["last_message_preview"] is None
        assert by_id["no-preview"]["last_message_preview"] is None

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_last_message_preview_truncated_to_100_chars(self, mock_proxy: MagicMock) -> None:
        long_content = "m" * 250
        mock_proxy.side_effect = [
            {},
            {},
            {"value": [{"id": "c1", "lastMessagePreview": {"body": {"content": long_content}}}]},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["recent_chats"][0]["last_message_preview"] == "m" * 100

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    def test_preview_without_body_yields_empty_preview(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {},
            {},
            {"value": [{"id": "c1", "lastMessagePreview": {"isRead": True}}]},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["recent_chats"][0]["last_message_preview"] == ""

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_me_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            RuntimeError("me down"),
            {"value": [{"id": "t1", "displayName": "Eng"}]},
            {"value": [{"id": "c1", "topic": "Design", "chatType": "group"}]},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 3
        assert result["user"] == {}
        assert result["team_count"] == 1
        assert result["chat_count"] == 1
        mock_log.set.assert_called_once_with(
            tool={"integration": "microsoft_teams", "action": "gather_context"}
        )
        mock_log.debug.assert_called_once_with(
            "[TOOL] Teams /me fetch failed", error_type="RuntimeError"
        )

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_teams_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "displayName": "Ada"},
            RuntimeError("teams down"),
            {"value": [{"id": "c1", "topic": "Design", "chatType": "group"}]},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["display_name"] == "Ada"
        assert result["teams"] == []
        assert result["team_count"] == 0
        assert result["chat_count"] == 1
        mock_log.debug.assert_called_once_with(
            "[TOOL] Teams joinedTeams fetch failed", error_type="RuntimeError"
        )

    @patch(f"{TEAMS_MODULE}.proxy_request_sync")
    @patch(f"{TEAMS_MODULE}.log")
    def test_chats_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {"id": "me1", "displayName": "Ada"},
            {"value": [{"id": "t1", "displayName": "Eng"}]},
            RuntimeError("chats down"),
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["display_name"] == "Ada"
        assert result["team_count"] == 1
        assert result["recent_chats"] == []
        assert result["chat_count"] == 0
        assert result["unread_chat_count"] == 0
        mock_log.debug.assert_called_once_with(
            "[TOOL] Teams chats fetch failed", error_type="RuntimeError"
        )


# =============================================================================
# REDDIT TOOLS
# =============================================================================

REDDIT_MODULE = "app.agents.tools.integrations.reddit_tool"
REDDIT_ME_ENDPOINT = "https://oauth.reddit.com/api/v1/me"
REDDIT_SUBS_ENDPOINT = "https://oauth.reddit.com/subreddits/mine/subscriber"
REDDIT_MESSAGES_ENDPOINT = "https://oauth.reddit.com/message/unread"
REDDIT_HEADERS = {"User-Agent": "GAIA/1.0"}
REDDIT_LIMIT_QUERY = {"limit": 5}


class TestRedditGatherContext:
    def _register(self) -> tuple[MagicMock, dict[str, Callable[..., Any]]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.reddit_tool import register_reddit_custom_tools

        names = register_reddit_custom_tools(composio)
        assert names == ["REDDIT_CUSTOM_GATHER_CONTEXT"]
        return composio, captured

    def _assert_proxy_call(
        self,
        mock_proxy: MagicMock,
        index: int,
        *,
        endpoint: str,
        query: dict[str, Any] | None = None,
    ) -> None:
        expected: dict[str, Any] = {
            "user_id": FAKE_USER_ID,
            "toolkit": "REDDIT",
            "endpoint": endpoint,
            "method": "GET",
            "headers": REDDIT_HEADERS,
        }
        if query is not None:
            expected["query"] = query
        assert mock_proxy.call_args_list[index].kwargs == expected

    def test_registers_custom_tool_with_reddit_toolkit(self) -> None:
        composio, _ = self._register()
        assert composio.tool_kwargs == [{"toolkit": "REDDIT"}]

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_basic_success(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {
                "name": "ada",
                "id": "u1",
                "link_karma": 10,
                "comment_karma": 5,
                "total_karma": 15,
                "icon_img": "https://reddit/avatar.png",
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

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 3
        self._assert_proxy_call(mock_proxy, 0, endpoint=REDDIT_ME_ENDPOINT)
        self._assert_proxy_call(
            mock_proxy, 1, endpoint=REDDIT_SUBS_ENDPOINT, query=REDDIT_LIMIT_QUERY
        )
        self._assert_proxy_call(
            mock_proxy, 2, endpoint=REDDIT_MESSAGES_ENDPOINT, query=REDDIT_LIMIT_QUERY
        )
        assert result == {
            "user": {
                "name": "ada",
                "id": "u1",
                "link_karma": 10,
                "comment_karma": 5,
                "total_karma": 15,
                "icon_img": "https://reddit/avatar.png",
                "is_gold": True,
            },
            "subscribed_subreddits": [
                {"name": "python", "title": "Python subreddit", "subscribers": 1000}
            ],
            "unread_messages": [
                {"id": "msg1", "subject": "Hey", "author": "bob", "created_utc": 123}
            ],
            "unread_message_count": 1,
        }

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_missing_fields_fall_back_to_defaults(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {"name": "ada"},
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "python"}},
                        {"data": {"display_name": "empty", "title": "T"}},
                    ]
                }
            },
            {"data": {"children": [{"data": {"id": "m1"}}]}},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"] == {
            "name": "ada",
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        }
        assert result["subscribed_subreddits"] == [
            {"name": "python", "title": "", "subscribers": 0},
            {"name": "empty", "title": "T", "subscribers": 0},
        ]
        assert result["unread_messages"] == [
            {"id": "m1", "subject": "", "author": None, "created_utc": None}
        ]
        assert result["unread_message_count"] == 1
        mock_log.error.assert_not_called()

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_title_and_subject_truncated_to_80_chars(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {},
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "long", "title": "t" * 200}}
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {"data": {"id": "m1", "subject": "s" * 200}}
                    ]
                }
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["subscribed_subreddits"][0]["title"] == "t" * 80
        assert result["unread_messages"][0]["subject"] == "s" * 80
        mock_log.error.assert_not_called()

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_none_responses_become_defaults(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [None, None, None]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"] == {
            "name": None,
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        }
        assert result["subscribed_subreddits"] == []
        assert result["unread_messages"] == []
        assert result["unread_message_count"] == 0
        mock_log.error.assert_not_called()

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_empty_payloads_yield_empty_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [{}, {}, {}]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"] == {
            "name": None,
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        }
        assert result["subscribed_subreddits"] == []
        assert result["unread_messages"] == []
        assert result["unread_message_count"] == 0
        mock_log.error.assert_not_called()

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_multiple_items_preserve_order_and_count(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = [
            {},
            {
                "data": {
                    "children": [
                        {"data": {"display_name": "a"}},
                        {"data": {"display_name": "b"}},
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {"data": {"id": "m1"}},
                        {"data": {"id": "m2"}},
                        {"data": {"id": "m3"}},
                    ]
                }
            },
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert [s["name"] for s in result["subscribed_subreddits"]] == ["a", "b"]
        assert [m["id"] for m in result["unread_messages"]] == ["m1", "m2", "m3"]
        assert result["unread_message_count"] == 3

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_me_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        me_error = RuntimeError("me down")
        mock_proxy.side_effect = [
            me_error,
            {"data": {"children": [{"data": {"display_name": "python"}}]}},
            {"data": {"children": [{"data": {"id": "m1"}}]}},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert mock_proxy.call_count == 3
        assert result["user"] == {
            "name": None,
            "id": None,
            "link_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "icon_img": None,
            "is_gold": False,
        }
        assert len(result["subscribed_subreddits"]) == 1
        assert len(result["unread_messages"]) == 1
        mock_log.set.assert_called_once_with(
            user_id=FAKE_USER_ID, endpoint=REDDIT_ME_ENDPOINT, toolkit="REDDIT"
        )
        mock_log.error.assert_called_once_with(
            "[TOOL] Reddit /me fetch failed", exc=me_error
        )

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_subreddits_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        subs_error = RuntimeError("subs down")
        mock_proxy.side_effect = [
            {"name": "ada"},
            subs_error,
            {"data": {"children": [{"data": {"id": "m1"}}]}},
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["name"] == "ada"
        assert result["subscribed_subreddits"] == []
        assert result["unread_message_count"] == 1
        mock_log.set.assert_called_once_with(
            user_id=FAKE_USER_ID, endpoint=REDDIT_SUBS_ENDPOINT, toolkit="REDDIT"
        )
        mock_log.error.assert_called_once_with(
            "[TOOL] Reddit subreddits fetch failed", exc=subs_error
        )

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    @patch(f"{REDDIT_MODULE}.log")
    def test_messages_failure_keeps_other_sections(
        self, mock_log: MagicMock, mock_proxy: MagicMock
    ) -> None:
        messages_error = RuntimeError("messages down")
        mock_proxy.side_effect = [
            {"name": "ada"},
            {"data": {"children": [{"data": {"display_name": "python"}}]}},
            messages_error,
        ]

        _, captured = self._register()
        result = captured["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY
        )

        assert result["user"]["name"] == "ada"
        assert len(result["subscribed_subreddits"]) == 1
        assert result["unread_messages"] == []
        assert result["unread_message_count"] == 0
        mock_log.set.assert_called_once_with(
            user_id=FAKE_USER_ID, endpoint=REDDIT_MESSAGES_ENDPOINT, toolkit="REDDIT"
        )
        mock_log.error.assert_called_once_with(
            "[TOOL] Reddit unread messages fetch failed", exc=messages_error
        )

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_missing_user_id_raises_app_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(AppError) as exc_info:
            captured["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})

        assert exc_info.value.status_code == 500
        assert exc_info.value.message == "Missing user_id in auth_credentials"
        assert (
            exc_info.value.why
            == "CUSTOM_GATHER_CONTEXT requires a user-scoped auth context"
        )
        mock_proxy.assert_not_called()

    @patch(f"{REDDIT_MODULE}.proxy_request_sync")
    def test_empty_user_id_raises_app_error(self, mock_proxy: MagicMock) -> None:
        _, captured = self._register()
        with pytest.raises(AppError, match="Missing user_id in auth_credentials"):
            captured["CUSTOM_GATHER_CONTEXT"](
                GatherContextInput(), EXECUTE_REQUEST, {"user_id": ""}
            )
        mock_proxy.assert_not_called()
