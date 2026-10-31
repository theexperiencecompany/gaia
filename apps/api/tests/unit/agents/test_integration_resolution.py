"""Tests for app.agents.core.subagents.integration_resolution and the custom-MCP index."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.core.subagents.integration_resolution import (
    CustomMcpSubagent,
    check_integration_connection,
    check_mcp_connection,
    get_integration_target,
    is_per_user_mcp,
)
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.db.repositories.user_integrations import user_integration_repository
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.services.mcp.custom_mcp_index import CustomMcpIndexRequest, index_custom_mcp_as_subagent

RESOLUTION = "app.agents.core.subagents.integration_resolution"
INDEX = "app.services.mcp.custom_mcp_index"


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
    }
    data.update(overrides)
    return Integration.model_validate(data)


def _make_subagent(
    subagent_id: str = "gmail",
    short_name: str | None = "gmail",
    name: str = "Gmail",
    managed_by: str = "internal",
    mcp_config: MCPConfig | None = None,
) -> Subagent:
    return Subagent(
        id=subagent_id,
        name=name,
        provider=subagent_id,
        managed_by=managed_by,  # type: ignore[arg-type]  # fixture uses a plain string for the managed_by Literal
        config=SubAgentConfig(
            has_subagent=True,
            agent_name=f"{subagent_id}_agent",
            tool_space=f"{subagent_id}_space",
            domain=subagent_id,
            capabilities="things",
            use_cases="things",
            system_prompt=f"You are {name}.",
        ),
        short_name=short_name,
        mcp_config=mcp_config,
    )


def _auth_mcp(subagent_id: str = "posthog", name: str = "PostHog") -> Subagent:
    return _make_subagent(
        subagent_id,
        subagent_id,
        name,
        managed_by="mcp",
        mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
    )


@contextmanager
def _ui_graph_run(writer: MagicMock, *, expired: bool = False) -> Iterator[None]:
    """Make the connect prompt believe it is running inside a UI chat turn."""
    with (
        patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ),
        patch("app.utils.integration_checker.current_stream_writer", return_value=writer),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=expired)),
    ):
        yield


def _connect_card_ids(writer: MagicMock) -> list[str]:
    return [
        call.args[0]["integration_connection_required"]["integration_id"]
        for call in writer.call_args_list
        if "integration_connection_required" in call.args[0]
    ]


def _get_meetings() -> str:
    return "meetings"


@contextmanager
def _token_store(connected: dict[str, bool]) -> Iterator[MagicMock]:
    """MCPTokenStore whose is_connected answers per integration id, so a swapped id changes the outcome."""
    with patch(f"{RESOLUTION}.MCPTokenStore") as store_cls:
        store = MagicMock()
        store.is_connected = AsyncMock(side_effect=lambda integration_id: connected[integration_id])
        store_cls.return_value = store
        yield store_cls


@pytest.mark.asyncio
class TestCheckIntegrationConnection:
    async def test_returns_none_when_integration_not_found(self):
        with patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None):
            assert await check_integration_connection("bogus", "user1") is None

    async def test_the_connection_check_is_scoped_to_this_user_and_integration(self):
        async def _status(integration_id: str, user_id: str) -> bool:
            return (integration_id, user_id) == ("gmail", "user1")

        with (
            patch(
                f"{RESOLUTION}.get_subagent_by_id",
                side_effect=lambda requested: _make_subagent() if requested == "gmail" else None,
            ),
            patch(f"{RESOLUTION}.check_integration_status", new=AsyncMock(side_effect=_status)),
        ):
            assert await check_integration_connection("gmail", "user1") is None

    async def test_not_connected_renders_the_card_and_names_the_integration(self):
        writer = MagicMock()
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=_make_subagent()),
            patch(f"{RESOLUTION}.check_integration_status", new=AsyncMock(return_value=False)),
            _ui_graph_run(writer),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None and result.startswith("Gmail needs to be connected")
        assert _connect_card_ids(writer) == ["gmail"]

    async def test_status_check_failure_propagates(self):
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=_make_subagent()),
            patch(
                f"{RESOLUTION}.check_integration_status",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await check_integration_connection("gmail", "user1")


@pytest.mark.asyncio
class TestGetIntegrationTarget:
    async def test_platform_integration_comes_from_the_registry_without_touching_the_cache(self):
        subagent = _make_subagent()
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=subagent) as lookup,
            patch(f"{RESOLUTION}.get_cache", new=AsyncMock()) as get_cache,
        ):
            result = await get_integration_target("  GMAIL ")

        assert result is subagent
        lookup.assert_called_once_with("gmail")
        get_cache.assert_not_awaited()

    async def test_returns_cached_custom_integration(self):
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None),
            patch(
                f"{RESOLUTION}.get_cache",
                new=AsyncMock(return_value={"id": "abc123", "name": "Custom MCP"}),
            ) as get_cache,
        ):
            result = await get_integration_target("abc123")

        assert result == CustomMcpSubagent(id="abc123", name="Custom MCP")
        get_cache.assert_awaited_once_with(f"{SUBAGENT_CACHE_PREFIX}:abc123")

    async def test_returns_none_for_negative_cache(self):
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None),
            patch(f"{RESOLUTION}.get_cache", new=AsyncMock(return_value={})),
            patch(f"{RESOLUTION}.integration_repository") as repo,
        ):
            repo.find_by_id_prefix_or_name = AsyncMock()
            assert await get_integration_target("missing") is None
        repo.find_by_id_prefix_or_name.assert_not_awaited()

    async def test_finds_custom_from_mongodb_and_caches_it(self):
        custom = _integration(
            "abc",
            "My MCP",
            mcp_config=MCPConfig(server_url="https://example.com"),
            icon_url="https://example.com/icon.png",
        )
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None),
            patch(f"{RESOLUTION}.get_cache", new=AsyncMock(return_value=None)),
            patch(f"{RESOLUTION}.integration_repository") as repo,
            patch(f"{RESOLUTION}.set_cache", new=AsyncMock()) as set_cache,
        ):
            repo.find_by_id_prefix_or_name = AsyncMock(return_value=custom)
            result = await get_integration_target("abc")

        expected = CustomMcpSubagent(
            id="abc",
            name="My MCP",
            source="custom",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com").model_dump(),
            icon_url="https://example.com/icon.png",
        )
        assert result == expected
        set_cache.assert_awaited_once_with(
            f"{SUBAGENT_CACHE_PREFIX}:abc", expected.model_dump(), ttl=SUBAGENT_CACHE_TTL
        )

    async def test_fallback_to_integration_resolver(self):
        resolved = SimpleNamespace(
            custom_doc={
                "integration_id": "res_id",
                "name": "Resolved",
                "mcp_config": {"server_url": "https://resolved.example.com"},
                "icon_url": "https://resolved.example.com/icon.png",
            },
            source="user_integrations",
        )
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None),
            patch(f"{RESOLUTION}.get_cache", new=AsyncMock(return_value=None)),
            patch(f"{RESOLUTION}.integration_repository") as repo,
            patch(f"{RESOLUTION}.IntegrationResolver") as resolver,
            patch(f"{RESOLUTION}.set_cache", new=AsyncMock()) as set_cache,
        ):
            repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            resolver.resolve = AsyncMock(return_value=resolved)
            result = await get_integration_target("res_id")

        expected = CustomMcpSubagent(
            id="res_id",
            name="Resolved",
            source="user_integrations",
            managed_by="mcp",
            mcp_config={"server_url": "https://resolved.example.com"},
            icon_url="https://resolved.example.com/icon.png",
        )
        assert result == expected
        set_cache.assert_awaited_once_with(
            f"{SUBAGENT_CACHE_PREFIX}:res_id", expected.model_dump(), ttl=SUBAGENT_CACHE_TTL
        )

    async def test_a_miss_everywhere_is_negatively_cached(self):
        with (
            patch(f"{RESOLUTION}.get_subagent_by_id", return_value=None),
            patch(f"{RESOLUTION}.get_cache", new=AsyncMock(return_value=None)),
            patch(f"{RESOLUTION}.integration_repository") as repo,
            patch(f"{RESOLUTION}.IntegrationResolver") as resolver,
            patch(f"{RESOLUTION}.set_cache", new=AsyncMock()) as set_cache,
        ):
            repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            resolver.resolve = AsyncMock(return_value=None)
            assert await get_integration_target("nope") is None

        set_cache.assert_awaited_once_with(
            f"{SUBAGENT_CACHE_PREFIX}:nope", {}, ttl=SUBAGENT_CACHE_TTL
        )


class TestIsPerUserMcp:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            (CustomMcpSubagent(id="abc"), True),
            (_auth_mcp(), True),
            (
                _make_subagent(
                    "deepwiki",
                    managed_by="mcp",
                    mcp_config=MCPConfig(server_url="https://example.com"),
                ),
                False,
            ),
            (_make_subagent("gmail", managed_by="composio"), False),
            (_make_subagent("todos", managed_by="internal"), False),
        ],
    )
    def test_only_custom_and_auth_required_mcp_are_per_user(
        self, target: Subagent | CustomMcpSubagent, expected: bool
    ) -> None:
        assert is_per_user_mcp(target) is expected


@pytest.mark.asyncio
class TestCheckMcpConnection:
    async def test_connected_auth_mcp_needs_nothing_and_is_checked_for_this_user(self):
        with (
            patch(f"{RESOLUTION}.get_integration_target", new=AsyncMock(return_value=_auth_mcp())),
            _token_store({"posthog": True}) as store_cls,
        ):
            assert await check_mcp_connection("posthog", "user1") is None
        store_cls.assert_called_once_with(user_id="user1")

    async def test_unconnected_auth_mcp_renders_the_connect_card(self):
        writer = MagicMock()
        with (
            patch(f"{RESOLUTION}.get_integration_target", new=AsyncMock(return_value=_auth_mcp())),
            _token_store({"posthog": False}),
            _ui_graph_run(writer),
        ):
            result = await check_mcp_connection("posthog", "user1")

        assert result is not None and result.startswith("PostHog needs to be connected")
        assert _connect_card_ids(writer) == ["posthog"]

    async def test_unconnected_custom_mcp_requiring_auth_is_gated_under_its_resolved_id(self):
        custom = CustomMcpSubagent(
            id="abc123",
            name="My MCP",
            managed_by="mcp",
            mcp_config={"server_url": "https://example.com", "requires_auth": True},
        )
        writer = MagicMock()
        with (
            patch(f"{RESOLUTION}.get_integration_target", new=AsyncMock(return_value=custom)),
            _token_store({"abc123": False}),
            _ui_graph_run(writer),
        ):
            result = await check_mcp_connection("my mcp", "user1")

        assert result is not None and result.startswith("My MCP needs to be connected")
        assert _connect_card_ids(writer) == ["abc123"]

    @pytest.mark.parametrize(
        "target",
        [
            None,
            CustomMcpSubagent(id="abc123", mcp_config={"server_url": "https://example.com"}),
            _make_subagent("gmail", managed_by="composio"),
            _make_subagent(
                "deepwiki", managed_by="mcp", mcp_config=MCPConfig(server_url="https://x.test")
            ),
        ],
    )
    async def test_targets_without_per_user_auth_are_never_gated(
        self, target: Subagent | CustomMcpSubagent | None
    ) -> None:
        with (
            patch(f"{RESOLUTION}.get_integration_target", new=AsyncMock(return_value=target)),
            patch(f"{RESOLUTION}.MCPTokenStore") as store_cls,
        ):
            assert await check_mcp_connection("anything", "user1") is None
        store_cls.assert_not_called()


@pytest.mark.asyncio
class TestIndexCustomMcpAsSubagent:
    async def test_indexes_identity_namespace_and_tool_summaries(self):
        store = AsyncMock()
        tool = StructuredTool.from_function(
            func=_get_meetings, name="get_meetings", description="List meetings.\nMore detail."
        )
        with patch(f"{INDEX}.derive_integration_namespace", return_value="example.com") as derive:
            await index_custom_mcp_as_subagent(
                store=store,
                request=CustomMcpIndexRequest(
                    integration_id="abc123",
                    name="My Tool",
                    description="Does stuff",
                    server_url="https://example.com/mcp",
                    tools=[tool],
                ),
            )

        derive.assert_called_once_with("abc123", "https://example.com/mcp", is_custom=True)
        store.abatch.assert_awaited_once()
        put_op = store.abatch.call_args[0][0][0]
        assert put_op.namespace == ("subagents",)
        assert put_op.key == "abc123"
        assert put_op.value == {
            "id": "abc123",
            "name": "My Tool",
            "description": "My Tool. Does stuff. Available tools: get_meetings: List meetings..",
            "source": "custom",
            "tool_namespace": "example.com",
        }
        assert put_op.index == ["description"]
