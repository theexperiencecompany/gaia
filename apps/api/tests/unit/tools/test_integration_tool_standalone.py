"""Unit tests for app.agents.tools.integration_tool."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.integrations import MAX_SUGGESTED_FOR_LLM
from app.helpers.integration_helpers import build_search_patterns, generate_integration_slug

# ---------------------------------------------------------------------------
# Module-level patch for rate limiting
# ---------------------------------------------------------------------------
_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.integration_tool"

BOT_CONNECT_URL = "https://connect.example/tok"

UI_CONNECT_MESSAGE = (
    "Gmail needs to be connected. A connect button has been shown to the "
    "user — do NOT include any URL in your reply, the UI card handles it. "
    "Ask the user to click the connect button, then try again."
)


@pytest.fixture(autouse=True)
def mock_log() -> MagicMock:
    """Replace the module's wide-event logger so log call args are assertable."""
    with patch(f"{MODULE}.log") as m:
        yield m


def _cfg(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    return {"configurable": {"user_id": user_id}}


def _cfg_no_user() -> dict[str, Any]:
    return {"configurable": {}}


def _writer() -> MagicMock:
    return MagicMock()


def _make_integration(
    id: str = "gmail",
    name: str = "Gmail",
    available: bool = True,
    short_name: str = "",
    description: str = "Email",
    category: str = "email",
) -> MagicMock:
    """Create a mock OAuthIntegration."""
    mock = MagicMock()
    mock.id = id
    mock.name = name
    mock.available = available
    mock.short_name = short_name
    mock.description = description
    mock.category = category
    return mock


def _make_doc(
    integration_id: str,
    name: str,
    description: str = "desc",
    category: str = "cat",
    icon_url: str = "https://icon.example/icon.png",
    auth_type: str | None = None,
) -> SimpleNamespace:
    mcp_config = SimpleNamespace(auth_type=auth_type) if auth_type else None
    return SimpleNamespace(
        integration_id=integration_id,
        name=name,
        description=description,
        category=category,
        icon_url=icon_url,
        mcp_config=mcp_config,
    )


# ---------------------------------------------------------------------------
# Tests: build_search_patterns
# ---------------------------------------------------------------------------


class TestBuildSearchPatterns:
    def test_basic_split(self) -> None:
        from app.agents.tools.integration_tool import build_search_patterns

        result = build_search_patterns("Render deployment")
        assert "render" in result
        assert "deployment" in result

    def test_stopwords_removed(self) -> None:
        from app.agents.tools.integration_tool import build_search_patterns

        result = build_search_patterns("a tool for the web")
        assert "a" not in result
        assert "the" not in result
        assert "for" not in result
        assert "tool" in result
        assert "web" in result

    def test_short_words_removed(self) -> None:
        from app.agents.tools.integration_tool import build_search_patterns

        result = build_search_patterns("I go to school")
        # "I" (len 1) should be removed
        assert "i" not in result

    def test_empty_query(self) -> None:
        from app.agents.tools.integration_tool import build_search_patterns

        result = build_search_patterns("")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: list_integrations
# ---------------------------------------------------------------------------


class TestListIntegrations:
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("slack", "Slack", available=False),
            _make_integration("gmail", "Gmail"),
            _make_integration("notion", "Notion", description="Notes", category="productivity"),
        ],
    )
    async def test_happy_path_exact_payload(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Platform integrations split by status; unavailable ones excluded."""
        w = _writer()
        mock_gsw.return_value = w
        mock_status.return_value = {"gmail": True}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]

        assert result == {
            "connected": [
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "description": "Email",
                    "category": "email",
                    "connected": True,
                }
            ],
            "available": [
                {
                    "id": "notion",
                    "name": "Notion",
                    "description": "Notes",
                    "category": "productivity",
                    "connected": False,
                }
            ],
            "suggested": [],
        }
        # Only available platform IDs are checked, in catalog order.
        mock_status.assert_awaited_once_with(["gmail", "notion"], FAKE_USER_ID)
        mock_user_repo.list_for_user.assert_awaited_once_with(FAKE_USER_ID)
        mock_int_repo.find_custom_by_ids.assert_not_called()
        mock_int_repo.search_public.assert_not_called()
        # Empty suggestion list is streamed to the frontend (camelCase).
        w.assert_called_once_with(
            {"integration_list_data": {"hasSuggestions": False, "suggested": []}}
        )
        mock_log.set.assert_called_once_with(
            tool={"name": "list_integrations", "action": "list"}
        )

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_custom_integrations_exact_payload(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        """Custom Mongo-backed integrations join the lists with per-doc status."""
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_user_repo.list_for_user = AsyncMock(
            return_value=[
                SimpleNamespace(integration_id="custom-slack"),
                SimpleNamespace(integration_id="custom-notion"),
            ]
        )
        mock_int_repo.find_custom_by_ids = AsyncMock(
            return_value=[
                _make_doc("custom-slack", "Custom Slack", category="chat"),
                _make_doc("custom-notion", "Custom Notion", category="notes"),
            ]
        )
        mock_user_repo.is_connected = AsyncMock(side_effect=[True, False])

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]

        assert result == {
            "connected": [
                {
                    "id": "custom-slack",
                    "name": "Custom Slack",
                    "description": "desc",
                    "category": "chat",
                    "connected": True,
                }
            ],
            "available": [
                {
                    "id": "custom-notion",
                    "name": "Custom Notion",
                    "description": "desc",
                    "category": "notes",
                    "connected": False,
                }
            ],
            "suggested": [],
        }
        # The set of custom ids is passed through to the lookup...
        find_args = mock_int_repo.find_custom_by_ids.await_args.args[0]
        assert set(find_args) == {"custom-slack", "custom-notion"}
        mock_user_repo.is_connected.assert_any_await(FAKE_USER_ID, "custom-slack")
        mock_user_repo.is_connected.assert_any_await(FAKE_USER_ID, "custom-notion")

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_search_streams_and_returns_suggestions(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """A non-empty query triggers a public search; results are streamed + returned."""
        w = _writer()
        mock_gsw.return_value = w
        mock_status.return_value = {}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.search_public = AsyncMock(
            return_value=[_make_doc("alpha", "Alpha", icon_url="https://i/alpha.png", auth_type="oauth2")]
        )

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), search_public_query="  email Tools "
        )

        expected_suggested = [
            {
                "id": "alpha",
                "name": "Alpha",
                "description": "desc",
                "category": "cat",
                "icon_url": "https://i/alpha.png",
                "auth_type": "oauth2",
                "relevance_score": 1.0,
                "slug": generate_integration_slug(name="Alpha", category="cat"),
            }
        ]
        assert result == {"connected": [], "available": [], "suggested": expected_suggested}

        mock_int_repo.search_public.assert_awaited_once_with(
            words=build_search_patterns("email Tools"),
            query="email Tools",
            exclude_ids=[],
            limit=MAX_SUGGESTED_FOR_LLM,
        )
        w.assert_called_once_with(
            {
                "integration_list_data": {
                    "hasSuggestions": True,
                    "suggested": [
                        {
                            "id": "alpha",
                            "name": "Alpha",
                            "description": "desc",
                            "category": "cat",
                            "iconUrl": "https://i/alpha.png",
                            "authType": "oauth2",
                            "relevanceScore": 1.0,
                            "slug": generate_integration_slug(name="Alpha", category="cat"),
                        }
                    ],
                }
            }
        )
        mock_log.info.assert_any_call("[TOOL] Searching public integrations", query="email Tools")
        mock_log.info.assert_any_call(
            "[TOOL] Found public integration", integration_id="alpha", integration_name="Alpha"
        )
        mock_log.info.assert_any_call("[TOOL] Found public integrations", integration_count=1)

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_search_auth_type_none_without_mcp_config(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.search_public = AsyncMock(return_value=[_make_doc("beta", "Beta")])

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), search_public_query="beta"
        )

        assert result["suggested"] == [
            {
                "id": "beta",
                "name": "Beta",
                "description": "desc",
                "category": "cat",
                "icon_url": "https://icon.example/icon.png",
                "auth_type": None,
                "relevance_score": 1.0,
                "slug": generate_integration_slug(name="Beta", category="cat"),
            }
        ]

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail"), _make_integration("notion", "Notion", category="notes")],
    )
    async def test_search_excludes_already_listed_and_connected_ids(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        """User-owned (connected/available) ids are excluded from the search."""
        w = _writer()
        mock_gsw.return_value = w
        mock_status.return_value = {"gmail": True, "notion": False}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.search_public = AsyncMock(
            return_value=[_make_doc("alpha", "Alpha", icon_url="https://i/alpha.png", auth_type="oauth2")]
        )

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), search_public_query="email"
        )

        assert [s["id"] for s in result["suggested"]] == ["alpha"]
        await_args = mock_int_repo.search_public.await_args.kwargs
        assert set(await_args["exclude_ids"]) == {"gmail", "notion"}

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_search_failure_does_not_fail_listing(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """A failing marketplace search is logged and skipped, not fatal."""
        w = _writer()
        mock_gsw.return_value = w
        mock_status.return_value = {}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.search_public = AsyncMock(side_effect=RuntimeError("boom"))

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), search_public_query="email"
        )

        assert result == {"connected": [], "available": [], "suggested": []}
        w.assert_called_once_with(
            {"integration_list_data": {"hasSuggestions": False, "suggested": []}}
        )
        mock_log.warning.assert_called_once_with(
            "[TOOL] Failed to search public integrations", error_type="RuntimeError"
        )

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_whitespace_only_query_skips_search(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_user_repo.list_for_user = AsyncMock(return_value=[])

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), search_public_query="   "
        )

        assert result == {"connected": [], "available": [], "suggested": []}
        mock_int_repo.search_public.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_no_user_id_returns_exact_error(self, mock_gsw: MagicMock) -> None:
        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg_no_user())  # type: ignore[attr-defined]
        assert result == "Error: User ID not found in configuration."

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_multiple_integrations_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration()])
    async def test_service_error_returns_exact_error(
        self, mock_status: AsyncMock, mock_gsw: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result == "Error listing integrations: err"
        mock_log.error.assert_called_once_with(
            "[TOOL] Error listing integrations", error_type="RuntimeError"
        )


# ---------------------------------------------------------------------------
# Tests: connect_integration
# ---------------------------------------------------------------------------


class TestConnectIntegration:
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_initiates_connection_exact_output(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock, mock_log: MagicMock
    ) -> None:
        """Bot context: writer progress + card payload, minted URL relayed verbatim."""
        w = _writer()
        mock_gsw.return_value = w
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "bot"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids=["gmail"]
            )

        assert result == (
            "Gmail needs to be connected. The user is on a text-only platform (no UI). "
            "Include this URL verbatim in your result so the comms agent can relay it to "
            f"the user, and tell them it is valid for 1 hour: {BOT_CONNECT_URL}"
        )
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)
        mock_build.assert_awaited_once_with(FAKE_USER_ID, "gmail")
        w.assert_has_calls(
            [
                call({"progress": "Initiating Gmail connection..."}),
                call(
                    {
                        "integration_connection_required": {
                            "integration_id": "gmail",
                            "message": "To use Gmail features, please connect your account.",
                        }
                    }
                ),
            ]
        )
        assert w.call_count == 2
        mock_log.set.assert_called_once_with(
            tool={"name": "connect_integration", "action": "connect"}
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_normalizes_and_deduplicates_ids(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """IDs are lowercased, stripped, deduplicated and emptied entries dropped."""
        w = _writer()
        mock_gsw.return_value = w
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "bot"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids=["  GMAIL ", "gmail", "Gmail", "   "]
            )

        assert BOT_CONNECT_URL in result
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)
        mock_build.assert_awaited_once_with(FAKE_USER_ID, "gmail")
        assert w.call_count == 2

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_string_input_is_widened(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """A bare string integration id is handled like a single-element list."""
        mock_gsw.return_value = _writer()
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "bot"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids="gmail"
            )

        assert BOT_CONNECT_URL in result
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("notion", "Notion", available=False, category="notes"),
            _make_integration("gmail", "Gmail"),
        ],
    )
    async def test_unavailable_and_available_exact_join(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids=["notion", "gmail"]
            )

        assert result == (
            "⏳ Notion is not available yet. Coming soon!\n" + UI_CONNECT_MESSAGE
        )
        # The unavailable integration is never status-checked.
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        side_effect=[True, False],
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("gmail", "Gmail"),
            _make_integration("slack", "Slack", category="chat"),
        ],
    )
    async def test_already_connected_exact_join(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids=["gmail", "slack"]
            )

        assert result == ("✅ Gmail is already connected!\n" + UI_CONNECT_MESSAGE.replace("Gmail", "Slack"))
        mock_check.assert_any_await("gmail", FAKE_USER_ID)
        mock_check.assert_any_await("slack", FAKE_USER_ID)
        # Only the not-yet-connected integration gets a link.
        mock_build.assert_awaited_once_with(FAKE_USER_ID, "slack")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.build_connect_link_url", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("gmail", "Gmail"),
            _make_integration("slack", "Slack", category="chat"),
        ],
    )
    async def test_not_found_and_connect_exact_join(
        self, mock_check: AsyncMock, mock_build: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """Unknown ids produce the available-IDs hint and processing continues."""
        mock_gsw.return_value = _writer()
        mock_build.return_value = BOT_CONNECT_URL

        from app.agents.tools.integration_tool import connect_integration

        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]
                config=_cfg(), integration_ids=["nonexistent", "gmail"]
            )

        assert result == (
            "❌ 'nonexistent' not found. Available IDs: gmail, slack\n" + UI_CONNECT_MESSAGE
        )
        mock_build.assert_awaited_once_with(FAKE_USER_ID, "gmail")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("gmail", "Gmail"),
            _make_integration("notion", "Notion", category="notes"),
            _make_integration("slack", "Slack", category="chat"),
            _make_integration("asana", "Asana", category="pm"),
            _make_integration("clickup", "ClickUp", category="pm"),
        ],
    )
    async def test_not_found_exact_available_ids_without_ellipsis(
        self, mock_gsw: MagicMock
    ) -> None:
        """Exactly five available IDs render without a trailing ellipsis."""
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_ids=["nonexistent"]
        )
        assert result == (
            "❌ 'nonexistent' not found. Available IDs: gmail, notion, slack, asana, clickup"
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("gmail", "Gmail"),
            _make_integration("notion", "Notion", category="notes"),
            _make_integration("slack", "Slack", category="chat"),
            _make_integration("asana", "Asana", category="pm"),
            _make_integration("clickup", "ClickUp", category="pm"),
            _make_integration("todoist", "Todoist", category="pm"),
        ],
    )
    async def test_not_found_truncates_available_ids_with_ellipsis(
        self, mock_gsw: MagicMock
    ) -> None:
        """More than five available IDs are truncated with a trailing ellipsis."""
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_ids=["nonexistent"]
        )
        assert result == (
            "❌ 'nonexistent' not found. "
            "Available IDs: gmail, notion, slack, asana, clickup..."
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail", available=False)])
    async def test_unavailable_exact_message(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_ids=["gmail"]
        )
        assert result == "⏳ Gmail is not available yet. Coming soon!"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_empty_list_returns_exact_noop(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_ids=[]
        )
        assert result == "No integrations to connect."

    async def test_no_user_id_returns_exact_error(self) -> None:
        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), integration_ids=["gmail"]
        )
        assert result == "Error: User ID not found in configuration."

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_service_error_returns_exact_error(
        self, mock_check: AsyncMock, mock_gsw: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_ids=["gmail"]
        )
        assert result == "Error connecting integrations: err"
        mock_log.error.assert_called_once_with(
            "[TOOL] Error connecting integrations",
            integration_ids=["gmail"],
            error_type="RuntimeError",
        )


# ---------------------------------------------------------------------------
# Tests: check_integrations_status
# ---------------------------------------------------------------------------


class TestCheckIntegrationsStatus:
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gm")],
    )
    async def test_connected_exact_output(self, mock_check: AsyncMock, mock_log: MagicMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert result == "Gmail: ✅ Connected"
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)
        mock_log.set.assert_called_once_with(
            tool={"name": "check_integrations_status", "action": "check"}
        )

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_not_connected_exact_output(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert result == "Gmail: ⚪ Not Connected"

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Google Mail", short_name="gm")],
    )
    async def test_matches_by_id(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert result == "Google Mail: ✅ Connected"
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Google Mail", short_name="gm")],
    )
    async def test_matches_by_name(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=[" Google Mail "]
        )
        assert result == "Google Mail: ✅ Connected"
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Google Mail", short_name="gm")],
    )
    async def test_matches_by_short_name(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gm"]
        )
        assert result == "Google Mail: ✅ Connected"
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail", short_name="gm")])
    async def test_not_found_exact_output(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["zzz"]
        )
        assert result == "❓ zzz: Not found"

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _make_integration("gmail", "Gmail", short_name="gm"),
            _make_integration("notion", "Notion", category="notes"),
        ],
    )
    async def test_multiple_names_exact_join(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["nope", "gmail"]
        )
        assert result == "❓ nope: Not found\nGmail: ✅ Connected"
        mock_check.assert_awaited_once_with("gmail", FAKE_USER_ID)

    async def test_no_user_id_returns_exact_error(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), integration_names=["gmail"]
        )
        assert result == "Error: User ID not found in configuration."

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration("gmail", "Gmail")])
    async def test_service_error_returns_exact_error(
        self, mock_check: AsyncMock, mock_log: MagicMock
    ) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert result == "Error checking status: err"
        mock_log.error.assert_called_once_with(
            "[TOOL] Error checking integration status", error_type="RuntimeError"
        )


# ---------------------------------------------------------------------------
# Tests: suggest_integrations (delegates to list_integrations)
# ---------------------------------------------------------------------------


class TestSuggestIntegrations:
    @patch(f"{MODULE}.list_integrations")
    async def test_delegates_with_exact_args_and_returns(
        self, mock_list: MagicMock
    ) -> None:
        sentinel = {"connected": [], "available": [], "suggested": []}
        mock_list.ainvoke = AsyncMock(return_value=sentinel)
        cfg = _cfg()

        from app.agents.tools.integration_tool import suggest_integrations

        result = await suggest_integrations.coroutine(config=cfg, query="email tools")  # type: ignore[attr-defined]

        assert result is sentinel
        mock_list.ainvoke.assert_awaited_once_with({"search_public_query": "email tools"}, config=cfg)
