"""Infra tests for tool runtime configuration and spawned subagent tool wiring."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
import pytest

from app.agents.core.subagents.base_subagent import SubAgentFactory
from app.agents.core.subagents.spawn_agent import _build_spawn_graph
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.tools.core.registry import ToolRegistry
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_child_tool_runtime_config,
    build_create_agent_tool_kwargs,
    build_executor_child_tool_runtime_config,
    build_provider_parent_tool_runtime_config,
)
from app.constants.general import FINISH_TASK_NAME
from app.override.langgraph_bigtool.create_agent import create_agent


@tool
def vfs_read(path: str = "") -> str:
    """Test vfs read tool."""
    return f"read:{path}"


@tool
def normal_tool(value: str = "") -> str:
    """Test normal tool."""
    return f"ok:{value}"


@tool
def handoff(task: str = "") -> str:
    """Test handoff tool."""
    return task


@tool
def spawn_subagent(task: str = "") -> str:
    """Test spawn tool."""
    return task


class _FakeLLM:
    """Simple fake LLM for create_agent flow tests."""

    def __init__(self) -> None:
        self.bind_calls: list[list[str]] = []
        self._invoke_count = 0

    def with_config(self, configurable: dict[str, Any] | None = None) -> "_FakeLLM":
        return self

    def bind_tools(self, tools: list[Any]) -> "_FakeLLM":
        names = [getattr(t, "name", str(t)) for t in tools]
        self.bind_calls.append(names)
        return self

    def with_retry(self, **_kwargs: Any) -> "_FakeLLM":
        # ainvoke_llm/invoke_llm wrap the bound model in with_llm_retry before
        # invoking; the fake retry is a no-op passthrough.
        return self

    async def ainvoke(self, _messages: list[Any], config: Any = None) -> AIMessage:
        self._invoke_count += 1
        if self._invoke_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "_dummy_retrieve_tools",
                        "args": {"exact_tool_names": ["subagent:gmail", "normal_tool"]},
                    }
                ],
            )
        return AIMessage(content="done", tool_calls=[])

    def invoke(self, _messages: list[Any], config: Any = None) -> AIMessage:
        self._invoke_count += 1
        if self._invoke_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "_dummy_retrieve_tools",
                        "args": {"exact_tool_names": ["subagent:gmail", "normal_tool"]},
                    }
                ],
            )
        return AIMessage(content="done", tool_calls=[])


def _dummy_retrieve_tools(**_kwargs: Any) -> dict[str, list[str]]:
    """Dummy retrieve_tools for create_agent flow test."""
    return {
        "tools_to_bind": ["subagent:gmail", "normal_tool"],
        "response": ["subagent:gmail", "normal_tool"],
    }


async def _dummy_retrieve_tools_async(**_kwargs: Any) -> dict[str, list[str]]:
    """Async dummy retrieve_tools for create_agent flow test."""
    return _dummy_retrieve_tools()


class _DummyCategory:
    def __init__(self, space: str, tools: list[BaseTool]):
        self.space = space
        self.tools = [SimpleNamespace(name=t.name, tool=t) for t in tools]


class _DummyRegistry:
    def __init__(self, category_tools: list[BaseTool], full_tools: dict[str, BaseTool]):
        self._category = _DummyCategory("provider_space", category_tools)
        self._full_tools = full_tools

    def get_category_by_space(self, space: str):
        return self._category if space == "provider_space" else None

    def get_tool_dict(self):
        return dict(self._full_tools)


class _DummyBuilder:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.kwargs = kwargs

    def compile(self, **_kwargs: Any) -> object:
        return object()


class _FakeStore:
    """Minimal async store for retrieval query tests."""

    def __init__(self, data: dict[tuple[str, ...], list[Any]]) -> None:
        self._data = data
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    async def asearch(
        self,
        namespace: tuple[str, ...],
        query: str = "",
        limit: int = 25,
    ) -> list[Any]:
        self.calls.append((namespace, query, limit))
        return self._data.get(namespace, [])


class _RetrieveRegistry:
    """Registry behavior needed by retrieval.py."""

    def __init__(self, tool_names: list[str]) -> None:
        self._tool_names = tool_names

    def get_tool_names(self):
        return self._tool_names

    def get_category_of_tool(self, tool_name: str) -> str:
        if tool_name == "delegated_tool":
            return "delegated_cat"
        return "general_cat"

    def get_category(self, name: str):
        if name == "delegated_cat":
            return SimpleNamespace(is_delegated=True)
        return SimpleNamespace(is_delegated=False)


async def _run_provider_subagent_factory(
    *,
    use_direct_tools: bool,
    disable_retrieve_tools: bool,
    auto_bind_tools: list[str] | None = None,
) -> tuple[dict[str, Any], SubagentMiddleware]:
    """Run SubAgentFactory with patched infra and capture wiring kwargs."""
    provider_tool = normal_tool
    full_tools = {
        "normal_tool": normal_tool,
        "vfs_read": vfs_read,
        "search_memory": normal_tool,
        "auto_tool": normal_tool,
    }
    dummy_registry = _DummyRegistry([provider_tool], full_tools)
    captured_kwargs: dict[str, Any] = {}

    def _fake_create_agent(**kwargs: Any):
        captured_kwargs.update(kwargs)
        return _DummyBuilder(kwargs)

    mw = SubagentMiddleware(
        llm=None,
        tool_registry=full_tools,
        store=MagicMock(),
        tool_runtime_config=ToolRuntimeConfig(initial_tool_names=["vfs_read"]),
    )

    with (
        patch(
            "app.agents.core.subagents.base_subagent.get_tools_store",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_tool_registry",
            new=AsyncMock(return_value=dummy_registry),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.create_agent",
            new=_fake_create_agent,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.create_subagent_middleware",
            return_value=[mw],
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: object())),
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            llm=MagicMock(),
            tool_space="provider_space",
            use_direct_tools=use_direct_tools,
            disable_retrieve_tools=disable_retrieve_tools,
            auto_bind_tools=auto_bind_tools,
        )

    return captured_kwargs, mw


@pytest.mark.asyncio
async def test_tool_runtime_config_builders_cover_direct_and_dynamic_modes():
    parent_dynamic = build_provider_parent_tool_runtime_config(
        provider_tool_names=["p1", "p2"],
        todo_tool_names=["t1"],
        auto_bind_tool_names=["auto1"],
        use_direct_tools=False,
        disable_retrieve_tools=False,
    )
    assert parent_dynamic.enable_retrieve_tools is True
    assert "read" in parent_dynamic.initial_tool_names
    assert "auto1" in parent_dynamic.initial_tool_names

    child_dynamic = build_child_tool_runtime_config(
        parent_dynamic, use_direct_tools=False, disable_retrieve_tools=False
    )
    assert child_dynamic.enable_retrieve_tools is True
    assert child_dynamic.initial_tool_names == ["read", "bash", "finish_task"]

    parent_direct = build_provider_parent_tool_runtime_config(
        provider_tool_names=["p1", "p2"],
        todo_tool_names=["t1"],
        auto_bind_tool_names=None,
        use_direct_tools=True,
        disable_retrieve_tools=True,
    )
    child_direct = build_child_tool_runtime_config(
        parent_direct, use_direct_tools=True, disable_retrieve_tools=True
    )
    assert child_direct.enable_retrieve_tools is False
    assert "p1" in child_direct.initial_tool_names
    assert "read" in child_direct.initial_tool_names

    executor_child = build_executor_child_tool_runtime_config()
    assert executor_child.enable_retrieve_tools is True
    assert executor_child.initial_tool_names == ["read", "bash", "finish_task"]

    kwargs = build_create_agent_tool_kwargs(parent_dynamic, tool_space="provider_space")
    assert "initial_tool_ids" in kwargs
    assert "retrieve_tools_coroutine" in kwargs


async def _spawn_graph_agent_kwargs(
    *, registry: dict[str, BaseTool], excluded: set[str], runtime: ToolRuntimeConfig
) -> dict[str, Any]:
    """The kwargs ``_build_spawn_graph`` hands to ``create_agent`` for this config.

    Store, checkpointer and agent builder are stubbed because they are the
    boundaries; the scoping under test is the real production code between them.
    """
    captured: dict[str, Any] = {}

    def _fake_create_agent(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(compile=lambda **_kwargs: MagicMock())

    with (
        patch("app.agents.core.subagents.spawn_agent.get_tools_store", new=AsyncMock()),
        patch(
            "app.agents.core.subagents.spawn_agent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: MagicMock())),
        ),
        patch("app.agents.core.subagents.spawn_agent.create_agent", new=_fake_create_agent),
    ):
        await _build_spawn_graph(
            llm=_FakeLLM(),
            registry=registry,
            excluded_tool_names=excluded,
            tool_space="provider_space",
            runtime=runtime,
            middleware_factory=list,
        )
    return captured


@pytest.mark.asyncio
async def test_spawn_graph_scopes_the_registry_to_what_the_parent_allows():
    # A spawn must not be able to spawn again, so the excluded set is applied
    # before create_agent ever sees the registry. finish_task is added back:
    # a one-shot agent with no way to declare itself done never terminates.
    captured = await _spawn_graph_agent_kwargs(
        registry={
            "vfs_read": vfs_read,
            "normal_tool": normal_tool,
            "spawn_subagent": spawn_subagent,
        },
        excluded={"spawn_subagent"},
        runtime=ToolRuntimeConfig(initial_tool_names=["vfs_read"], enable_retrieve_tools=True),
    )

    bindable = set(captured["tool_registry"])
    assert "spawn_subagent" not in bindable
    assert {"vfs_read", "normal_tool", FINISH_TASK_NAME} <= bindable
    assert "retrieve_tools_coroutine" in captured


@pytest.mark.asyncio
async def test_spawn_graph_disables_retrieve_when_the_parent_did():
    captured = await _spawn_graph_agent_kwargs(
        registry={"vfs_read": vfs_read},
        excluded={"spawn_subagent"},
        runtime=ToolRuntimeConfig(initial_tool_names=["vfs_read"], enable_retrieve_tools=False),
    )

    assert captured["disable_retrieve_tools"] is True
    assert "retrieve_tools_coroutine" not in captured


@pytest.mark.asyncio
async def test_spawned_retrieve_cannot_bind_back_an_excluded_tool():
    # The scoped registry travels on as retrieve_tools' bindable set, so a tool
    # the parent excluded cannot be pulled back in at retrieval time.
    captured = await _spawn_graph_agent_kwargs(
        registry={"vfs_read": vfs_read, "normal_tool": normal_tool, "handoff": handoff},
        excluded={"handoff"},
        runtime=build_executor_child_tool_runtime_config(),
    )

    with patch(
        "app.agents.tools.core.retrieval.get_tool_registry",
        new=AsyncMock(return_value=_RetrieveRegistry(["normal_tool", "vfs_read", "handoff"])),
    ):
        result = await captured["retrieve_tools_coroutine"](
            store=MagicMock(),
            config={"configurable": {"user_id": "u1"}},
            exact_tool_names=["subagent:gmail", "handoff", "normal_tool"],
        )

    assert "subagent:gmail" not in result["tools_to_bind"]
    assert "handoff" not in result["tools_to_bind"]
    assert "normal_tool" in result["tools_to_bind"]


@pytest.mark.asyncio
async def test_retrieval_exact_mode_excludes_subagents_when_disabled():
    retrieve_tools = get_retrieve_tools_function(
        tool_space="provider_space", include_subagents=False
    )
    registry = _RetrieveRegistry(["normal_tool", "vfs_read", "handoff"])
    with patch(
        "app.agents.tools.core.retrieval.get_tool_registry",
        new=AsyncMock(return_value=registry),
    ):
        result = await retrieve_tools(
            store=MagicMock(),
            config={"configurable": {"user_id": "u1"}},
            exact_tool_names=["subagent:gmail", "normal_tool", "handoff"],
        )

    assert "subagent:gmail" not in result["tools_to_bind"]
    assert "normal_tool" in result["tools_to_bind"]
    assert "handoff" in result["tools_to_bind"]


@pytest.mark.asyncio
async def test_retrieval_query_mode_excludes_subagent_results_inside_spawned_agent():
    retrieve_tools = get_retrieve_tools_function(
        tool_space="provider_space", include_subagents=False
    )
    registry = _RetrieveRegistry(["normal_tool", "vfs_read", "web_search", "fetch_webpages"])
    store = _FakeStore(
        {
            ("provider_space",): [
                SimpleNamespace(
                    key="normal_tool",
                    score=0.9,
                    namespace=("provider_space",),
                    value={},
                ),
                SimpleNamespace(
                    key="subagent:gmail",
                    score=0.8,
                    namespace=("provider_space",),
                    value={},
                ),
            ],
            ("general",): [
                SimpleNamespace(key="fetch_webpages", score=0.7, namespace=("general",), value={}),
                SimpleNamespace(
                    key="random_general_tool",
                    score=0.6,
                    namespace=("general",),
                    value={},
                ),
            ],
            ("subagents",): [
                SimpleNamespace(
                    key="gmail",
                    score=1.0,
                    namespace=("subagents",),
                    value={"name": "Gmail"},
                )
            ],
        }
    )

    with (
        patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new=AsyncMock(return_value=registry),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
            new=AsyncMock(return_value={"provider_space", "general", "subagents"}),
        ),
    ):
        result = await retrieve_tools(
            store=store,
            config={"configurable": {"user_id": "u1"}},
            query="find tools",
            exact_tool_names=[],
        )

    # No subagent tools in spawned-agent retrieve flow.
    assert all(not item.startswith("subagent:") for item in result["response"])
    # General namespace is filtered to webpage tools only when tool_space != general.
    assert "fetch_webpages" in result["response"]
    assert "random_general_tool" not in result["response"]
    # subagents namespace should not even be queried in include_subagents=False mode.
    searched_namespaces = {ns for ns, _q, _l in store.calls}
    assert ("subagents",) not in searched_namespaces


@pytest.mark.asyncio
async def test_retrieval_query_mode_includes_subagents_when_enabled_and_filters_delegated():
    retrieve_tools = get_retrieve_tools_function(tool_space="general", include_subagents=True)
    registry = _RetrieveRegistry(["normal_tool", "delegated_tool"])
    store = _FakeStore(
        {
            ("general",): [
                SimpleNamespace(key="normal_tool", score=0.8, namespace=("general",), value={}),
                SimpleNamespace(key="delegated_tool", score=0.9, namespace=("general",), value={}),
            ],
            ("subagents",): [
                SimpleNamespace(
                    key="gmail",
                    score=1.0,
                    namespace=("subagents",),
                    value={"name": "Gmail"},
                )
            ],
        }
    )

    with (
        patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new=AsyncMock(return_value=registry),
        ),
        patch(
            "app.agents.tools.core.retrieval._get_user_context",
            # _get_user_context returns (user_namespaces, connected_integrations, internal_subagents).
            # connected_integrations is dict[str, str | None]; internal_subagents is set[str].
            new=AsyncMock(return_value=({"general", "subagents"}, {}, set())),
        ),
        patch(
            "app.agents.tools.core.retrieval.search_public_integrations",
            new=AsyncMock(
                return_value=[
                    {
                        "integration_id": "pub123",
                        "name": "Public MCP",
                        "relevance_score": 0.5,
                    }
                ]
            ),
        ),
    ):
        result = await retrieve_tools(
            store=store,
            config={"configurable": {"user_id": "u1"}},
            query="anything",
            exact_tool_names=[],
        )

    # delegated direct tools are filtered in include_subagents=True mode
    assert "delegated_tool" not in result["response"]
    assert "normal_tool" in result["response"]
    # subagent discovery is present
    assert any(item.startswith("subagent:gmail") for item in result["response"])
    assert any(item.startswith("subagent:pub123") for item in result["response"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_agent_filters_subagent_from_direct_binding():
    fake_llm = _FakeLLM()
    builder = create_agent(
        llm=fake_llm,  # type: ignore[arg-type]
        tool_registry={"normal_tool": normal_tool},
        retrieve_tools_function=_dummy_retrieve_tools,
        retrieve_tools_coroutine=_dummy_retrieve_tools_async,
        initial_tool_ids=[],
        disable_retrieve_tools=False,
        middleware=[],
    )
    graph = builder.compile()

    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="run")],
            "selected_tool_ids": [],
        }
    )

    # Binding occurs and only directly-bindable tools are retained.
    assert fake_llm.bind_calls
    assert any("normal_tool" in call for call in fake_llm.bind_calls[1:])
    assert all("subagent:gmail" not in call for call in fake_llm.bind_calls)


@pytest.mark.asyncio
async def test_tool_registry_core_contains_vfs_read():
    registry = ToolRegistry()
    await registry.setup()
    names = registry.get_tool_names()
    # VFS tools were replaced by E2B sandbox coding tools (read, bash, write, edit).
    assert "read" in names


@pytest.mark.asyncio
async def test_base_subagent_wiring_uses_shared_tool_runtime_helpers():
    provider_tool = normal_tool
    full_tools = {
        "normal_tool": normal_tool,
        "vfs_read": vfs_read,
        "search_memory": normal_tool,
    }
    dummy_registry = _DummyRegistry([provider_tool], full_tools)

    captured_kwargs: dict[str, Any] = {}

    def _fake_create_agent(**kwargs: Any):
        captured_kwargs.update(kwargs)
        return _DummyBuilder(kwargs)

    with (
        patch(
            "app.agents.core.subagents.base_subagent.get_tools_store",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_tool_registry",
            new=AsyncMock(return_value=dummy_registry),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.create_agent",
            new=_fake_create_agent,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: object())),
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            llm=MagicMock(),
            tool_space="provider_space",
            use_direct_tools=True,
            disable_retrieve_tools=True,
            auto_bind_tools=None,
        )

    assert captured_kwargs["disable_retrieve_tools"] is True
    assert "retrieve_tools_coroutine" not in captured_kwargs
    assert "read" in captured_kwargs["initial_tool_ids"]
    assert "normal_tool" in captured_kwargs["initial_tool_ids"]


@pytest.mark.asyncio
async def test_base_subagent_dynamic_mode_wires_retrieve_and_auto_bind():
    captured_kwargs, mw = await _run_provider_subagent_factory(
        use_direct_tools=False,
        disable_retrieve_tools=False,
        auto_bind_tools=["normal_tool", "missing_tool"],
    )

    assert "retrieve_tools_coroutine" in captured_kwargs
    assert "disable_retrieve_tools" not in captured_kwargs
    assert "search_memory" in captured_kwargs["initial_tool_ids"]
    assert "read" in captured_kwargs["initial_tool_ids"]
    assert "normal_tool" in captured_kwargs["initial_tool_ids"]
    assert "missing_tool" not in captured_kwargs["initial_tool_ids"]
    # spawned child for dynamic mode should keep minimal initial tools
    assert mw._tool_runtime_config.initial_tool_names == ["read", "bash", "finish_task"]
    assert mw._tool_runtime_config.enable_retrieve_tools is True


@pytest.mark.asyncio
async def test_base_subagent_direct_mode_propagates_child_direct_runtime():
    captured_kwargs, mw = await _run_provider_subagent_factory(
        use_direct_tools=True,
        disable_retrieve_tools=True,
    )

    assert captured_kwargs["disable_retrieve_tools"] is True
    assert "retrieve_tools_coroutine" not in captured_kwargs
    assert "read" in captured_kwargs["initial_tool_ids"]
    assert "normal_tool" in captured_kwargs["initial_tool_ids"]
    assert mw._tool_runtime_config.enable_retrieve_tools is False
    assert "normal_tool" in mw._tool_runtime_config.initial_tool_names
    assert "read" in mw._tool_runtime_config.initial_tool_names
