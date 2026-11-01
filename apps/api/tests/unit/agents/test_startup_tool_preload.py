"""Startup tool preload: integration tools load as schema docs, never as bindings.

Regression contract for the execute-proxy cutover: a subagent's declared
startup tools (auto_bind_tools + extra_initial_tools) split by kind —
internal tools bind into initial_tool_ids as before, while integration
tools (Composio require_integration categories + per-user MCP) are
excluded from binding and instead render as schema docs injected into the
run's context, executed via execute.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.base_subagent import SubAgentFactory, SubAgentToolConfig
from app.agents.tools.core import retrieval


def _category(*, require_integration: bool, tool_names: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        require_integration=require_integration,
        tools=[SimpleNamespace(name=n, tool=MagicMock(name=n)) for n in tool_names],
    )


def _registry(
    *,
    integration_names: set[str],
    internal_names: set[str],
) -> MagicMock:
    """Build a registry where ALLCAPS names are integration tools, the rest internal."""
    registry = MagicMock()
    registry.get_category_of_tool.side_effect = (
        lambda n: "int_cat" if n in integration_names else "general"
    )

    def _get_category(name: str) -> SimpleNamespace | None:
        if name == "int_cat":
            return _category(require_integration=True, tool_names=sorted(integration_names))
        if name == "general":
            return _category(require_integration=False, tool_names=sorted(internal_names))
        return None

    registry.get_category.side_effect = _get_category
    registry.get_category_by_space.side_effect = lambda space: (
        _category(require_integration=True, tool_names=sorted(integration_names))
        if space == "gmail"
        else None
    )
    return registry


@pytest.mark.unit
class TestSplitStartupTools:
    async def test_integration_tools_preload_while_internal_tools_bind(self) -> None:
        from app.agents.tools.core import retrieval

        with patch.object(
            retrieval,
            "get_tool_registry",
            new=AsyncMock(
                return_value=_registry(
                    integration_names={"GMAIL_FETCH_MESSAGES"},
                    internal_names={"query_json"},
                )
            ),
        ):
            bind, preload = await retrieval.split_startup_tools(
                None, ["GMAIL_FETCH_MESSAGES", "query_json"]
            )
        assert bind == ["query_json"]
        assert preload == ["GMAIL_FETCH_MESSAGES"]

    async def test_mcp_tool_names_preload(self) -> None:
        from app.agents.tools.core import retrieval

        registry = _registry(integration_names=set(), internal_names=set())
        with patch.object(retrieval, "get_tool_registry", new=AsyncMock(return_value=registry)):
            bind, preload = await retrieval.split_startup_tools(
                "u1", ["MY_MCP_TOOL"], mcp_tool_names={"MY_MCP_TOOL"}
            )
        assert bind == []
        assert preload == ["MY_MCP_TOOL"]

    async def test_empty_declaration_splits_empty(self) -> None:
        from app.agents.tools.core import retrieval

        with patch.object(
            retrieval,
            "get_tool_registry",
            new=AsyncMock(return_value=_registry(integration_names=set(), internal_names=set())),
        ):
            assert await retrieval.split_startup_tools(None, []) == ([], [])
            assert await retrieval.split_startup_tools(None, None) == ([], [])

    async def test_order_is_stable_and_duplicates_collapse(self) -> None:
        from app.agents.tools.core import retrieval

        with patch.object(
            retrieval,
            "get_tool_registry",
            new=AsyncMock(
                return_value=_registry(
                    integration_names={"GMAIL_A"},
                    internal_names={"query_json"},
                )
            ),
        ):
            bind, preload = await retrieval.split_startup_tools(
                None, ["GMAIL_A", "query_json", "GMAIL_A"]
            )
        assert bind == ["query_json"]
        assert preload == ["GMAIL_A"]

    async def test_mcp_names_are_fetched_for_the_calling_user(self) -> None:
        registry = _registry(integration_names=set(), internal_names=set())
        mcp_names = AsyncMock(return_value={"MY_MCP_TOOL"})
        with (
            patch.object(retrieval, "get_tool_registry", new=AsyncMock(return_value=registry)),
            patch.object(retrieval, "_user_mcp_tool_names", new=mcp_names),
        ):
            bind, preload = await retrieval.split_startup_tools("u1", ["MY_MCP_TOOL"])
        assert (bind, preload) == ([], ["MY_MCP_TOOL"])
        mcp_names.assert_awaited_once_with("u1")


@pytest.mark.unit
class TestRenderPreloadBlock:
    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_renders_docs_with_execute_guidance(self) -> None:
        from langchain_core.tools import tool as langchain_tool

        from app.agents.tools.core import retrieval
        from app.agents.tools.execute.resolver import ResolvedTool

        @langchain_tool
        def GMAIL_FETCH_MESSAGES(thread_id: str) -> str:
            """Fetch one Gmail thread by id."""
            return thread_id

        resolved = ResolvedTool(
            name="GMAIL_FETCH_MESSAGES",
            tool=GMAIL_FETCH_MESSAGES,
            is_integration=True,
        )
        with patch.object(
            retrieval, "_resolve_for_retrieval", new=AsyncMock(return_value=resolved)
        ):
            block = await retrieval.render_preload_block("u1", ["GMAIL_FETCH_MESSAGES"])
        assert "## GMAIL_FETCH_MESSAGES" in block
        assert "execute(" in block
        assert "NOT bound" in block

    async def test_empty_preload_renders_empty(self) -> None:
        from app.agents.tools.core import retrieval

        assert await retrieval.render_preload_block("u1", []) == ""

    async def test_unresolvable_tools_degrade_to_empty_with_warning(self) -> None:
        from app.agents.tools.core import retrieval

        with patch.object(retrieval, "_resolve_for_retrieval", new=AsyncMock(return_value=None)):
            assert await retrieval.render_preload_block("u1", ["GMAIL_GHOST"]) == ""


@pytest.mark.unit
class TestFactoryDoesNotBindIntegrationTools:
    """The bug pin: gmail-style auto_bind integration tools must not reach initial_tool_ids (provider bind_tools).

    Internal extras still do.
    """

    @staticmethod
    async def _initial_ids(
        config: SubAgentToolConfig, registry: MagicMock, provider_tool_ids: list[str]
    ) -> list[str]:
        names = [*provider_tool_ids, "search_memory", "read", "bash", "execute"]
        scoped = {name: MagicMock(name=name) for name in [*names, "get_tool_schema"]}
        for name, tool in scoped.items():
            tool.name = name
        captured: dict = {}

        def _fake_create_agent(**kwargs):
            captured.update(kwargs)
            builder = MagicMock()
            builder.compile.return_value = MagicMock()
            return builder

        with (
            patch(
                "app.agents.core.subagents.base_subagent.get_tools_store",
                new=AsyncMock(),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.get_tool_registry",
                new=AsyncMock(return_value=registry),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.build_scoped_tool_dict",
                return_value=(scoped, provider_tool_ids),
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_subagent_middleware",
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_todo_tools",
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_todo_pre_model_hook",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.base_subagent.worker_pre_model_hooks",
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.base_subagent.create_agent",
                side_effect=_fake_create_agent,
            ),
            patch(
                "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
                new=AsyncMock(
                    return_value=MagicMock(get_checkpointer=MagicMock(return_value=MagicMock()))
                ),
            ),
        ):
            await SubAgentFactory.create_provider_subagent(
                provider="gmail", name="gmail_agent", llm=MagicMock(), config=config
            )
        return list(captured["tools_config"].initial_tool_ids)

    async def test_integration_auto_bind_excluded_from_initial_ids(self) -> None:
        initial_ids = await self._initial_ids(
            SubAgentToolConfig(
                tool_space="gmail",
                auto_bind_tools=["GMAIL_FETCH_MESSAGES"],
                extra_initial_tools=["query_json"],
            ),
            _registry(integration_names={"GMAIL_FETCH_MESSAGES"}, internal_names={"query_json"}),
            ["GMAIL_FETCH_MESSAGES", "query_json"],
        )

        assert "query_json" in initial_ids
        assert "GMAIL_FETCH_MESSAGES" not in initial_ids
        # The proxy itself always binds: preloaded docs are unusable without it.
        assert "execute" in initial_ids
        assert "get_tool_schema" in initial_ids
