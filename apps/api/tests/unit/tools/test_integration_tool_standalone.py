"""Unit tests for app.agents.tools.integration_tool."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.integrations import MAX_SUGGESTED_FOR_LLM
from app.db.repositories.user_integrations import user_integration_repository
from tests.helpers import captured_wide_event

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


def _cfg(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    return {"configurable": {"user_id": user_id}}


def _cfg_no_user() -> dict[str, Any]:
    return {"configurable": {}}


def _writer() -> MagicMock:
    return MagicMock()


def _make_integration(
    integration_id: str = "gmail",
    name: str = "Gmail",
    available: bool = True,
    short_name: str = "",
    description: str = "Email",
    category: str = "email",
) -> MagicMock:
    """Create a mock OAuthIntegration."""
    mock = MagicMock()
    mock.id = integration_id
    mock.name = name
    mock.available = available
    mock.short_name = short_name
    mock.description = description
    mock.category = category
    return mock


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


def _custom_doc(
    integration_id: str,
    name: str,
    description: str,
    category: str,
) -> MagicMock:
    doc = MagicMock()
    doc.integration_id = integration_id
    doc.name = name
    doc.description = description
    doc.category = category
    return doc


async def _list(config: dict[str, Any], search: str | None = None):
    from app.agents.tools.integration_tool import list_integrations

    return await list_integrations.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
        config=config, search_public_query=search
    )


class TestListIntegrations:
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_happy_path_empty_stamps_the_wide_event(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_repo.list_for_user = AsyncMock(return_value=[])

        async with captured_wide_event() as event:
            result = await _list(_cfg())

        assert result == {"connected": [], "available": [], "suggested": []}
        assert event["tool"] == {"name": "list_integrations", "action": "list"}

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            # Unavailable FIRST: a `break` (instead of `continue`) here would drop
            # every integration after it, so the exact lists below catch it.
            _make_integration("slack", "Slack", available=False),
            _make_integration("gmail", "Gmail", description="Email", category="email"),
            _make_integration("notion", "Notion", description="Notes", category="docs"),
            # Available but absent from the status map — the default must be False
            # (available), never True (connected).
            _make_integration("linear", "Linear", description="Issues", category="pm"),
        ],
    )
    async def test_platform_partition_is_exact_and_excludes_unavailable(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {"gmail": True, "notion": False}
        mock_repo.list_for_user = AsyncMock(return_value=[])

        result = await _list(_cfg())

        # Status is checked for exactly the available ids, for this user.
        mock_status.assert_awaited_once_with(["gmail", "notion", "linear"], FAKE_USER_ID)
        # Connected vs available is decided by status, every field is carried
        # through verbatim, the unavailable integration never appears, and the
        # status-map miss (linear) defaults to available.
        assert result["connected"] == [
            {
                "id": "gmail",
                "name": "Gmail",
                "description": "Email",
                "category": "email",
                "connected": True,
            }
        ]
        assert result["available"] == [
            {
                "id": "notion",
                "name": "Notion",
                "description": "Notes",
                "category": "docs",
                "connected": False,
            },
            {
                "id": "linear",
                "name": "Linear",
                "description": "Issues",
                "category": "pm",
                "connected": False,
            },
        ]

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_custom_integrations_partition_is_exact(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_repo.list_for_user = AsyncMock(
            return_value=[MagicMock(integration_id="c1"), MagicMock(integration_id="c2")]
        )
        mock_int_repo.find_custom_by_ids = AsyncMock(
            return_value=[
                _custom_doc("c1", "Sentry", "Errors", "observability"),
                _custom_doc("c2", "Linear", "Issues", "pm"),
            ]
        )
        # c1 connected, c2 not — is_connected drives the split per-doc.
        mock_repo.is_connected = AsyncMock(side_effect=[True, False])

        result = await _list(_cfg())

        # The user's integrations are listed for this user, the custom docs are
        # fetched by their ids (order is a set, so compare as a set), and each
        # doc's connection is checked for this user by that doc's id.
        mock_repo.list_for_user.assert_awaited_once_with(FAKE_USER_ID)
        assert set(mock_int_repo.find_custom_by_ids.await_args.args[0]) == {"c1", "c2"}
        assert mock_repo.is_connected.await_args_list == [
            call(FAKE_USER_ID, "c1"),
            call(FAKE_USER_ID, "c2"),
        ]
        assert result["connected"] == [
            {
                "id": "c1",
                "name": "Sentry",
                "description": "Errors",
                "category": "observability",
                "connected": True,
            }
        ]
        assert result["available"] == [
            {
                "id": "c2",
                "name": "Linear",
                "description": "Issues",
                "category": "pm",
                "connected": False,
            }
        ]

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_listed_custom_ids_are_excluded_from_public_search_exactly(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_repo.list_for_user = AsyncMock(return_value=[MagicMock(integration_id="c1")])
        mock_int_repo.find_custom_by_ids = AsyncMock(
            return_value=[_custom_doc("c1", "Sentry", "Errors", "observability")]
        )
        mock_repo.is_connected = AsyncMock(return_value=True)
        mock_int_repo.search_public = AsyncMock(return_value=[])

        await _list(_cfg(), search="monitoring")

        assert mock_int_repo.search_public.await_args.kwargs["exclude_ids"] == ["c1"]

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_no_custom_integrations_skips_the_lookup(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        # An empty user set must short-circuit before find_custom_by_ids runs.
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}
        mock_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.find_custom_by_ids = AsyncMock(return_value=[])

        result = await _list(_cfg())

        assert result["connected"] == []
        assert result["available"] == []
        mock_int_repo.find_custom_by_ids.assert_not_awaited()

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail"), _make_integration("notion", "Notion")],
    )
    async def test_search_streams_and_returns_exact_suggestions(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        writer = _writer()
        mock_gsw.return_value = writer
        # gmail connected, notion available — both must be excluded from search.
        mock_status.return_value = {"gmail": True, "notion": False}
        mock_repo.list_for_user = AsyncMock(return_value=[])
        suggested_doc = MagicMock()
        suggested_doc.integration_id = "pub-1"
        suggested_doc.name = "Datadog"
        suggested_doc.description = "Monitoring"
        suggested_doc.category = "observability"
        suggested_doc.icon_url = "https://icons.example/dd.png"
        suggested_doc.mcp_config = MagicMock(auth_type="oauth")
        mock_int_repo.search_public = AsyncMock(return_value=[suggested_doc])

        with patch(
            f"{MODULE}.generate_integration_slug", return_value="datadog-mcp-observability"
        ) as mock_slug:
            result = await _list(_cfg(), search="monitoring")

        # The marketplace query carries the split words, the raw query, and the
        # per-LLM cap; the slug is built from the doc's own name and category.
        search_call = mock_int_repo.search_public.await_args
        assert search_call.kwargs["words"] == ["monitoring"]
        assert search_call.kwargs["query"] == "monitoring"
        assert search_call.kwargs["limit"] == MAX_SUGGESTED_FOR_LLM
        # The user's existing connected + available integrations are excluded by
        # id (a set, so compare unordered).
        assert set(search_call.kwargs["exclude_ids"]) == {"gmail", "notion"}
        mock_slug.assert_called_once_with(name="Datadog", category="observability")
        assert result["suggested"] == [
            {
                "id": "pub-1",
                "name": "Datadog",
                "description": "Monitoring",
                "category": "observability",
                "icon_url": "https://icons.example/dd.png",
                "auth_type": "oauth",
                "relevance_score": 1.0,
                "slug": "datadog-mcp-observability",
            }
        ]
        # The camelCase payload streamed to the UI mirrors it, one row, flagged.
        writer.assert_called_once_with(
            {
                "integration_list_data": {
                    "hasSuggestions": True,
                    "suggested": [
                        {
                            "id": "pub-1",
                            "name": "Datadog",
                            "description": "Monitoring",
                            "category": "observability",
                            "iconUrl": "https://icons.example/dd.png",
                            "authType": "oauth",
                            "relevanceScore": 1.0,
                            "slug": "datadog-mcp-observability",
                        }
                    ],
                }
            }
        )

    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.user_integration_repository")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_search_failure_is_non_fatal_and_warns(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_repo: MagicMock,
        mock_int_repo: MagicMock,
    ) -> None:
        writer = _writer()
        mock_gsw.return_value = writer
        mock_status.return_value = {}
        mock_repo.list_for_user = AsyncMock(return_value=[])
        mock_int_repo.search_public = AsyncMock(side_effect=RuntimeError("chroma down"))

        async with captured_wide_event() as event:
            result = await _list(_cfg(), search="monitoring")

        # The listing still succeeds with no suggestions, and the failure is
        # surfaced on the event with the real exception type.
        assert result["suggested"] == []
        writer.assert_called_once_with(
            {"integration_list_data": {"hasSuggestions": False, "suggested": []}}
        )
        (warning,) = event["warnings"]
        assert "Failed to search public integrations" in warning["msg"]
        assert warning["error_type"] == "RuntimeError"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_no_user_id(self, mock_gsw: MagicMock) -> None:
        result = await _list(_cfg_no_user())
        assert result == "Error: User ID not found in configuration."

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_multiple_integrations_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration()])
    async def test_service_error(self, mock_status: AsyncMock, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()
        async with captured_wide_event() as event:
            result = await _list(_cfg())
        assert result == "Error listing integrations: err"
        # The failure is surfaced on the wide event with the real exception type.
        (error,) = event["errors"]
        assert "Error listing integrations" in error["msg"]
        assert error["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Tests: connect_integration
# ---------------------------------------------------------------------------


class TestConnectIntegration:
    @pytest.fixture(autouse=True)
    def _never_expired(self) -> Iterator[None]:
        """Pin the stored status to never-expired since these tests cover the tool's own behaviour, not the expired wording (see test_integration_checker.py)."""
        with patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=False)):
            yield

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_initiates_connection(self, mock_check: AsyncMock, mock_gsw: MagicMock) -> None:
        w = _writer()
        mock_gsw.return_value = w

        from app.agents.tools.integration_tool import connect_integration

        # The card and the copy that promises it now live together in
        # request_integration_connection, so the writer to watch is that
        # module's — and a source category has to exist for a card to be sent.
        with (
            patch("app.utils.integration_checker.get_stream_writer", return_value=w),
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": "ui"}},
            ),
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
                config=_cfg(), integration_ids=["gmail"]
            )
        assert "needs to be connected" in result
        integration_calls = [
            c for c in w.call_args_list if "integration_connection_required" in c[0][0]
        ]
        assert len(integration_calls) == 1

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_bot_context_includes_connect_url(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """On a bot platform the agent reply must carry the connect URL inline."""
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": "bot"}},
            ),
            patch("app.utils.integration_checker.get_stream_writer", return_value=_writer()),
            patch(
                "app.utils.integration_checker.build_connect_link_url",
                new=AsyncMock(return_value="https://app.example.com/connect/test-token"),
            ),
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
                config=_cfg(), integration_ids=["gmail"]
            )

        # Bot platforms get the minted login-free connect link inline (verbatim).
        assert "https://app.example.com/connect/test-token" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_the_connect_request_carries_this_integration_and_user(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """Minting for the wrong user hands one person another's connect flow, and losing the name leaves the agent telling the user "None" needs connecting."""
        mock_gsw.return_value = _writer()

        async def _link(user_id: str, integration_id: str) -> str | None:
            if (user_id, integration_id) == (FAKE_USER_ID, "gmail"):
                return "https://app.example.com/connect/for-this-user"
            return None

        from app.agents.tools.integration_tool import connect_integration

        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": "bot"}},
            ),
            patch("app.utils.integration_checker.get_stream_writer", return_value=_writer()),
            patch(
                "app.utils.integration_checker.build_connect_link_url",
                new=AsyncMock(side_effect=_link),
            ),
        ):
            result = await connect_integration.ainvoke(
                {"integration_ids": ["gmail"]}, config=_cfg()
            )

        assert "https://app.example.com/connect/for-this-user" in result
        assert result.startswith("Gmail needs to be connected")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_ui_context_points_to_card_without_url(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        """On UI the reply points at the rendered card, never a raw URL."""
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": "ui"}},
            ),
            patch("app.utils.integration_checker.get_stream_writer", return_value=_writer()),
        ):
            result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
                config=_cfg(), integration_ids=["gmail"]
            )

        assert "http" not in result
        assert "card" in result.lower()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_already_connected(self, mock_check: AsyncMock, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_ids=["gmail"]
        )
        assert "already connected" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_not_found(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_ids=["nonexistent"]
        )
        assert "not found" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", available=False)],
    )
    async def test_unavailable(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_ids=["gmail"]
        )
        assert "not available yet" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg_no_user(), integration_ids=["gmail"]
        )
        assert "Error" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_empty_list(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_ids=[]
        )
        assert result == "No integrations to connect."

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_service_error(self, mock_check: AsyncMock, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_ids=["gmail"]
        )
        assert "Error connecting" in result


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
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_connected(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Connected" in result

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_not_connected(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Not Connected" in result

    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_not_found(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_names=["nonexistent"]
        )
        assert "Not found" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg_no_user(), integration_names=["gmail"]
        )
        assert "Error" in result

    @patch(
        f"{MODULE}.check_single_integration_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail", short_name="gmail")],
    )
    async def test_service_error(self, mock_check: AsyncMock) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]  # langchain BaseTool.coroutine exists only at runtime; stubs omit it
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Error checking status" in result


# ---------------------------------------------------------------------------
# Tests: suggest_integrations (delegates to list_integrations)
# ---------------------------------------------------------------------------


class TestSuggestIntegrations:
    @patch(f"{MODULE}.list_integrations")
    async def test_delegates_to_list(self, mock_list: MagicMock) -> None:
        mock_list.ainvoke = AsyncMock(
            return_value={"connected": [], "available": [], "suggested": []}
        )

        from app.agents.tools.integration_tool import suggest_integrations

        await suggest_integrations.ainvoke({"query": "email tools"}, config=_cfg())
        mock_list.ainvoke.assert_awaited_once()
        # Check it passed search_public_query
        call_args = mock_list.ainvoke.call_args
        assert call_args[0][0]["search_public_query"] == "email tools"
