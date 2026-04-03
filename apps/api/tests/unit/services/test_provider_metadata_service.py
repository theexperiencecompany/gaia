"""Tests for app.services.provider_metadata_service."""

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


# ---------------------------------------------------------------------------
# _extract_nested_field
# ---------------------------------------------------------------------------


class TestExtractNestedField:
    def test_simple_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"login": "octocat"}, "login") == "octocat"

    def test_nested_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: Dict[str, Any] = {"data": {"login": "octocat"}}
        assert _extract_nested_field(data, "data.login") == "octocat"

    def test_deeply_nested_key(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: Dict[str, Any] = {"a": {"b": {"c": "deep"}}}
        assert _extract_nested_field(data, "a.b.c") == "deep"

    def test_missing_key_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"a": 1}, "b") is None

    def test_non_dict_intermediate_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        data: Dict[str, Any] = {"a": "string_value"}
        assert _extract_nested_field(data, "a.b") is None

    def test_none_value_returns_none(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"a": None}, "a") is None

    def test_numeric_value_converted_to_str(self) -> None:
        from app.services.provider_metadata_service import _extract_nested_field

        assert _extract_nested_field({"count": 42}, "count") == "42"


# ---------------------------------------------------------------------------
# fetch_tool_response
# ---------------------------------------------------------------------------


class TestFetchToolResponse:
    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_dict_response(self, mock_get_composio: MagicMock) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": {"login": "octocat"}}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "GITHUB_USER_ME", "github")
        assert result == {"login": "octocat"}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_parsed_json_string(
        self, mock_get_composio: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": json.dumps({"name": "test"})}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_for_invalid_json_string(
        self, mock_get_composio: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": "not json"}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_for_unexpected_type(
        self, mock_get_composio: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = {"data": 12345}

        svc = MagicMock()
        svc.get_tool.return_value = mock_tool
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "TOOL", "provider")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_when_tool_not_found(
        self, mock_get_composio: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        svc = MagicMock()
        svc.get_tool.return_value = None
        mock_get_composio.return_value = svc

        result = await fetch_tool_response("u1", "MISSING", "github")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_composio_service")
    async def test_returns_none_on_exception(
        self, mock_get_composio: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_tool_response

        mock_get_composio.side_effect = RuntimeError("boom")
        result = await fetch_tool_response("u1", "T", "p")
        assert result is None


# ---------------------------------------------------------------------------
# fetch_provider_user_info
# ---------------------------------------------------------------------------


class TestFetchProviderUserInfo:
    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_metadata_dict(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var = _make_variable("username", "login")
        tc = _make_tool_config("GITHUB_USER_ME", [var])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = {"login": "octocat"}

        result = await fetch_provider_user_info("u1", "github")
        assert result == {"username": "octocat"}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_no_integration(
        self, mock_get_int: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        mock_get_int.return_value = None
        result = await fetch_provider_user_info("u1", "unknown")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_no_metadata_config(
        self, mock_get_int: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        mock_get_int.return_value = _make_integration(metadata_config=None)
        result = await fetch_provider_user_info("u1", "github")
        assert result is None

    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_none_when_all_tools_fail(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        from app.services.provider_metadata_service import fetch_provider_user_info

        var = _make_variable("username", "login")
        tc = _make_tool_config("TOOL", [var])
        cfg = _make_metadata_config([tc])
        mock_get_int.return_value = _make_integration(metadata_config=cfg)
        mock_fetch.return_value = None

        result = await fetch_provider_user_info("u1", "github")
        assert result is None

    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_skips_missing_fields(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock
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

    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_tool_response",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_multiple_tools(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock
    ) -> None:
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


# ---------------------------------------------------------------------------
# store_provider_metadata
# ---------------------------------------------------------------------------


class TestStoreProviderMetadata:
    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_success(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_coll.update_one = AsyncMock(return_value=mock_result)

        ok = await store_provider_metadata(
            "507f1f77bcf86cd799439011", "github", {"username": "octocat"}
        )
        assert ok is True

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_no_document_updated(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_coll.update_one = AsyncMock(return_value=mock_result)

        ok = await store_provider_metadata(
            "507f1f77bcf86cd799439011", "github", {"username": "octocat"}
        )
        assert ok is False

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_exception_returns_false(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import store_provider_metadata

        mock_coll.update_one = AsyncMock(side_effect=RuntimeError("db error"))
        ok = await store_provider_metadata(
            "507f1f77bcf86cd799439011", "github", {"a": "b"}
        )
        assert ok is False


# ---------------------------------------------------------------------------
# get_provider_metadata
# ---------------------------------------------------------------------------


class TestGetProviderMetadata:
    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_metadata(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import get_provider_metadata

        mock_coll.find_one = AsyncMock(
            return_value={"provider_metadata": {"github": {"username": "octocat"}}}
        )
        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")
        assert result == {"username": "octocat"}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_none_when_user_not_found(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import get_provider_metadata

        mock_coll.find_one = AsyncMock(return_value=None)
        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_none_when_provider_missing(
        self, mock_coll: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import get_provider_metadata

        mock_coll.find_one = AsyncMock(return_value={"provider_metadata": {}})
        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_exception_returns_none(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import get_provider_metadata

        mock_coll.find_one = AsyncMock(side_effect=RuntimeError("db"))
        result = await get_provider_metadata("507f1f77bcf86cd799439011", "github")
        assert result is None


# ---------------------------------------------------------------------------
# get_all_provider_metadata
# ---------------------------------------------------------------------------


class TestGetAllProviderMetadata:
    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_all(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import get_all_provider_metadata

        mock_coll.find_one = AsyncMock(
            return_value={
                "provider_metadata": {"github": {"u": "a"}, "twitter": {"u": "b"}}
            }
        )
        result = await get_all_provider_metadata("507f1f77bcf86cd799439011")
        assert len(result) == 2

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_empty_when_user_not_found(
        self, mock_coll: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import get_all_provider_metadata

        mock_coll.find_one = AsyncMock(return_value=None)
        result = await get_all_provider_metadata("507f1f77bcf86cd799439011")
        assert result == {}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_exception_returns_empty(self, mock_coll: MagicMock) -> None:
        from app.services.provider_metadata_service import get_all_provider_metadata

        mock_coll.find_one = AsyncMock(side_effect=RuntimeError("db"))
        result = await get_all_provider_metadata("507f1f77bcf86cd799439011")
        assert result == {}

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.users_collection")
    async def test_returns_empty_when_no_metadata_key(
        self, mock_coll: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import get_all_provider_metadata

        mock_coll.find_one = AsyncMock(return_value={"name": "test"})
        result = await get_all_provider_metadata("507f1f77bcf86cd799439011")
        assert result == {}


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
        mock_store.assert_called_once_with("u1", "github", {"username": "octocat"})

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_no_integration(
        self, mock_get_int: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = None
        result = await fetch_and_store_provider_metadata("u1", "unknown")
        assert result is False

    @pytest.mark.asyncio
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_no_metadata_config(
        self, mock_get_int: MagicMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = _make_integration(metadata_config=None)
        result = await fetch_and_store_provider_metadata("u1", "github")
        assert result is False

    @pytest.mark.asyncio
    @patch(
        "app.services.provider_metadata_service.fetch_provider_user_info",
        new_callable=AsyncMock,
    )
    @patch("app.services.provider_metadata_service.get_integration_by_id")
    async def test_returns_false_when_fetch_fails(
        self, mock_get_int: MagicMock, mock_fetch: AsyncMock
    ) -> None:
        from app.services.provider_metadata_service import (
            fetch_and_store_provider_metadata,
        )

        mock_get_int.return_value = _make_integration(
            metadata_config=_make_metadata_config([])
        )
        mock_fetch.return_value = None
        result = await fetch_and_store_provider_metadata("u1", "github")
        assert result is False
