"""Unit tests for app.agents.tools.integrations.microsoft_teams_tool.

Only the true I/O boundary is faked: `proxy_request_sync` (the Graph API
route) and the shared `log` object. Everything else — user-id validation,
request assembly, response unwrapping, unread counting, preview truncation —
runs for real, so the assertions below pin the exact Graph payloads the
proxy would send and the exact snapshot dict the agent receives.
"""

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.microsoft_teams_tool import (
    GRAPH_API_BASE,
    TEAMS_TOOLKIT,
    register_microsoft_teams_custom_tools,
)
from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput

MODULE = "app.agents.tools.integrations.microsoft_teams_tool"
AUTH: dict[str, Any] = {"user_id": "user-42"}

ME_PAYLOAD: dict[str, Any] = {
    "id": "u-1",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.com",
    "userPrincipalName": "ada@corp.example",
    "extra": "ignored",
}
TEAMS_PAYLOAD: dict[str, Any] = {
    "value": [
        {"id": "t-1", "displayName": "Platform", "description": "Core platform team"},
        {"id": "t-2", "displayName": "Design", "description": None},
    ]
}
LONG_PREVIEW = (
    "Design review moved to Thursday — please bring the updated flows and "
    "the accessibility notes so we can lock the launch checklist. " * 2
)  # 264 chars — must be truncated


def _register(composio: Any | None = None) -> dict[str, Any]:
    """Register the tools against the given (or a fresh) Composio mock."""
    captured: dict[str, Any] = {}
    if composio is None:
        composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_microsoft_teams_custom_tools(composio)
    return captured


def _gather_context(
    proxy_results: list[Any],
    auth: dict[str, Any] = AUTH,
) -> tuple[dict[str, Any], MagicMock, MagicMock, MagicMock]:
    """Call CUSTOM_GATHER_CONTEXT with canned proxy responses.

    `proxy_results` is consumed as the side_effect of `proxy_request_sync`
    (return values or exceptions, in call order). Returns
    (result, proxy mock, log.debug mock, log.set mock).
    """
    tools = _register()
    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=proxy_results) as proxy,
        patch(f"{MODULE}.log.debug") as debug_log,
        patch(f"{MODULE}.log.set") as log_set,
    ):
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), MagicMock(), auth)
    return result, proxy, debug_log, log_set


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_gather_context_under_the_teams_toolkit(self) -> None:
        composio = MagicMock()
        registered: list[str] = []
        seen_kwargs: list[dict[str, Any]] = []

        def custom_tool(**kwargs: Any) -> Any:
            seen_kwargs.append(kwargs)

            def decorator(fn: Any) -> Any:
                registered.append(fn.__name__)
                return fn

            return decorator

        composio.tools.custom_tool = custom_tool
        names = register_microsoft_teams_custom_tools(composio)

        assert seen_kwargs == [{"toolkit": "MICROSOFT_TEAMS"}]
        assert registered == ["CUSTOM_GATHER_CONTEXT"]
        # Every returned name must correspond to a function that was actually
        # registered — a name in the list with no tool behind it is a tool the
        # agent can select and never execute.
        assert names == [f"{TEAMS_TOOLKIT}_{fn}" for fn in registered]
        assert names == ["MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT"]

    def test_constants_are_stable(self) -> None:
        assert TEAMS_TOOLKIT == "MICROSOFT_TEAMS"
        assert GRAPH_API_BASE == "https://graph.microsoft.com/v1.0"

    def test_gather_context_docstring_is_the_agent_facing_contract(self) -> None:
        # The model selects tools by docstring; a terse or missing docstring
        # would strip the parameter contract.
        tools = _register()
        doc = tools["CUSTOM_GATHER_CONTEXT"].__doc__
        assert doc is not None
        assert "context snapshot" in doc
        assert "joined teams" in doc


# ---------------------------------------------------------------------------
# User-id validation
# ---------------------------------------------------------------------------


class TestUserId:
    @pytest.mark.parametrize("credentials", [{}, {"user_id": ""}, {"user_id": None}])
    def test_missing_user_id_is_rejected_before_any_proxy_call(
        self, credentials: dict[str, Any]
    ) -> None:
        tools = _register()
        with (
            patch(f"{MODULE}.proxy_request_sync") as proxy,
            patch(f"{MODULE}.log.set") as log_set,
        ):
            with pytest.raises(ValueError) as excinfo:
                tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), MagicMock(), credentials)

        assert str(excinfo.value) == "Missing user_id in auth_credentials"
        proxy.assert_not_called()
        # log.set runs before the guard — the failure is attributed to the
        # integration even when credentials are unusable.
        log_set.assert_called_once_with(
            tool={"integration": "microsoft_teams", "action": "gather_context"}
        )


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_returns_the_full_teams_snapshot(self) -> None:
        chats_payload = {
            "value": [
                {
                    "id": "c-1",
                    "topic": "Launch",
                    "chatType": "group",
                    "lastMessagePreview": {
                        "isRead": False,
                        "body": {"content": LONG_PREVIEW},
                    },
                },
                {
                    "id": "c-2",
                    "topic": "Random",
                    "chatType": "oneOnOne",
                    "lastMessagePreview": {"isRead": True, "body": {"content": "hi"}},
                },
                {
                    "id": "c-3",
                    "topic": None,
                    "chatType": "group",
                    # preview without isRead — must default to read
                    "lastMessagePreview": {"body": {"content": "no isRead flag"}},
                },
                {
                    "id": "c-4",
                    "topic": "Quiet",
                    "chatType": "meeting",
                    "extra": "ignored",  # no preview at all
                },
            ]
        }
        result, proxy, debug_log, log_set = _gather_context(
            [ME_PAYLOAD, TEAMS_PAYLOAD, chats_payload]
        )

        log_set.assert_called_once_with(
            tool={"integration": "microsoft_teams", "action": "gather_context"}
        )
        debug_log.assert_not_called()
        assert proxy.call_args_list == [
            call(
                user_id="user-42",
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me",
                method="GET",
                query={"$select": "id,displayName,mail,userPrincipalName"},
            ),
            call(
                user_id="user-42",
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me/joinedTeams",
                method="GET",
                query={"$select": "id,displayName,description"},
            ),
            call(
                user_id="user-42",
                toolkit=TEAMS_TOOLKIT,
                endpoint=f"{GRAPH_API_BASE}/me/chats",
                method="GET",
                query={"$expand": "lastMessagePreview", "$top": 10},
            ),
        ]
        assert result == {
            "user": {"id": "u-1", "display_name": "Ada Lovelace", "email": "ada@example.com"},
            "teams": [
                {"id": "t-1", "name": "Platform", "description": "Core platform team"},
                {"id": "t-2", "name": "Design", "description": None},
            ],
            "recent_chats": [
                {
                    "id": "c-1",
                    "topic": "Launch",
                    "chat_type": "group",
                    "last_message_preview": LONG_PREVIEW[:100],
                    "is_read": False,
                },
                {
                    "id": "c-2",
                    "topic": "Random",
                    "chat_type": "oneOnOne",
                    "last_message_preview": "hi",
                    "is_read": True,
                },
                {
                    "id": "c-3",
                    "topic": None,
                    "chat_type": "group",
                    "last_message_preview": "no isRead flag",
                    "is_read": True,
                },
                {
                    "id": "c-4",
                    "topic": "Quiet",
                    "chat_type": "meeting",
                    "last_message_preview": None,
                    "is_read": True,
                },
            ],
            "team_count": 2,
            "chat_count": 4,
            "unread_chat_count": 1,
        }

    def test_mail_falls_back_to_user_principal_name(self) -> None:
        result, _, debug_log, _ = _gather_context(
            [{"id": "u-1", "displayName": "Ada", "userPrincipalName": "ada@corp.example"}, {}, {}]
        )
        assert result["user"] == {
            "id": "u-1",
            "display_name": "Ada",
            "email": "ada@corp.example",
        }
        debug_log.assert_not_called()

    def test_email_is_none_when_mail_and_upn_are_absent(self) -> None:
        result, _, _, _ = _gather_context([{"id": "u-1", "displayName": "Ada"}, {}, {}])
        assert result["user"] == {"id": "u-1", "display_name": "Ada", "email": None}

    def test_falsy_proxy_payloads_yield_an_empty_snapshot(self) -> None:
        # A None payload is a normal, expected response — (result or {}) must
        # absorb it without tripping the broad except (no debug log).
        result, _, debug_log, _ = _gather_context([None, None, None])

        assert result == {
            "user": {"id": None, "display_name": None, "email": None},
            "teams": [],
            "recent_chats": [],
            "team_count": 0,
            "chat_count": 0,
            "unread_chat_count": 0,
        }
        debug_log.assert_not_called()

    def test_me_fetch_failure_is_logged_and_swallowed(self) -> None:
        # The /me failure must not abort the snapshot — teams and chats still
        # load; the user section stays the untouched empty dict.
        result, _, debug_log, _ = _gather_context(
            [RuntimeError("connection reset"), TEAMS_PAYLOAD, {"value": []}]
        )

        assert result["user"] == {}
        assert result["teams"] == [
            {"id": "t-1", "name": "Platform", "description": "Core platform team"},
            {"id": "t-2", "name": "Design", "description": None},
        ]
        assert result["team_count"] == 2
        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} Teams /me fetch failed", error_type="RuntimeError"
        )

    def test_joined_teams_fetch_failure_is_logged_and_swallowed(self) -> None:
        result, _, debug_log, _ = _gather_context(
            [ME_PAYLOAD, RuntimeError("403 denied"), {"value": []}]
        )

        assert result["user"] == {
            "id": "u-1",
            "display_name": "Ada Lovelace",
            "email": "ada@example.com",
        }
        assert result["teams"] == []
        assert result["team_count"] == 0
        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} Teams joinedTeams fetch failed", error_type="RuntimeError"
        )

    def test_chats_fetch_failure_is_logged_and_swallowed(self) -> None:
        result, _, debug_log, _ = _gather_context(
            [ME_PAYLOAD, TEAMS_PAYLOAD, RuntimeError("rate limited")]
        )

        assert result["recent_chats"] == []
        assert result["chat_count"] == 0
        assert result["unread_chat_count"] == 0
        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} Teams chats fetch failed", error_type="RuntimeError"
        )

    def test_total_fetch_failure_logs_all_three_sections(self) -> None:
        result, _, debug_log, _ = _gather_context(
            [RuntimeError("a"), RuntimeError("b"), RuntimeError("c")]
        )

        assert result == {
            "user": {},
            "teams": [],
            "recent_chats": [],
            "team_count": 0,
            "chat_count": 0,
            "unread_chat_count": 0,
        }
        assert debug_log.call_args_list == [
            ((f"{LogTag.TOOL} Teams /me fetch failed",), {"error_type": "RuntimeError"}),
            ((f"{LogTag.TOOL} Teams joinedTeams fetch failed",), {"error_type": "RuntimeError"}),
            ((f"{LogTag.TOOL} Teams chats fetch failed",), {"error_type": "RuntimeError"}),
        ]

    @pytest.mark.parametrize(
        ("chats", "expected_unread"),
        [
            # isRead: False -> unread
            ([{"id": "c1", "lastMessagePreview": {"isRead": False}}], 1),
            # isRead: True -> read
            ([{"id": "c1", "lastMessagePreview": {"isRead": True}}], 0),
            # no isRead flag -> defaults to read
            ([{"id": "c1", "lastMessagePreview": {"body": {"content": "hi"}}}], 0),
            # no preview at all -> read
            ([{"id": "c1", "topic": "t"}], 0),
            # mixed — only the explicit unread one counts
            (
                [
                    {"id": "c1", "lastMessagePreview": {"isRead": False}},
                    {"id": "c2", "lastMessagePreview": {"isRead": True}},
                    {"id": "c3", "lastMessagePreview": {"body": {"content": "x"}}},
                    {"id": "c4", "topic": "t"},
                ],
                1,
            ),
        ],
    )
    def test_unread_count_pins_preview_is_read_semantics(
        self, chats: list[dict[str, Any]], expected_unread: int
    ) -> None:
        result, _, debug_log, _ = _gather_context([ME_PAYLOAD, {"value": []}, {"value": chats}])

        assert result["unread_chat_count"] == expected_unread
        assert result["chat_count"] == len(chats)
        assert len(result["recent_chats"]) == len(chats)
        debug_log.assert_not_called()

    def test_chat_preview_is_truncated_to_100_chars(self) -> None:
        chats = [{"id": "c1", "lastMessagePreview": {"isRead": True, "body": {"content": LONG_PREVIEW}}}]
        result, _, _, _ = _gather_context([ME_PAYLOAD, {"value": []}, {"value": chats}])

        preview = result["recent_chats"][0]["last_message_preview"]
        assert preview == LONG_PREVIEW[:100]
        assert len(preview) == 100

    def test_preview_without_body_or_content_yields_empty_string(self) -> None:
        chats = [{"id": "c1", "lastMessagePreview": {"isRead": True}}]
        result, _, _, _ = _gather_context([ME_PAYLOAD, {"value": []}, {"value": chats}])

        assert result["recent_chats"][0]["last_message_preview"] == ""
        assert result["recent_chats"][0]["is_read"] is True

    def test_empty_preview_dict_is_treated_as_missing(self) -> None:
        # {} is falsy — the truthiness guards treat it as "no preview".
        chats = [{"id": "c1", "lastMessagePreview": {}}]
        result, _, _, _ = _gather_context([ME_PAYLOAD, {"value": []}, {"value": chats}])

        assert result["recent_chats"][0]["last_message_preview"] is None
        assert result["recent_chats"][0]["is_read"] is True
