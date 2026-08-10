"""Tests for app.services.provider_metadata_service."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_integration(
    provider: str = "github",
    metadata_config: Any = None,
) -> MagicMock:
    integration = MagicMock()
    integration.provider = provider
    integration.metadata_config = metadata_config
    return integration


def _make_metadata_config(tools: list) -> MagicMock:
    cfg = MagicMock()
    cfg.tools = tools
    return cfg


def _make_tool_config(tool: str, variables: list) -> MagicMock:
    tc = MagicMock()
    tc.tool = tool
    tc.variables = variables
    return tc


def _make_variable(name: str, field_path: str) -> MagicMock:
    v = MagicMock()
    v.name = name
    v.field_path = field_path
    return v


class _ExplodingDict(dict[str, Any]):
    """dict whose .get raises — drives _extract_nested_field's error path."""

    def get(self, key: str, default: Any = None) -> Any:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# _extract_nested_field
# ---------------------------------------------------------------------------


class TestExtractNestedField:
    def test_simple_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"login": "octocat"}, "login") == "octocat"

    def test_nested_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: dict[str, Any] = {"data": {"login": "octocat"}}
        assert _extract_nested_field(data, "data.login") == "octocat"

    def test_deeply_nested_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: dict[str, Any] = {"a": {"b": {"c": "deep"}}}
        assert _extract_nested_field(data, "a.b.c") == "deep"

    def test_missing_key_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"a": 1}, "b") is None

    def test_non_dict_intermediate_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: dict[str, Any] = {"a": "string_value"}
        assert _extract_nested_field(data, "a.b") is None

    def test_none_value_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"a": None}, "a") is None

    def test_numeric_value_converted_to_str(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"count": 42}, "count") == "42"

    def test_error_path_logs_exact_wide_event(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        with patch.object(log, "error") as mock_error:
            result = _extract_nested_field(_ExplodingDict({"a": 1}), "a")

        assert result is None
        mock_error.assert_called_once_with(
            "Error extracting field",
            field_path="a",
            error="boom",
            error_type="RuntimeError",
        )


# ---------------------------------------------------------------------------
# fetch_tool_response
# ---------------------------------------------------------------------------


class TestFetchToolResponse:
    @pytest.mark.asyncio
    @patch.object(log, "set")
    @patch.object(log, "info")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_dict_response(
        self, mock_get_composio: MagicMock, mock_log_info: MagicMock, mock_log_set: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": {"login": "octocat"}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "GITHUB_USER_ME", "github")

        assert result == {"login": "octocat"}
        svc.get_tool.assert_called_once_with(
            tool_name="GITHUB_USER_ME",
            use_before_hook=False,
            use_after_hook=False,
            user_id="u1",
        )
        mock_tool.ainvoke.assert_called_once_with({})
        mock_log_set.assert_called_once_with(
            provider_metadata_user_id="u1",
            provider_metadata_tool="GITHUB_USER_ME",
            provider_metadata_integration="github",
        )
        mock_log_info.assert_called_once_with(
            "Fetched provider metadata tool result",
            tool_name="GITHUB_USER_ME",
            integration_id="github",
            data_type="dict",
        )

    @pytest.mark.asyncio
    @patch.object(log, "info")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_parsed_json_string(
        self, mock_get_composio: MagicMock, mock_log_info: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": json.dumps({"name": "test"})}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result == {"name": "test"}
        svc.get_tool.assert_called_once_with(
            tool_name="TOOL",
            use_before_hook=False,
            use_after_hook=False,
            user_id="u1",
        )
        mock_tool.ainvoke.assert_called_once_with({})
        mock_log_info.assert_called_once_with(
            "Fetched provider metadata tool result",
            tool_name="TOOL",
            integration_id="provider",
            data_type="str",
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_for_invalid_json_string(
        self, mock_get_composio: MagicMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": "not json"}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result is None
        mock_log_warning.assert_called_once_with(
            "Could not parse tool response as JSON",
            tool_name="TOOL",
            response_length=8,
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_when_json_is_not_an_object(
        self, mock_get_composio: MagicMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": "[1, 2, 3]"}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result is None
        mock_log_warning.assert_called_once_with(
            "Tool response JSON was not an object",
            tool_name="TOOL",
            data_type="list",
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_for_unexpected_type(
        self, mock_get_composio: MagicMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": 12345}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result is None
        mock_log_warning.assert_called_once_with(
            "Unexpected response type from tool",
            tool_name="TOOL",
            data_type="int",
        )

    @pytest.mark.asyncio
    @patch.object(log, "info")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_empty_dict_when_data_key_missing(
        self, mock_get_composio: MagicMock, mock_log_info: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result == {}
        mock_log_info.assert_called_once_with(
            "Fetched provider metadata tool result",
            tool_name="TOOL",
            integration_id="provider",
            data_type="dict",
        )

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_when_tool_not_found(
        self, mock_get_composio: MagicMock, mock_log_error: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        svc = MagicMock()
        svc.get_tool.return_value = None
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "MISSING", "github")

        assert result is None
        svc.get_tool.assert_called_once_with(
            tool_name="MISSING",
            use_before_hook=False,
            use_after_hook=False,
            user_id="u1",
        )
        mock_log_error.assert_called_once_with(
            "Tool not found for",
            tool_name="MISSING",
            integration_id="github",
            user_id="u1",
        )

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_when_ainvoke_raises(
        self, mock_get_composio: MagicMock, mock_log_error: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.side_effect = RuntimeError("tool boom")

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result is None
        mock_log_error.assert_called_once_with(
            "Error fetching for",
            tool_name="TOOL",
            integration_id="provider",
            error="tool boom",
            error_type="RuntimeError",
            user_id="u1",
        )

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_when_ainvoke_returns_none(
        self, mock_get_composio: MagicMock, mock_log_error: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = None

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")

        assert result is None
        mock_log_error.assert_called_once_with(
            "Error fetching for",
            tool_name="TOOL",
            integration_id="provider",
            error="'NoneType' object has no attribute 'get'",
            error_type="AttributeError",
            user_id="u1",
        )

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_on_exception(
        self, mock_get_composio: MagicMock, mock_log_error: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_get_composio.side_effect = RuntimeError("boom")

        result = await fetch_tool_response("u1", "T", "p")

        assert result is None
        mock_log_error.assert_called_once_with(
            "Error fetching for",
            tool_name="T",
            integration_id="p",
            error="boom",
            error_type="RuntimeError",
            user_id="u1",
        )


# ---------------------------------------------------------------------------
# fetch_provider_user_info
# ---------------------------------------------------------------------------


class TestFetchProviderUserInfo:
    @pytest.mark.asyncio
    @patch.object(log, "set")
    @patch.object(log, "debug")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_metadata_dict(
        self,
        mock_get_int: MagicMock,
        mock_fetch: AsyncMock,
        mock_log_debug: MagicMock,
        mock_log_set: MagicMock,
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var = _make_variable("username", "login")
        tc = _make_tool_config("GITHUB_USER_ME", [var])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = {"login": "octocat"}

        result = await fetch_provider_user_info("u1", "github")

        assert result == {"username": "octocat"}
        mock_get_int.assert_called_once_with("github")
        mock_fetch.assert_called_once_with("u1", "GITHUB_USER_ME", "github")
        mock_log_set.assert_called_once_with(
            provider_metadata_user_id="u1",
            provider_metadata_integration="github",
        )
        mock_log_debug.assert_called_once_with(
            "Extracted = from",
            name="username",
            value="octocat",
            tool="GITHUB_USER_ME",
        )

    @pytest.mark.asyncio
    @patch.object(log, "debug")
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_no_integration(
        self, mock_get_int: MagicMock, mock_log_debug: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        mock_get_int.return_value = None

        result = await fetch_provider_user_info("u1", "unknown")

        assert result is None
        mock_get_int.assert_called_once_with("unknown")
        mock_log_debug.assert_called_once_with(
            "No metadata config for integration", integration_id="unknown"
        )

    @pytest.mark.asyncio
    @patch.object(log, "debug")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_no_metadata_config(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_debug: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        mock_get_int.return_value = _make_integration(metadata_config=None)

        result = await fetch_provider_user_info("u1", "github")

        assert result is None
        mock_fetch.assert_not_called()
        mock_log_debug.assert_called_once_with(
            "No metadata config for integration", integration_id="github"
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_all_tools_fail(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var = _make_variable("username", "login")
        tc = _make_tool_config("TOOL", [var])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = None

        result = await fetch_provider_user_info("u1", "github")

        assert result is None
        mock_fetch.assert_called_once_with("u1", "TOOL", "github")
        mock_log_warning.assert_called_once_with(
            "Failed to fetch provider metadata, skipping",
            tool="TOOL",
            integration_id="github",
            user_id="u1",
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch.object(log, "debug")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_skips_missing_fields(
        self,
        mock_get_int: MagicMock,
        mock_fetch: AsyncMock,
        mock_log_debug: MagicMock,
        mock_log_warning: MagicMock,
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var1 = _make_variable("username", "login")
        var2 = _make_variable("email", "missing_field")
        tc = _make_tool_config("TOOL", [var1, var2])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = {"login": "octocat"}

        result = await fetch_provider_user_info("u1", "github")

        assert result == {"username": "octocat"}
        mock_log_debug.assert_called_once_with(
            "Extracted = from",
            name="username",
            value="octocat",
            tool="TOOL",
        )
        mock_log_warning.assert_called_once_with(
            "Could not extract from in response",
            name="email",
            field_path="missing_field",
            tool="TOOL",
            user_id="u1",
            integration_id="github",
        )

    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_multiple_tools(self, mock_get_int: MagicMock, mock_fetch: AsyncMock) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        v1 = _make_variable("username", "login")
        tc1 = _make_tool_config("TOOL_A", [v1])
        v2 = _make_variable("email", "addr")
        tc2 = _make_tool_config("TOOL_B", [v2])
        cfg = _make_metadata_config([tc1, tc2])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)

        mock_fetch.side_effect = [{"login": "user1"}, {"addr": "a@b.com"}]

        result = await fetch_provider_user_info("u1", "github")

        assert result == {"username": "user1", "email": "a@b.com"}
        mock_fetch.assert_has_calls(
            [call("u1", "TOOL_A", "github"), call("u1", "TOOL_B", "github")]
        )
        assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_continues_when_first_tool_fails(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        v1 = _make_variable("username", "login")
        tc1 = _make_tool_config("TOOL_A", [v1])
        v2 = _make_variable("email", "addr")
        tc2 = _make_tool_config("TOOL_B", [v2])
        cfg = _make_metadata_config([tc1, tc2])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)

        mock_fetch.side_effect = [None, {"addr": "a@b.com"}]

        result = await fetch_provider_user_info("u1", "github")

        assert result == {"email": "a@b.com"}
        mock_fetch.assert_has_calls(
            [call("u1", "TOOL_A", "github"), call("u1", "TOOL_B", "github")]
        )
        mock_log_warning.assert_called_once_with(
            "Failed to fetch provider metadata, skipping",
            tool="TOOL_A",
            integration_id="github",
            user_id="u1",
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_empty_string_value_is_not_stored(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var = _make_variable("username", "login")
        tc = _make_tool_config("TOOL", [var])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = {"login": ""}

        result = await fetch_provider_user_info("u1", "github")

        assert result is None
        mock_log_warning.assert_called_once_with(
            "Could not extract from in response",
            name="username",
            field_path="login",
            tool="TOOL",
            user_id="u1",
            integration_id="github",
        )

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_no_tools_configured(self, mock_get_int: MagicMock) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        mock_get_int.return_value = _make_integration(metadata_config=_make_metadata_config([]))

        result = await fetch_provider_user_info("u1", "github")

        assert result is None


# ---------------------------------------------------------------------------
# store_provider_metadata
# ---------------------------------------------------------------------------


class TestStoreProviderMetadata:
    @pytest.mark.asyncio
    @patch.object(log, "set")
    @patch.object(log, "info")
    @patch("app.decorators.caching.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.set_provider_metadata",
        new_callable=AsyncMock,
    )
    async def test_success(
        self,
        mock_set: AsyncMock,
        mock_delete_cache: AsyncMock,
        mock_log_info: MagicMock,
        mock_log_set: MagicMock,
    ) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_set.return_value = True

        ok = await store_provider_metadata(
            "507f1f77bcf86cd799439011", "github", {"username": "octocat"}
        )

        assert ok is True
        mock_set.assert_called_once_with(
            "507f1f77bcf86cd799439011", "github", {"username": "octocat"}
        )
        mock_log_set.assert_called_once_with(
            provider_metadata_user_id="507f1f77bcf86cd799439011",
            provider_metadata_provider="github",
            provider_metadata_keys=["username"],
        )
        mock_log_info.assert_called_once_with(
            "Stored metadata for user",
            provider="github",
            user_id="507f1f77bcf86cd799439011",
            metadata={"username": "octocat"},
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch("app.decorators.caching.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.set_provider_metadata",
        new_callable=AsyncMock,
    )
    async def test_no_document_updated(
        self, mock_set: AsyncMock, mock_delete_cache: AsyncMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_set.return_value = False

        ok = await store_provider_metadata(
            "507f1f77bcf86cd799439011", "github", {"username": "octocat"}
        )

        assert ok is False
        mock_log_warning.assert_called_once_with(
            "No document updated for user", user_id="507f1f77bcf86cd799439011"
        )

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.decorators.caching.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.set_provider_metadata",
        new_callable=AsyncMock,
    )
    async def test_exception_returns_false(
        self, mock_set: AsyncMock, mock_delete_cache: AsyncMock, mock_log_error: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_set.side_effect = RuntimeError("db error")

        ok = await store_provider_metadata("507f1f77bcf86cd799439011", "github", {"a": "b"})

        assert ok is False
        mock_log_error.assert_called_once_with(
            "Error storing metadata for user",
            provider="github",
            user_id="507f1f77bcf86cd799439011",
            error="db error",
            error_type="RuntimeError",
        )


# ---------------------------------------------------------------------------
# get_provider_metadata
# ---------------------------------------------------------------------------


class TestGetProviderMetadata:
    @pytest.mark.asyncio
    @patch("app.decorators.caching.set_cache", new_callable=AsyncMock)
    @patch("app.decorators.caching.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.get",
        new_callable=AsyncMock,
    )
    async def test_returns_metadata(
        self,
        mock_get: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        from app.models.user_models import UserDocument
        from app.services.provider_metadata_service import get_provider_metadata

        mock_get_cache.return_value = None
        mock_get.return_value = UserDocument(provider_metadata={"github": {"username": "octocat"}})

        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")

        assert result == {"username": "octocat"}
        mock_get.assert_called_once_with("507f1f77bcf86cd799439011")

    @pytest.mark.asyncio
    @patch("app.decorators.caching.set_cache", new_callable=AsyncMock)
    @patch("app.decorators.caching.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.get",
        new_callable=AsyncMock,
    )
    async def test_returns_none_when_user_not_found(
        self,
        mock_get: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        mock_get_cache.return_value = None
        from app.services.provider_metadata_service import get_provider_metadata

        mock_get.return_value = None

        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")

        assert result is None
        mock_get.assert_called_once_with("507f1f77bcf86cd799439011")

    @pytest.mark.asyncio
    @patch("app.decorators.caching.set_cache", new_callable=AsyncMock)
    @patch("app.decorators.caching.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.get",
        new_callable=AsyncMock,
    )
    async def test_returns_none_when_provider_missing(
        self,
        mock_get: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        mock_get_cache.return_value = None
        from app.models.user_models import UserDocument
        from app.services.provider_metadata_service import get_provider_metadata

        mock_get.return_value = UserDocument(provider_metadata={})

        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")

        assert result is None
        mock_get.assert_called_once_with("507f1f77bcf86cd799439011")

    @pytest.mark.asyncio
    @patch("app.decorators.caching.set_cache", new_callable=AsyncMock)
    @patch("app.decorators.caching.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.get",
        new_callable=AsyncMock,
    )
    async def test_returns_none_when_metadata_value_not_a_dict(
        self,
        mock_get: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        mock_get_cache.return_value = None
        from app.models.user_models import UserDocument
        from app.services.provider_metadata_service import get_provider_metadata

        mock_get.return_value = UserDocument(provider_metadata={"github": ["not", "a", "dict"]})

        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")

        assert result is None

    @pytest.mark.asyncio
    @patch.object(log, "error")
    @patch("app.decorators.caching.set_cache", new_callable=AsyncMock)
    @patch("app.decorators.caching.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.provider_metadata_service.user_repository.get",
        new_callable=AsyncMock,
    )
    async def test_exception_returns_none(
        self,
        mock_get: AsyncMock,
        mock_get_cache: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_log_error: MagicMock,
    ) -> None:
        mock_get_cache.return_value = None
        from app.services.provider_metadata_service import get_provider_metadata

        mock_get.side_effect = RuntimeError("db")

        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")

        assert result is None
        mock_log_error.assert_called_once_with(
            "Error getting metadata for user",
            provider="github",
            user_id="507f1f77bcf86cd799439011",
            error="db",
            error_type="RuntimeError",
        )


# ---------------------------------------------------------------------------
# fetch_and_store_provider_metadata
# ---------------------------------------------------------------------------


class TestFetchAndStoreProviderMetadata:
    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.store_provider_metadata",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.provider_metadata_service.fetch_provider_user_info",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_success(
        self,
        mock_get_int: MagicMock,
        mock_fetch: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = _make_integration(
            provider="github",
            metadata_config=_make_metadata_config([]),
        )
        mock_fetch.return_value = {"username": "octocat"}
        mock_store.return_value = True

        result = await fetch_and_store_provider_metadata("u1", "github")

        assert result is True
        mock_get_int.assert_called_once_with("github")
        mock_fetch.assert_called_once_with("u1", "github")
        mock_store.assert_called_once_with("u1", "github", {"username": "octocat"})

    @pytest.mark.asyncio
    @patch.object(log, "debug")
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_no_integration(
        self, mock_get_int: MagicMock, mock_log_debug: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = None

        result = await fetch_and_store_provider_metadata("u1", "unknown")

        assert result is False
        mock_get_int.assert_called_once_with("unknown")
        mock_log_debug.assert_called_once_with("Integration not found", integration_id="unknown")

    @pytest.mark.asyncio
    @patch.object(log, "debug")
    @patch(
        "app.services.provider_metadata_service.fetch_provider_user_info",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_no_metadata_config(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_debug: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = _make_integration(metadata_config=None)

        result = await fetch_and_store_provider_metadata("u1", "github")

        assert result is False
        mock_fetch.assert_not_called()
        mock_log_debug.assert_called_once_with(
            "No metadata config for integration", integration_id="github"
        )

    @pytest.mark.asyncio
    @patch.object(log, "warning")
    @patch(
        "app.services.provider_metadata_service.fetch_provider_user_info",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_fetch_fails(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock, mock_log_warning: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = _make_integration(metadata_config=_make_metadata_config([]))
        mock_fetch.return_value = None

        result = await fetch_and_store_provider_metadata("u1", "github")

        assert result is False
        mock_log_warning.assert_called_once_with(
            "Failed to fetch/extract metadata for", integration_id="github", user_id="u1"
        )
