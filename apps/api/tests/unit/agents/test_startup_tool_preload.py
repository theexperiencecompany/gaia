"""Startup tool preload: integration tools load as schema docs, never as bindings.

Regression contract for the execute-proxy cutover: a subagent's declared
startup tools (auto_bind_tools + extra_initial_tools) split by kind —
internal tools bind into initial_tool_ids as before, while integration
tools (Composio require_integration categories + per-user MCP) are
excluded from binding and instead render as schema docs injected into the
run's context, executed via execute.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool as langchain_tool
import pytest

from app.agents.core.subagents import handoff_tools
from app.agents.core.subagents.base_subagent import SubAgentFactory, SubAgentToolConfig
from app.agents.core.subagents.handoff_tools import prepare_subagent_execution
from app.agents.tools.core import retrieval
from app.agents.tools.execute.resolver import ResolvedTool
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event


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

    async def test_a_per_user_mcp_startup_tool_preloads_instead_of_binding(self) -> None:
        """No registry category knows a per-user MCP tool, so only the subagent's own MCP list marks it execute-routed."""
        mcp_tool = MagicMock(name="notion_search")
        mcp_tool.name = "notion_search"

        initial_ids = await self._initial_ids(
            SubAgentToolConfig(
                tool_space="mcp_notion",
                mcp_tools=[mcp_tool],
                auto_bind_tools=["notion_search"],
            ),
            _registry(integration_names=set(), internal_names=set()),
            ["notion_search"],
        )

        assert "notion_search" not in initial_ids
        assert "execute" in initial_ids


@pytest.mark.unit
class TestPrepareInjectsPreloadDocs:
    """prepare_subagent_execution opens the run with the integration's startup schemas inside the static system message — no binding, no retrieve_tools round trip."""

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_system_message_carries_preloaded_schemas(self) -> None:
        from langchain_core.tools import tool as langchain_tool

        from app.agents.core.subagents import handoff_tools
        from app.agents.tools.core import retrieval
        from app.agents.tools.execute.resolver import ResolvedTool

        captured: dict = {}

        async def _fake_build_initial_messages(**kwargs):
            captured.update(kwargs)
            return [kwargs["system_message"]]

        def _fake_resolved(name: str) -> ResolvedTool:
            @langchain_tool
            def _fake_tool(query: str) -> str:
                """Run a fake query."""
                return query

            _fake_tool.name = name
            return ResolvedTool(name=name, tool=_fake_tool, is_integration=True)

        split_registry = MagicMock()
        split_registry.get_category_of_tool.side_effect = (
            lambda n: "gmail" if n.startswith("GMAIL_") else "general"
        )

        def _get_category(name: str) -> MagicMock:
            category = MagicMock()
            category.require_integration = name == "gmail"
            return category

        split_registry.get_category.side_effect = _get_category

        with (
            patch.object(
                handoff_tools,
                "_resolve_subagent",
                new=AsyncMock(return_value=(MagicMock(), "gmail_agent", "gmail", False)),
            ),
            patch.object(
                handoff_tools,
                "build_agent_config",
                new=AsyncMock(
                    return_value={
                        "configurable": {
                            "thread_id": "t1",
                            "user_id": "u1",
                            "conversation_id": "c1",
                        }
                    }
                ),
            ),
            patch.object(handoff_tools, "get_provider_metadata", new=AsyncMock(return_value=None)),
            patch.object(
                handoff_tools,
                "build_initial_messages",
                side_effect=_fake_build_initial_messages,
            ),
            patch.object(
                retrieval, "get_tool_registry", new=AsyncMock(return_value=split_registry)
            ),
            patch.object(retrieval, "_user_mcp_tool_names", new=AsyncMock(return_value=set())),
            patch.object(
                retrieval,
                "_resolve_for_retrieval",
                new=AsyncMock(side_effect=lambda _u, n: _fake_resolved(n)),
            ),
        ):
            from app.agents.core.subagents.handoff_tools import prepare_subagent_execution

            ctx, _, error = await prepare_subagent_execution(
                "gmail", "List my inbox", {"user_id": "u1", "thread_id": "t1"}
            )

        assert error is None
        system_message = captured["system_message"]
        assert system_message.type == "system"
        # The real static prompt is intact and the preloaded schemas follow it
        # in the same singleton STATIC message.
        assert "## GMAIL_FETCH_MESSAGES" in system_message.content
        assert "execute(" in system_message.content
        assert "NOT bound" in system_message.content
        assert ctx is not None

    async def test_no_declared_tools_leaves_system_message_untouched(self) -> None:
        from app.agents.core.subagents import handoff_tools

        captured: dict = {}

        async def _fake_build_initial_messages(**kwargs):
            captured.update(kwargs)
            return [kwargs["system_message"]]

        with (
            patch.object(
                handoff_tools,
                "_resolve_subagent",
                new=AsyncMock(return_value=(MagicMock(), "docgen_agent", "docgen", False)),
            ),
            patch.object(
                handoff_tools,
                "build_agent_config",
                new=AsyncMock(
                    return_value={
                        "configurable": {
                            "thread_id": "t1",
                            "user_id": "u1",
                            "conversation_id": "c1",
                        }
                    }
                ),
            ),
            patch.object(handoff_tools, "get_provider_metadata", new=AsyncMock(return_value=None)),
            patch.object(
                handoff_tools,
                "build_initial_messages",
                side_effect=_fake_build_initial_messages,
            ),
        ):
            from app.agents.core.subagents.handoff_tools import prepare_subagent_execution

            _, _, error = await prepare_subagent_execution(
                "docgen", "Make a PDF", {"user_id": "u1", "thread_id": "t1"}
            )

        assert error is None
        # docgen declares no startup tools and binds direct — no docs appended.
        assert "preloaded below" not in captured["system_message"].content


@contextmanager
def _prepared_gmail_run(preload: AsyncMock) -> Iterator[dict[str, Any]]:
    """Resolve gmail for u1 with a fixed static prompt; yield what build_initial_messages got."""
    captured: dict[str, Any] = {}

    async def _capture(**kwargs: Any) -> list[SystemMessage]:
        captured.update(kwargs)
        return [kwargs["system_message"]]

    config = {"configurable": {"thread_id": "t1", "user_id": "u1", "conversation_id": "c1"}}
    with (
        patch.object(
            handoff_tools,
            "_resolve_subagent",
            new=AsyncMock(return_value=(MagicMock(), "gmail_agent", "gmail", False)),
        ),
        patch.object(handoff_tools, "build_agent_config", new=AsyncMock(return_value=config)),
        patch.object(
            handoff_tools,
            "create_subagent_system_message",
            new=AsyncMock(return_value=SystemMessage(content="STATIC GMAIL PROMPT")),
        ),
        patch.object(handoff_tools, "get_provider_metadata", new=AsyncMock(return_value=None)),
        patch.object(handoff_tools, "build_initial_messages", side_effect=_capture),
        patch.object(handoff_tools, "preloaded_startup_docs", new=preload),
    ):
        yield captured


@pytest.mark.unit
class TestPrepareAppendsThePreloadBlock:
    async def test_the_block_is_built_for_the_calling_user_and_follows_the_static_prompt(
        self,
    ) -> None:
        preload = AsyncMock(return_value="## GMAIL_FETCH_MESSAGES")
        with _prepared_gmail_run(preload) as captured:
            await prepare_subagent_execution("gmail", "List my inbox", {"user_id": "u1"})

        preload.assert_awaited_once_with("u1", "gmail")
        assert captured["system_message"].content == (
            "STATIC GMAIL PROMPT\n\n## GMAIL_FETCH_MESSAGES"
        )

    async def test_unavailable_docs_leave_the_static_prompt_as_is_and_say_why(self) -> None:
        preload = AsyncMock(side_effect=RuntimeError("registry down"))
        with _prepared_gmail_run(preload) as captured:
            async with captured_wide_event() as event:
                ctx, _, error = await prepare_subagent_execution(
                    "gmail", "List my inbox", {"user_id": "u1"}
                )

        assert error is None
        assert ctx is not None
        assert captured["system_message"].content == "STATIC GMAIL PROMPT"
        (warning,) = event["warnings"]
        assert warning["msg"] == (
            f"{LogTag.AGENT} Startup tool docs unavailable; continuing without them"
        )
        assert (warning["integration_id"], warning["error_type"]) == ("gmail", "RuntimeError")


@langchain_tool
def GMAIL_FETCH_MESSAGES(thread_id: str) -> str:
    """Fetch one Gmail thread by id."""
    return thread_id


def _integration(
    *,
    use_direct_tools: bool = False,
    auto_bind_tools: list[str] | None = None,
    extra_initial_tools: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            use_direct_tools=use_direct_tools,
            auto_bind_tools=auto_bind_tools,
            extra_initial_tools=extra_initial_tools,
        )
    )


@pytest.mark.unit
class TestPreloadedStartupDocs:
    @pytest.mark.parametrize(
        "subagent",
        [
            None,
            _integration(use_direct_tools=True, auto_bind_tools=["GMAIL_FETCH_MESSAGES"]),
            _integration(),
        ],
        ids=["unknown_integration", "direct_tools_graph", "nothing_declared"],
    )
    async def test_integrations_with_no_docs_to_preload_get_an_empty_block(
        self, subagent: SimpleNamespace | None
    ) -> None:
        with patch.object(retrieval, "get_subagent_by_id", return_value=subagent):
            assert await retrieval.preloaded_startup_docs("u1", "gmail") == ""

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_extra_initial_tools_preload_for_the_calling_user(self) -> None:
        mcp_names = AsyncMock(return_value=set())
        resolver = AsyncMock(
            return_value=ResolvedTool("GMAIL_FETCH_MESSAGES", GMAIL_FETCH_MESSAGES, True)
        )
        registry = _registry(integration_names={"GMAIL_FETCH_MESSAGES"}, internal_names=set())
        with (
            patch.object(
                retrieval,
                "get_subagent_by_id",
                return_value=_integration(extra_initial_tools=["GMAIL_FETCH_MESSAGES"]),
            ),
            patch.object(retrieval, "get_tool_registry", new=AsyncMock(return_value=registry)),
            patch.object(retrieval, "_user_mcp_tool_names", new=mcp_names),
            patch.object(retrieval, "resolve_tool", new=resolver),
        ):
            block = await retrieval.preloaded_startup_docs("u1", "gmail")
        assert "## GMAIL_FETCH_MESSAGES" in block
        mcp_names.assert_awaited_once_with("u1")
        resolver.assert_awaited_once_with("u1", "GMAIL_FETCH_MESSAGES")
