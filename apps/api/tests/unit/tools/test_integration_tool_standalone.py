"""Unit tests for app.agents.tools.integration_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _cfg(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    return {"configurable": {"user_id": user_id}}


def _cfg_no_user() -> Dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Tests: build_search_patterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
class TestListIntegrations:
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.user_integrations_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_happy_path_empty(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_int: MagicMock,
        mock_int_coll: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}

        # user_integrations_collection.find returns async iterable with no docs
        async def _empty_cursor():
            return
            yield  # noqa

        mock_user_int.find.return_value = _empty_cursor()

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result["connected"] == []
        assert result["available"] == []

    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.user_integrations_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_make_integration("gmail", "Gmail"), _make_integration("notion", "Notion")],
    )
    async def test_with_connected_and_available(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_int: MagicMock,
        mock_int_coll: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {"gmail": True, "notion": False}

        async def _empty_cursor():
            return
            yield  # noqa

        mock_user_int.find.return_value = _empty_cursor()

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert len(result["connected"]) == 1
        assert result["connected"][0]["id"] == "gmail"
        assert len(result["available"]) == 1
        assert result["available"][0]["id"] == "notion"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_no_user_id(self, mock_gsw: MagicMock) -> None:
        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg_no_user())  # type: ignore[attr-defined]
        assert "Error" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.check_multiple_integrations_status",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration()])
    async def test_service_error(
        self, mock_status: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "Error" in result

    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.user_integrations_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.check_multiple_integrations_status", new_callable=AsyncMock)
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_make_integration(available=False)])
    async def test_unavailable_integrations_excluded(
        self,
        mock_status: AsyncMock,
        mock_gsw: MagicMock,
        mock_user_int: MagicMock,
        mock_int_coll: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_status.return_value = {}

        async def _empty_cursor():
            return
            yield  # noqa

        mock_user_int.find.return_value = _empty_cursor()

        from app.agents.tools.integration_tool import list_integrations

        result = await list_integrations.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert result["connected"] == []
        assert result["available"] == []


# ---------------------------------------------------------------------------
# Tests: connect_integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectIntegration:
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
    async def test_initiates_connection(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Connection initiated" in result
        # Writer should be called with integration_connection_required
        integration_calls = [
            c for c in w.call_args_list if "integration_connection_required" in c[0][0]
        ]
        assert len(integration_calls) == 1

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
    async def test_already_connected(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "already connected" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_not_found(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["nonexistent"]
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

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "not available yet" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg_no_user(), integration_names=["gmail"]
        )
        assert "Error" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_empty_list(self, mock_gsw: MagicMock) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=[]
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
    async def test_service_error(
        self, mock_check: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()

        from app.agents.tools.integration_tool import connect_integration

        result = await connect_integration.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Error connecting" in result


# ---------------------------------------------------------------------------
# Tests: check_integrations_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
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

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
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

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Not Connected" in result

    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_not_found(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["nonexistent"]
        )
        assert "Not found" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.integration_tool import check_integrations_status

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
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

        result = await check_integrations_status.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), integration_names=["gmail"]
        )
        assert "Error checking status" in result


# ---------------------------------------------------------------------------
# Tests: suggest_integrations (delegates to list_integrations)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuggestIntegrations:
    @patch(f"{MODULE}.list_integrations")
    async def test_delegates_to_list(self, mock_list: MagicMock) -> None:
        mock_list.ainvoke = AsyncMock(
            return_value={"connected": [], "available": [], "suggested": []}
        )

        from app.agents.tools.integration_tool import suggest_integrations

        await suggest_integrations.coroutine(config=_cfg(), query="email tools")  # type: ignore[attr-defined]
        mock_list.ainvoke.assert_awaited_once()
        # Check it passed search_public_query
        call_args = mock_list.ainvoke.call_args
        assert call_args[0][0]["search_public_query"] == "email tools"
