"""Exact-argument behaviour of integration_resolution's lookups and connect prompts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.integration_resolution import (
    check_integration_connection,
    check_mcp_connection,
)
from app.agents.core.subagents.integration_target import (
    CustomMcpSubagent,
    get_integration_target,
)
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent

RESOLUTION = "app.agents.core.subagents.integration_resolution"
TARGET = "app.agents.core.subagents.integration_target"


def _subagent() -> Subagent:
    return Subagent(
        id="gmail",
        name="Gmail",
        provider="gmail",
        managed_by="composio",
        config=SubAgentConfig(
            has_subagent=True,
            agent_name="gmail_agent",
            tool_space="gmail_space",
            domain="gmail",
            capabilities="things",
            use_cases="things",
            system_prompt="You are Gmail.",
        ),
        short_name="gmail",
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetIntegrationTargetLookupKeys:
    async def test_repository_and_resolver_receive_the_normalised_id(self) -> None:
        with (
            patch(f"{TARGET}.get_subagent_by_id", return_value=None),
            patch(f"{TARGET}.get_cache", new=AsyncMock(return_value=None)),
            patch(f"{TARGET}.set_cache", new=AsyncMock()),
            patch(f"{TARGET}.integration_repository") as repo,
            patch(f"{TARGET}.IntegrationResolver") as resolver,
        ):
            repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            resolver.resolve = AsyncMock(return_value=SimpleNamespace(custom_doc=None))
            assert await get_integration_target("  My-MCP ") is None

        repo.find_by_id_prefix_or_name.assert_awaited_once_with("my-mcp")
        resolver.resolve.assert_awaited_once_with("my-mcp")


@pytest.mark.unit
@pytest.mark.asyncio
class TestConnectPromptArguments:
    async def test_registry_integration_prompt_names_id_name_and_user(self) -> None:
        prompt_mock = AsyncMock(return_value="connect gmail")
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=_subagent()) as lookup,
            patch(f"{RESOLUTION}.check_integration_status", new=AsyncMock(return_value=False)),
            patch(f"{RESOLUTION}.request_integration_connection", new=prompt_mock),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result == "connect gmail"
        lookup.assert_called_once_with("gmail")
        prompt_mock.assert_awaited_once_with("gmail", "Gmail", "user1")

    async def test_mcp_prompt_names_id_name_and_user(self) -> None:
        target = CustomMcpSubagent(
            id="abc123",
            name="My MCP",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        resolve = AsyncMock(return_value=target)
        store = MagicMock()
        store.is_connected = AsyncMock(return_value=False)
        prompt = AsyncMock(return_value="connect mcp")
        with (
            patch(f"{RESOLUTION}.get_integration_target", new=resolve),
            patch(f"{RESOLUTION}.MCPTokenStore", return_value=store),
            patch(f"{RESOLUTION}.request_integration_connection", new=prompt),
        ):
            result = await check_mcp_connection("my mcp", "user1")

        assert result == "connect mcp"
        resolve.assert_awaited_once_with("my mcp")
        prompt.assert_awaited_once_with("abc123", "My MCP", "user1")
