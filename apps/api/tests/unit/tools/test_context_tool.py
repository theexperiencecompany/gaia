"""Unit tests for app.agents.tools.context_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.context_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> Dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


# ---------------------------------------------------------------------------
# Tests: gather_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatherContext:
    """Tests for the gather_context tool."""

    @patch(f"{MODULE}.fetch_all_providers")
    @patch(f"{MODULE}.resolve_providers", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path_auto_detect_providers(
        self,
        mock_get_user: MagicMock,
        mock_resolve: AsyncMock,
        mock_fetch: MagicMock,
    ) -> None:
        """gather_context with no providers specified auto-detects connected ones."""
        mock_resolve.return_value = ["calendar", "gmail"]
        mock_fetch.return_value = {
            "calendar": {"events": [{"title": "Standup"}]},
            "gmail": {"emails": [{"subject": "Hello"}]},
        }

        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config(),
            providers=None,
            date=None,
        )

        assert "context" in result
        assert result["providers_queried"] == ["calendar", "gmail"]
        assert result["_performance"]["providers_attempted"] == 2
        assert result["_performance"]["providers_succeeded"] == 2
        mock_resolve.assert_awaited_once()

    @patch(f"{MODULE}.fetch_all_providers")
    @patch(f"{MODULE}.resolve_providers", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_specific_providers(
        self,
        mock_get_user: MagicMock,
        mock_resolve: AsyncMock,
        mock_fetch: MagicMock,
    ) -> None:
        """gather_context with explicit providers list passes them through."""
        mock_resolve.return_value = ["slack"]
        mock_fetch.return_value = {"slack": {"messages": []}}

        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config(),
            providers=["slack"],
            date="2026-01-15",
        )

        assert result["date"] == "2026-01-15"
        assert result["providers_queried"] == ["slack"]
        mock_resolve.assert_awaited_once()

    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
    ) -> None:
        """gather_context without user_id returns auth error."""
        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config_no_user(),
        )

        assert result == {"error": "User authentication required", "data": None}

    @patch(f"{MODULE}.fetch_all_providers")
    @patch(f"{MODULE}.resolve_providers", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_defaults_date_to_today(
        self,
        mock_get_user: MagicMock,
        mock_resolve: AsyncMock,
        mock_fetch: MagicMock,
    ) -> None:
        """When date is None, defaults to today's date string."""
        mock_resolve.return_value = []
        mock_fetch.return_value = {}

        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config(),
        )

        # The date should be a valid YYYY-MM-DD string
        assert "date" in result
        assert len(result["date"]) == 10
        assert result["date"].count("-") == 2

    @patch(f"{MODULE}.fetch_all_providers")
    @patch(f"{MODULE}.resolve_providers", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_connected_providers(
        self,
        mock_get_user: MagicMock,
        mock_resolve: AsyncMock,
        mock_fetch: MagicMock,
    ) -> None:
        """gather_context with no connected providers returns empty context."""
        mock_resolve.return_value = []
        mock_fetch.return_value = {}

        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config(),
        )

        assert result["providers_queried"] == []
        assert result["context"] == {}
        assert result["_performance"]["providers_attempted"] == 0
        assert result["_performance"]["providers_succeeded"] == 0

    @patch(f"{MODULE}.fetch_all_providers")
    @patch(f"{MODULE}.resolve_providers", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_performance_metrics_present(
        self,
        mock_get_user: MagicMock,
        mock_resolve: AsyncMock,
        mock_fetch: MagicMock,
    ) -> None:
        """Result includes _performance with timing info."""
        mock_resolve.return_value = ["calendar"]
        mock_fetch.return_value = {"calendar": {"events": []}}

        from app.agents.tools.context_tool import gather_context

        result = await gather_context.coroutine(
            config=_make_config(),
        )

        perf = result["_performance"]
        assert "total_time_seconds" in perf
        assert isinstance(perf["total_time_seconds"], float)
        assert perf["providers_attempted"] == 1
        assert perf["providers_succeeded"] == 1
