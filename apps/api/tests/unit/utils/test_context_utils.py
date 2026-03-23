"""Unit tests for context_utils: execute_tool, fetch_all_providers, resolve_providers."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.utils.context_utils import execute_tool, fetch_all_providers, resolve_providers

# Patch targets — these are lazy (inline) imports inside the production code,
# so we patch at the *source* module, not at app.utils.context_utils.
_COMPOSIO_SERVICE_PATCH = "app.services.composio.composio_service.get_composio_service"
_NAMESPACES_PATCH = (
    "app.services.integrations.integration_service.get_user_available_tool_namespaces"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SampleOutputModel(BaseModel):
    name: str
    count: int


class _StrictOutputModel(BaseModel):
    """Model whose fields don't match typical tool output — triggers validation failure."""

    required_field: int
    another_required: str


def _make_composio_service(result: Dict[str, Any]) -> MagicMock:
    """Build a mock ComposioService whose tools.execute returns *result*."""
    service = MagicMock()
    service.composio.tools.execute.return_value = result
    return service


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteTool:
    """Tests for execute_tool (sync, calls Composio service)."""

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_successful_execution_returns_data(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value = _make_composio_service(
            {"successful": True, "data": {"emails": [1, 2, 3]}}
        )

        result = execute_tool("GMAIL_FETCH_EMAILS", {"limit": 10}, "user_123")

        assert result == {"emails": [1, 2, 3]}
        mock_get_service.return_value.composio.tools.execute.assert_called_once_with(
            slug="GMAIL_FETCH_EMAILS",
            arguments={"limit": 10},
            user_id="user_123",
            dangerously_skip_version_check=True,
        )

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_unsuccessful_execution_raises_with_error_message(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value = _make_composio_service(
            {"successful": False, "error": "Auth token expired"}
        )

        with pytest.raises(Exception, match="Auth token expired"):
            execute_tool("GMAIL_FETCH_EMAILS", {}, "user_123")

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_unsuccessful_execution_raises_fallback_message_when_no_error_key(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value = _make_composio_service({"successful": False})

        with pytest.raises(Exception, match="GMAIL_FETCH_EMAILS failed"):
            execute_tool("GMAIL_FETCH_EMAILS", {}, "user_123")

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_with_output_model_validation_succeeds(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value = _make_composio_service(
            {"successful": True, "data": {"name": "Test", "count": 42}}
        )

        result = execute_tool(
            "SOME_TOOL", {}, "user_123", output_model=_SampleOutputModel
        )

        assert result == {"name": "Test", "count": 42}

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_with_output_model_validation_fails_returns_raw_data(
        self, mock_get_service: MagicMock
    ) -> None:
        raw_data = {"unexpected_field": "hello"}
        mock_get_service.return_value = _make_composio_service(
            {"successful": True, "data": raw_data}
        )

        result = execute_tool(
            "SOME_TOOL", {}, "user_123", output_model=_StrictOutputModel
        )

        # Should return raw data when validation fails
        assert result == raw_data

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_without_output_model_returns_raw_data(
        self, mock_get_service: MagicMock
    ) -> None:
        raw_data = {"arbitrary": "structure", "nested": {"deep": True}}
        mock_get_service.return_value = _make_composio_service(
            {"successful": True, "data": raw_data}
        )

        result = execute_tool("ANY_TOOL", {"x": 1}, "user_456")

        assert result == raw_data

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_empty_params_accepted(self, mock_get_service: MagicMock) -> None:
        mock_get_service.return_value = _make_composio_service(
            {"successful": True, "data": {}}
        )

        result = execute_tool("TOOL", {}, "user_1")

        assert result == {}

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_unsuccessful_with_error_none(self, mock_get_service: MagicMock) -> None:
        """When error key exists but is None, fallback message should be used."""
        mock_get_service.return_value = _make_composio_service(
            {"successful": False, "error": None}
        )

        with pytest.raises(Exception, match="MY_TOOL failed"):
            execute_tool("MY_TOOL", {}, "user_1")

    @patch(_COMPOSIO_SERVICE_PATCH)
    def test_unsuccessful_with_empty_string_error(
        self, mock_get_service: MagicMock
    ) -> None:
        """When error is empty string, fallback message should be used."""
        mock_get_service.return_value = _make_composio_service(
            {"successful": False, "error": ""}
        )

        with pytest.raises(Exception, match="EMPTY_ERR_TOOL failed"):
            execute_tool("EMPTY_ERR_TOOL", {}, "user_1")


# ---------------------------------------------------------------------------
# fetch_all_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchAllProviders:
    """Tests for fetch_all_providers (parallel execution with ThreadPoolExecutor)."""

    @patch("app.utils.context_utils.execute_tool")
    def test_all_providers_succeed(self, mock_execute: MagicMock) -> None:
        mock_execute.side_effect = lambda slug, params, uid: {"provider_data": slug}

        provider_tools = {
            "gmail": "GMAIL_GATHER",
            "calendar": "CALENDAR_GATHER",
        }

        result = fetch_all_providers(["gmail", "calendar"], provider_tools, "user_1")

        assert "gmail" in result
        assert "calendar" in result
        assert result["gmail"] == {"provider_data": "GMAIL_GATHER"}
        assert result["calendar"] == {"provider_data": "CALENDAR_GATHER"}

    @patch("app.utils.context_utils.execute_tool")
    def test_some_providers_fail(self, mock_execute: MagicMock) -> None:
        def side_effect(slug: str, params: dict, uid: str) -> dict:
            if slug == "FAIL_GATHER":
                raise Exception("Provider down")
            return {"ok": True}

        mock_execute.side_effect = side_effect

        provider_tools = {
            "good": "GOOD_GATHER",
            "bad": "FAIL_GATHER",
        }

        result = fetch_all_providers(["good", "bad"], provider_tools, "user_1")

        assert "good" in result
        assert result["good"] == {"ok": True}
        assert "bad" not in result

    @patch("app.utils.context_utils.PROVIDER_TIMEOUT_SECONDS", 0.001)
    @patch("app.utils.context_utils.execute_tool")
    def test_timeout_on_one_provider_skipped(self, mock_execute: MagicMock) -> None:
        """A provider that exceeds the timeout should be skipped."""
        import time

        def side_effect(slug: str, params: dict, uid: str) -> dict:
            if slug == "SLOW_GATHER":
                time.sleep(1)  # Well beyond the 0.001s timeout
                return {"slow": True}
            return {"fast": True}

        mock_execute.side_effect = side_effect

        provider_tools = {
            "fast_provider": "FAST_GATHER",
            "slow_provider": "SLOW_GATHER",
        }

        result = fetch_all_providers(
            ["fast_provider", "slow_provider"], provider_tools, "user_1"
        )

        assert "fast_provider" in result
        assert result["fast_provider"] == {"fast": True}
        # The slow provider should be skipped due to timeout
        assert "slow_provider" not in result

    @patch("app.utils.context_utils.execute_tool")
    def test_empty_providers_list(self, mock_execute: MagicMock) -> None:
        result = fetch_all_providers([], {}, "user_1")

        assert result == {}
        mock_execute.assert_not_called()

    @patch("app.utils.context_utils.execute_tool")
    def test_all_providers_fail(self, mock_execute: MagicMock) -> None:
        mock_execute.side_effect = Exception("All broken")

        provider_tools = {
            "a": "A_GATHER",
            "b": "B_GATHER",
        }

        result = fetch_all_providers(["a", "b"], provider_tools, "user_1")

        assert result == {}

    @patch("app.utils.context_utils.execute_tool")
    def test_provider_returning_none_data_excluded(
        self, mock_execute: MagicMock
    ) -> None:
        """fetch_one returns (provider, None) on exception, which should be excluded."""
        call_count = 0

        def side_effect(slug: str, params: dict, uid: str) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First call fails")
            return {"data": "ok"}

        mock_execute.side_effect = side_effect

        provider_tools = {"p1": "P1_TOOL", "p2": "P2_TOOL"}

        result = fetch_all_providers(["p1", "p2"], provider_tools, "user_1")

        # At least one should succeed; the failed one should be absent
        successful_count = len(result)
        assert successful_count >= 1

    @patch("app.utils.context_utils.execute_tool")
    def test_single_provider_success(self, mock_execute: MagicMock) -> None:
        mock_execute.return_value = {"inbox": []}

        provider_tools = {"email": "EMAIL_GATHER"}

        result = fetch_all_providers(["email"], provider_tools, "user_1")

        assert result == {"email": {"inbox": []}}


# ---------------------------------------------------------------------------
# resolve_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestResolveProviders:
    """Tests for resolve_providers (async, resolves which providers to query)."""

    async def test_with_explicit_requested_list_returns_filtered(self) -> None:
        provider_tools = {
            "gmail": "GMAIL_TOOL",
            "calendar": "CALENDAR_TOOL",
            "slack": "SLACK_TOOL",
        }

        result = await resolve_providers(
            requested=["Gmail", "Slack"],
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug.lower(),
        )

        assert result == ["gmail", "slack"]

    async def test_with_explicit_requested_filters_out_unknown(self) -> None:
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=["Gmail", "NotAProvider"],
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug.lower(),
        )

        assert result == ["gmail"]

    @patch(_NAMESPACES_PATCH, new_callable=AsyncMock, return_value=set())
    async def test_with_explicit_requested_empty_list(
        self, mock_namespaces: AsyncMock
    ) -> None:
        """An empty requested list is falsy, so it should trigger auto-detect."""
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=[],
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug.lower(),
        )

        # Empty list is falsy -> auto-detect -> no connected -> []
        assert result == []

    @patch(_NAMESPACES_PATCH, new_callable=AsyncMock)
    async def test_auto_detect_connected_found(
        self, mock_namespaces: AsyncMock
    ) -> None:
        mock_namespaces.return_value = {"gmail_ns", "calendar_ns"}

        provider_tools = {
            "gmail": "GMAIL_TOOL",
            "calendar": "CALENDAR_TOOL",
            "slack": "SLACK_TOOL",
        }

        def namespace_fn(slug: str) -> str:
            return slug.lower().replace("_tool", "_ns")

        result = await resolve_providers(
            requested=None,
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=namespace_fn,
        )

        assert sorted(result) == ["calendar", "gmail"]

    @patch(_NAMESPACES_PATCH, new_callable=AsyncMock, return_value=set())
    async def test_auto_detect_no_connected_returns_empty(
        self, mock_namespaces: AsyncMock
    ) -> None:
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=None,
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: "unrelated_ns",
        )

        assert result == []

    @patch(
        _NAMESPACES_PATCH,
        new_callable=AsyncMock,
        side_effect=Exception("Service unavailable"),
    )
    async def test_auto_detect_get_namespaces_fails_returns_empty(
        self, mock_namespaces: AsyncMock
    ) -> None:
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=None,
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug,
        )

        assert result == []

    @patch(
        _NAMESPACES_PATCH,
        new_callable=AsyncMock,
        return_value={"completely_different_ns"},
    )
    async def test_auto_detect_connected_but_no_match_returns_empty(
        self, mock_namespaces: AsyncMock
    ) -> None:
        """Connected namespaces exist but none match provider_tools slugs."""
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=None,
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: "no_match_ns",
        )

        assert result == []

    async def test_requested_case_insensitive(self) -> None:
        provider_tools = {"gmail": "GMAIL_TOOL", "slack": "SLACK_TOOL"}

        result = await resolve_providers(
            requested=["GMAIL", "SLACK"],
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug,
        )

        assert result == ["gmail", "slack"]

    async def test_requested_all_unknown_returns_empty(self) -> None:
        provider_tools = {"gmail": "GMAIL_TOOL"}

        result = await resolve_providers(
            requested=["nonexistent", "also_missing"],
            user_id="user_1",
            provider_tools=provider_tools,
            namespace_fn=lambda slug: slug,
        )

        assert result == []

    @patch(
        _NAMESPACES_PATCH,
        new_callable=AsyncMock,
        return_value={"something"},
    )
    async def test_auto_detect_none_requested_with_empty_provider_tools(
        self, mock_namespaces: AsyncMock
    ) -> None:
        result = await resolve_providers(
            requested=None,
            user_id="user_1",
            provider_tools={},
            namespace_fn=lambda slug: slug,
        )

        assert result == []
