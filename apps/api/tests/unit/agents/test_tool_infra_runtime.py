"""Infra tests for tool runtime configuration and spawned subagent tool wiring."""

from dataclasses import dataclass
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
import pytest

from app.agents.core.nodes.pre_model_hooks import worker_pre_model_hooks
from app.agents.core.subagents.base_subagent import SubAgentFactory, SubAgentToolConfig
from app.agents.core.subagents.spawn_agent import _build_spawn_graph
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.tools.core import retrieval as retrieval_module
from app.agents.tools.core.registry import ToolRegistry
from app.agents.tools.core.retrieval import (
    _render_discovery_response,
    _split_subagent_entry,
    get_retrieve_tools_function,
)
from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_child_tool_runtime_config,
    build_create_agent_tool_kwargs,
    build_executor_child_tool_runtime_config,
    build_provider_parent_tool_runtime_config,
)
from app.constants.general import FINISH_TASK_NAME, SPAWN_AGENT_NAME
from app.override.langgraph_bigtool.create_agent import (
    AgentConfig,
    ToolRetrievalConfig,
    create_agent,
)
from tests.helpers import BindableToolsFakeModel, PassthroughFakeLLM


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


class _FakeLLM(PassthroughFakeLLM):
    """Simple fake LLM for create_agent flow tests."""

    def __init__(self) -> None:
        self.bind_calls: list[list[str]] = []
        self._invoke_count = 0

    def bind_tools(self, tools: Any, **_kwargs: Any) -> "_FakeLLM":
        # Overridden only to record what was bound; the assertions read this.
        names = [getattr(t, "name", str(t)) for t in tools]
        self.bind_calls.append(names)
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

    def get_tool_meta(self, tool_name: str):
        """Read by the JSON-bucketed discovery response for a tool's description.

        None is a real registry answer (an unindexed name), and the entry
        builder has to stay correct for it, so returning it here keeps the fake
        honest rather than inventing metadata the tests never assert on.
        """
        return


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
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=object)),
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            # A real chat LLM always carries a context-window profile
            # (init_*_llm pin it); fractional-token middleware requires it.
            llm=BindableToolsFakeModel(responses=[], profile={"max_input_tokens": 1_000_000}),
            config=SubAgentToolConfig(
                tool_space="provider_space",
                use_direct_tools=use_direct_tools,
                disable_retrieve_tools=disable_retrieve_tools,
                auto_bind_tools=auto_bind_tools,
            ),
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
    tools_config = kwargs["tools_config"]
    assert tools_config.initial_tool_ids == parent_dynamic.initial_tool_names
    assert tools_config.retrieve_tools_coroutine is not None


def test_build_create_agent_tool_kwargs_hands_retrieval_scoping_through_verbatim():
    """tool_space, the subagent-discovery toggle and the bindable set reach
    get_retrieve_tools_function exactly as given — nulling or dropping any of
    them silently widens what a spawned subagent can discover."""
    sentinel = AsyncMock()
    config = ToolRuntimeConfig(
        initial_tool_names=["read"],
        enable_retrieve_tools=True,
        include_subagents_in_retrieve=True,
    )
    with patch(
        "app.agents.tools.core.tool_runtime_config.get_retrieve_tools_function",
        return_value=sentinel,
    ) as mock_get:
        kwargs = build_create_agent_tool_kwargs(
            config,
            tool_space="provider_space",
            bindable_tool_names={"vfs_read"},
        )

    mock_get.assert_called_once_with(
        tool_space="provider_space",
        include_subagents=True,
        bindable_tool_names={"vfs_read"},
    )
    assert kwargs["tools_config"].retrieve_tools_coroutine is sentinel
    assert kwargs["tools_config"].initial_tool_ids == ["read"]
    assert kwargs["tools_config"].disable_retrieve_tools is False


async def _spawn_graph_agent_kwargs(
    *,
    registry: dict[str, BaseTool],
    excluded: set[str],
    runtime: ToolRuntimeConfig,
    llm: Any = None,
) -> dict[str, Any]:
    """The kwargs ``_build_spawn_graph`` hands to ``create_agent`` for this config.

    Store, checkpointer and agent builder are stubbed because they are the
    boundaries; the scoping under test is the real production code between them.
    """
    llm = llm or _FakeLLM()
    captured: dict[str, Any] = {}

    def _fake_create_agent(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(compile=lambda **_kwargs: MagicMock())

    with (
        patch("app.agents.core.subagents.spawn_agent.get_tools_store", new=AsyncMock()),
        patch(
            "app.agents.core.subagents.spawn_agent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=MagicMock)),
        ),
        patch("app.agents.core.subagents.spawn_agent.create_agent", new=_fake_create_agent),
    ):
        await _build_spawn_graph(
            llm=llm,
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
    assert captured["tools_config"].retrieve_tools_coroutine is not None


@pytest.mark.asyncio
async def test_spawn_graph_disables_retrieve_when_the_parent_did():
    captured = await _spawn_graph_agent_kwargs(
        registry={"vfs_read": vfs_read},
        excluded={"spawn_subagent"},
        runtime=ToolRuntimeConfig(initial_tool_names=["vfs_read"], enable_retrieve_tools=False),
    )

    assert captured["tools_config"].disable_retrieve_tools is True
    assert captured["tools_config"].retrieve_tools_coroutine is None


@pytest.mark.asyncio
async def test_spawn_graph_wires_identity_middleware_and_hooks_into_create_agent():
    """The spawn's identity and guardrails ride on these exact kwargs: the agent
    name keys threads/logs, the middleware list is what gives a spawn the HIL
    gate, and the pre-model chain is the executor's minus the todo hook.
    create_agent selects behavior purely by these kwarg names, so a renamed key
    or dropped value silently falls back to its own default."""
    llm = _FakeLLM()
    captured = await _spawn_graph_agent_kwargs(
        registry={"vfs_read": vfs_read},
        excluded=set(),
        runtime=ToolRuntimeConfig(initial_tool_names=["vfs_read"], enable_retrieve_tools=False),
        llm=llm,
    )

    assert captured["llm"] is llm
    assert set(captured) == {"llm", "tool_registry", "agent_config", "hooks_config", "tools_config"}
    assert captured["agent_config"].agent_name == SPAWN_AGENT_NAME
    # middleware_factory=list → the factory call must appear verbatim.
    assert captured["agent_config"].middleware == []
    assert list(captured["hooks_config"].pre_model_hooks) == list(worker_pre_model_hooks())


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
        result = await captured["tools_config"].retrieve_tools_coroutine(
            store=MagicMock(),
            config={"configurable": {"user_id": "u1"}},
            exact_tool_names=["subagent:gmail", "handoff", "normal_tool"],
        )

    assert "subagent:gmail" not in result["tools_to_bind"]
    assert "handoff" not in result["tools_to_bind"]
    assert "normal_tool" in result["tools_to_bind"]
    # Refusing is only half of it: the response has to tell the subagent to STOP
    # asking and hand the work back, or it retries the same bind until it runs
    # out of steps. This sentence is the entire instruction.
    assert (
        "main executor, not this subagent. Do not retry binding them; finish "
        "your task here and let the executor handle them."
    ) in " ".join(
        result["response"] if isinstance(result["response"], list) else [result["response"]]
    )


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
        llm=fake_llm,
        tool_registry={"normal_tool": normal_tool},
        tools_config=ToolRetrievalConfig(
            retrieve_tools_function=_dummy_retrieve_tools,
            retrieve_tools_coroutine=_dummy_retrieve_tools_async,
        ),
        agent_config=AgentConfig(middleware=[]),
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
    registry.setup()
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
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=object)),
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            # A real chat LLM always carries a context-window profile
            # (init_*_llm pin it); fractional-token middleware requires it.
            llm=BindableToolsFakeModel(responses=[], profile={"max_input_tokens": 1_000_000}),
            config=SubAgentToolConfig(
                tool_space="provider_space",
                use_direct_tools=True,
                disable_retrieve_tools=True,
            ),
        )

    assert captured_kwargs["tools_config"].disable_retrieve_tools is True
    assert captured_kwargs["tools_config"].retrieve_tools_coroutine is None
    assert "read" in captured_kwargs["tools_config"].initial_tool_ids
    assert "normal_tool" in captured_kwargs["tools_config"].initial_tool_ids
    # A subagent runs no end-graph hook, and the kwarg has to say so under
    # exactly this name — anything else and create_agent silently falls back to
    # its own default. The memory hook is the one that matters: a subagent sees
    # the thread comms already ingested, so hooking it here re-extracts one
    # conversation once per subagent per turn and bills for every pass.
    assert captured_kwargs["hooks_config"].end_graph_hooks == []


@pytest.mark.asyncio
async def test_base_subagent_hands_create_agent_the_exact_agent_config():
    # create_agent receives **common_kwargs, so a renamed key silently drops the
    # wiring instead of erroring: assert every key by name, plus the identity
    # values inside AgentConfig — the subagent's own name and the middleware
    # list built for it.
    captured_kwargs, mw = await _run_provider_subagent_factory(
        use_direct_tools=False,
        disable_retrieve_tools=False,
    )

    assert set(captured_kwargs) == {
        "llm",
        "tool_registry",
        "agent_config",
        "hooks_config",
        "tools_config",
    }
    assert captured_kwargs["tool_registry"]["normal_tool"] is normal_tool
    agent_config = captured_kwargs["agent_config"]
    assert isinstance(agent_config, AgentConfig)
    assert agent_config.agent_name == "provider_agent"
    assert agent_config.middleware == [mw]


@pytest.mark.asyncio
async def test_provider_subagent_defaults_tool_space_to_general():
    """``tool_space`` defaults to "general" — the literal string, not "GENERAL"
    or any other spelling — and that default must actually reach the
    middleware that scopes what the subagent (and anything it spawns) may call."""
    provider_tool = normal_tool
    full_tools = {"normal_tool": normal_tool, "vfs_read": vfs_read, "search_memory": normal_tool}
    dummy_registry = _DummyRegistry([provider_tool], full_tools)

    def _fake_create_agent(**kwargs: Any):
        return _DummyBuilder(kwargs)

    captured_middleware_kwargs: dict[str, Any] = {}

    def _fake_create_subagent_middleware(**kwargs: Any):
        captured_middleware_kwargs.update(kwargs)
        return []

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
            new=_fake_create_subagent_middleware,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=object)),
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            llm=BindableToolsFakeModel(responses=[], profile={"max_input_tokens": 1_000_000}),
            # tool_space intentionally omitted — must default to "general".
        )

    assert captured_middleware_kwargs["subagent_tool_space"] == "general"


@pytest.mark.asyncio
async def test_base_subagent_dynamic_mode_wires_retrieve_and_auto_bind():
    captured_kwargs, mw = await _run_provider_subagent_factory(
        use_direct_tools=False,
        disable_retrieve_tools=False,
        auto_bind_tools=["normal_tool", "missing_tool"],
    )

    assert captured_kwargs["tools_config"].retrieve_tools_coroutine is not None
    assert captured_kwargs["tools_config"].disable_retrieve_tools is False
    assert "search_memory" in captured_kwargs["tools_config"].initial_tool_ids
    assert "read" in captured_kwargs["tools_config"].initial_tool_ids
    assert "normal_tool" in captured_kwargs["tools_config"].initial_tool_ids
    assert "missing_tool" not in captured_kwargs["tools_config"].initial_tool_ids
    # spawned child for dynamic mode should keep minimal initial tools
    assert mw._tool_runtime_config.initial_tool_names == ["read", "bash", "finish_task"]
    assert mw._tool_runtime_config.enable_retrieve_tools is True


@pytest.mark.asyncio
async def test_base_subagent_direct_mode_propagates_child_direct_runtime():
    captured_kwargs, mw = await _run_provider_subagent_factory(
        use_direct_tools=True,
        disable_retrieve_tools=True,
    )

    assert captured_kwargs["tools_config"].disable_retrieve_tools is True
    assert captured_kwargs["tools_config"].retrieve_tools_coroutine is None
    assert "read" in captured_kwargs["tools_config"].initial_tool_ids
    assert "normal_tool" in captured_kwargs["tools_config"].initial_tool_ids
    assert mw._tool_runtime_config.enable_retrieve_tools is False
    assert "normal_tool" in mw._tool_runtime_config.initial_tool_names
    assert "read" in mw._tool_runtime_config.initial_tool_names


# ---------------------------------------------------------------------------
# create_provider_subagent wiring pins — todo tools, hooks, middleware toggle,
# and the declaration labels on the missing-tools warning
# ---------------------------------------------------------------------------


async def _run_factory_recording_wiring(*, config: SubAgentToolConfig) -> dict[str, Any]:
    """Run the factory with every collaborator recorded.

    Returns a dict with: create_agent kwargs (``agent_kwargs``), the middleware
    factory kwargs (``middleware_kwargs``), the todo-tool/hook factory calls
    (``todo_calls``), and the worker_pre_model_hooks stand-in (``worker``).
    """
    full_tools = {"normal_tool": normal_tool, "vfs_read": vfs_read}
    dummy_registry = _DummyRegistry([normal_tool], full_tools)

    captured: dict[str, Any] = {
        "agent_kwargs": {},
        "middleware_kwargs": {},
        "todo_calls": {},
    }

    def _fake_create_agent(**kwargs: Any):
        captured["agent_kwargs"].update(kwargs)
        return _DummyBuilder(kwargs)

    def _fake_middleware(**kwargs: Any):
        captured["middleware_kwargs"].update(kwargs)
        return []

    hook_sentinel = object()
    pre_model_hooks_sentinel = object()

    def _fake_todo_tools(**kwargs: Any) -> list[BaseTool]:
        captured["todo_calls"]["tools"] = kwargs
        return []

    def _fake_todo_hook(**kwargs: Any) -> object:
        captured["todo_calls"]["hook"] = kwargs
        return hook_sentinel

    worker = MagicMock(return_value=pre_model_hooks_sentinel)

    with (
        patch(
            "app.agents.core.subagents.base_subagent.get_tools_store",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_tool_registry",
            new=AsyncMock(return_value=dummy_registry),
        ),
        patch("app.agents.core.subagents.base_subagent.create_agent", new=_fake_create_agent),
        patch(
            "app.agents.core.subagents.base_subagent.create_subagent_middleware",
            new=_fake_middleware,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
            new=AsyncMock(return_value=SimpleNamespace(get_checkpointer=object)),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.create_todo_tools",
            new=_fake_todo_tools,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.create_todo_pre_model_hook",
            new=_fake_todo_hook,
        ),
        patch(
            "app.agents.core.subagents.base_subagent.worker_pre_model_hooks",
            new=worker,
        ),
    ):
        await SubAgentFactory.create_provider_subagent(
            provider="provider",
            name="provider_agent",
            llm=BindableToolsFakeModel(responses=[], profile={"max_input_tokens": 1_000_000}),
            config=config,
        )

    captured["worker"] = worker
    return captured


@pytest.mark.asyncio
async def test_a_non_authoring_subagent_keeps_spawn_enabled():
    """The middleware toggle is the NEGATION of authoring_only: an ordinary
    provider subagent must be able to spawn sub-subagents; inverting the flag
    silently strips that ability from every integration agent."""
    captured = await _run_factory_recording_wiring(config=SubAgentToolConfig())

    assert captured["middleware_kwargs"]["enable_subagent"] is True


@pytest.mark.asyncio
async def test_todo_factories_receive_the_provider_identity_exactly():
    """source/source_label key the todo tools' progress events to the right
    integration; a dropped kwarg falls back to a generic label."""
    captured = await _run_factory_recording_wiring(config=SubAgentToolConfig(source_label="Gmail"))

    assert captured["todo_calls"]["tools"] == {"source": "provider", "source_label": "Gmail"}
    assert captured["todo_calls"]["hook"] == {"source": "provider"}


@pytest.mark.asyncio
async def test_the_todo_hook_reaches_hooks_config_through_worker_pre_model_hooks():
    """The chain is exact end to end: the created hook feeds
    worker_pre_model_hooks, whose result lands in hooks_config.pre_model_hooks.
    A None in either position silently un-hooks the subagent's pre-model pass."""
    captured = await _run_factory_recording_wiring(config=SubAgentToolConfig())

    worker = captured["worker"]
    assert worker.call_count == 1
    assert len(worker.call_args.args) == 1
    # The argument is exactly what create_todo_pre_model_hook returned.
    assert worker.call_args.args[0] is not None
    assert captured["agent_kwargs"]["hooks_config"].pre_model_hooks is worker.return_value


@pytest.mark.asyncio
async def test_missing_declared_tools_warn_under_their_exact_declaration_kind():
    """The warning's ``declaration`` label is how an operator tells an
    auto_bind gap from an extra_initial gap; a mangled kind reads as the other
    config surface's fault."""
    with patch("app.agents.core.subagents.base_subagent.log") as log:
        await _run_factory_recording_wiring(
            config=SubAgentToolConfig(
                tool_space="provider_space",
                auto_bind_tools=["normal_tool", "missing_auto"],
                extra_initial_tools=["missing_extra"],
            )
        )

    warnings = log.warning.call_args_list
    auto_bind = [c for c in warnings if c.kwargs.get("declaration") == "auto_bind"]
    extra_initial = [c for c in warnings if c.kwargs.get("declaration") == "extra_initial"]
    assert auto_bind and auto_bind[0].kwargs["missing_tools"] == ["missing_auto"]
    assert auto_bind[0].kwargs["provider"] == "provider"
    assert extra_initial and extra_initial[0].kwargs["missing_tools"] == ["missing_extra"]


# ---------------------------------------------------------------------------
# _render_discovery_response — what a discovery search tells the model it may do
# ---------------------------------------------------------------------------


class _DiscoveryRegistry:
    """Registry double shaped like the two methods the renderer actually calls."""

    def __init__(self, categories: dict[str, str], destructive: set[str] | None = None):
        self._categories = categories
        self._destructive = destructive or set()

    def get_category_of_tool(self, tool_name: str) -> str:
        return self._categories.get(tool_name, "unknown")

    def get_tool_meta(self, tool_name: str):
        if tool_name not in self._categories:
            return None
        return SimpleNamespace(destructive=tool_name in self._destructive)


@dataclass
class _DiscoveryOptions:
    """Knobs for rendering a discovery response in tests."""

    categories: dict[str, str] | None = None
    destructive: set[str] | None = None
    connected: dict[str, str | None] | None = None
    internal: set[str] | None = None
    total_candidates: int = 5
    limit: int = 10


def _render_text(
    final_tools: list[str],
    *,
    options: _DiscoveryOptions | None = None,
    query: str | None = None,
) -> str:
    """The raw string the model receives, formatting and all."""
    opts = options or _DiscoveryOptions()
    return _render_discovery_response(
        final_tools,
        _DiscoveryRegistry(opts.categories or {}, opts.destructive),
        opts.connected or {},
        opts.internal or set(),
        query,
        opts.total_candidates,
        opts.limit,
    )


def _render(
    final_tools: list[str],
    *,
    options: _DiscoveryOptions | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    return json.loads(_render_text(final_tools, options=options, query=query))


class TestSplitSubagentEntry:
    def test_an_id_with_a_display_name(self) -> None:
        assert _split_subagent_entry("subagent:gmail (Gmail)") == ("gmail", "Gmail")

    def test_a_bare_id_has_no_name(self) -> None:
        assert _split_subagent_entry("subagent:gmail") == ("gmail", None)

    def test_a_name_containing_a_bracket_keeps_its_tail(self) -> None:
        assert _split_subagent_entry("subagent:x (A (B))") == ("x", "A (B)")

    def test_an_unclosed_bracket_is_not_treated_as_a_name(self) -> None:
        """Both halves of the guard are load-bearing: an opening bracket alone
        would otherwise split a malformed id and hand back a truncated name."""
        assert _split_subagent_entry("subagent:foo (bar") == ("foo (bar", None)


class TestDiscoveryResponseIsIndentedJson:
    """Every other test here parses the payload, which throws the formatting away.

    The model receives the STRING, so the indentation is part of what discovery
    delivers, and nothing was asserting it.
    """

    def test_the_model_receives_indented_json_not_one_compact_line(self) -> None:
        text = _render_text(
            ["send_email"], options=_DiscoveryOptions(categories={"send_email": "gmail"})
        )
        assert len(text.splitlines()) > 1

    def test_nesting_is_indented_by_two_spaces(self) -> None:
        text = _render_text(
            ["send_email"], options=_DiscoveryOptions(categories={"send_email": "gmail"})
        )
        indents = {len(ln) - len(ln.lstrip(" ")) for ln in text.splitlines() if ln.startswith(" ")}
        assert indents, "nothing is indented — the payload came out compact"
        assert min(indents) == 2


class TestDiscoveryAvailabilityBuckets:
    """Availability is the axis that decides what the model may do next: bind it,
    hand off to it, or ask the user to connect it first."""

    def test_a_builtin_subagent_is_never_reported_as_needing_a_connection(self) -> None:
        """The bug this argument exists for — without internal_subagents every
        built-in was listed as needing a connection it has none of."""
        payload = _render(
            ["subagent:gaia_knowledge_guide (Guide)"],
            options=_DiscoveryOptions(internal={"gaia_knowledge_guide"}),
        )

        assert payload["subagents_builtin"] == [{"id": "gaia_knowledge_guide", "name": "Guide"}]
        assert payload["subagents_needing_connection"] == []
        assert payload["subagents_connected"] == []

    def test_a_connected_integration_subagent_is_ready_to_hand_off_to(self) -> None:
        payload = _render(
            ["subagent:gmail (Gmail)"],
            options=_DiscoveryOptions(connected={"gmail": "me@example.com"}),
        )

        assert payload["subagents_connected"] == [{"id": "gmail", "name": "Gmail"}]
        assert payload["subagents_needing_connection"] == []

    def test_an_unconnected_integration_subagent_needs_connecting(self) -> None:
        payload = _render(["subagent:slack (Slack)"])

        assert payload["subagents_needing_connection"] == [{"id": "slack", "name": "Slack"}]
        assert payload["subagents_connected"] == []
        assert payload["subagents_builtin"] == []

    def test_a_builtin_wins_over_a_connection_record(self) -> None:
        """Built-in and connected are not mutually exclusive in the inputs; a
        built-in must not also be advertised as an integration."""
        payload = _render(
            ["subagent:gmail (Gmail)"],
            options=_DiscoveryOptions(connected={"gmail": "me@example.com"}, internal={"gmail"}),
        )

        assert payload["subagents_builtin"] == [{"id": "gmail", "name": "Gmail"}]
        assert payload["subagents_connected"] == []

    def test_a_nameless_subagent_carries_only_its_id(self) -> None:
        payload = _render(["subagent:gmail"], options=_DiscoveryOptions(internal={"gmail"}))

        assert payload["subagents_builtin"] == [{"id": "gmail"}]

    def test_tools_and_subagents_go_to_different_buckets(self) -> None:
        payload = _render(
            ["web_search_tool", "subagent:gmail (Gmail)"],
            options=_DiscoveryOptions(
                categories={"web_search_tool": "search"},
                internal={"gmail"},
            ),
        )

        assert [t["name"] for t in payload["tools_to_bind"]] == ["web_search_tool"]
        assert payload["subagents_builtin"] == [{"id": "gmail", "name": "Gmail"}]


class TestDiscoveryToolEntries:
    def test_a_connected_integration_tool_is_sourced_by_its_display_name(self) -> None:
        payload = _render(
            ["GMAIL_SEND"],
            options=_DiscoveryOptions(
                categories={"GMAIL_SEND": "gmail"},
                connected={"gmail": "me@example.com"},
            ),
        )

        assert payload["tools_to_bind"] == [{"name": "GMAIL_SEND", "source": "me@example.com"}]

    def test_a_connected_integration_with_no_display_name_falls_back_to_the_category(self) -> None:
        payload = _render(
            ["GMAIL_SEND"],
            options=_DiscoveryOptions(
                categories={"GMAIL_SEND": "gmail"}, connected={"gmail": None}
            ),
        )

        assert payload["tools_to_bind"] == [{"name": "GMAIL_SEND", "source": "gmail"}]

    def test_a_first_party_tool_is_sourced_to_gaia(self) -> None:
        payload = _render(
            ["web_search_tool"], options=_DiscoveryOptions(categories={"web_search_tool": "search"})
        )

        assert payload["tools_to_bind"] == [{"name": "web_search_tool", "source": "gaia"}]

    def test_a_destructive_tool_is_flagged_for_approval(self) -> None:
        payload = _render(
            ["GMAIL_SEND"],
            options=_DiscoveryOptions(
                categories={"GMAIL_SEND": "gmail"}, destructive={"GMAIL_SEND"}
            ),
        )

        assert payload["tools_to_bind"][0]["needs_approval"] is True

    def test_a_safe_tool_carries_no_approval_flag(self) -> None:
        """The key's presence is the signal, so an explicit False would read as
        'approval considered and required' to a client checking for the key."""
        payload = _render(
            ["web_search_tool"], options=_DiscoveryOptions(categories={"web_search_tool": "search"})
        )

        assert "needs_approval" not in payload["tools_to_bind"][0]


class TestDiscoveryZeroMatchSignal:
    """Built-in subagents are injected unconditionally, so a search that matched
    nothing still returns entries. Reporting that as a find is what sent the
    model re-querying the same dead index."""

    def test_a_zero_match_search_says_so_even_though_builtins_are_listed(self) -> None:
        payload = _render(
            ["subagent:gaia_knowledge_guide (Guide)"],
            options=_DiscoveryOptions(
                internal={"gaia_knowledge_guide"},
                total_candidates=0,
            ),
        )

        assert payload["search_matched_nothing"] is True
        assert payload["subagents_builtin"] != []
        assert "matched NOTHING" in payload["next"]
        assert "Never repeat the same query" in payload["next"]

    def test_a_search_with_hits_carries_no_zero_match_flag(self) -> None:
        payload = _render(
            ["web_search_tool"],
            options=_DiscoveryOptions(categories={"web_search_tool": "search"}, total_candidates=1),
        )

        assert "search_matched_nothing" not in payload
        assert "handoff(subagent_id=" in payload["next"]

    def test_the_two_next_instructions_are_different(self) -> None:
        empty = _render([], options=_DiscoveryOptions(total_candidates=0))["next"]
        hits = _render(["x"], options=_DiscoveryOptions(total_candidates=1))["next"]

        assert empty != hits

    def test_the_zero_match_instruction_survives_verbatim(self) -> None:
        """This block is the contract with the model, not commentary: each
        clause closes one of the loops a dead search sent it into (re-query the
        same words, guess a tool name, keep going instead of telling the user)."""
        assert _render([], options=_DiscoveryOptions(total_candidates=0))["next"] == (
            "The search matched NOTHING; anything listed above is a built-in that is "
            "always offered, not a hit. Retry ONCE with a broader query naming the "
            "action ('send email', not a product name). If you already know the exact "
            "tool name, skip search and call retrieve_tools(exact_tool_names=[...]). "
            "Otherwise tell the user the capability is unavailable. Never repeat the "
            "same query."
        )

    def test_the_found_instruction_survives_verbatim(self) -> None:
        """Two of these clauses exist because the model got them wrong: binding
        a subagent, and offering an unconnected integration as if it worked."""
        assert _render(["x"], options=_DiscoveryOptions(total_candidates=1))["next"] == (
            "Bind with retrieve_tools(exact_tool_names=[...]) then call the tool. "
            'Subagents are NOT bindable: use handoff(subagent_id="<id>", task="..."). '
            "Anything under subagents_needing_connection is unusable until the user "
            "connects it, so ask them first."
        )


class TestDiscoveryTruncationAndQuery:
    def test_more_candidates_than_the_limit_reports_the_shortfall(self) -> None:
        payload = _render(
            ["a", "b"],
            options=_DiscoveryOptions(categories={"a": "s", "b": "s"}, total_candidates=9, limit=2),
        )

        assert payload["truncated"] == {"shown": 2, "total": 9}

    def test_a_full_result_set_is_not_marked_truncated(self) -> None:
        payload = _render(
            ["a"], options=_DiscoveryOptions(categories={"a": "s"}, total_candidates=2, limit=2)
        )

        assert "truncated" not in payload

    def test_the_query_is_echoed_back_when_there_was_one(self) -> None:
        assert (
            _render(["a"], options=_DiscoveryOptions(categories={"a": "s"}), query="send email")[
                "query"
            ]
            == "send email"
        )

    def test_an_exact_name_lookup_echoes_no_query(self) -> None:
        assert "query" not in _render(["a"], options=_DiscoveryOptions(categories={"a": "s"}))


# ---------------------------------------------------------------------------
# The bind response — what exact_tool_names tells the model it just got
# ---------------------------------------------------------------------------


async def _bind(names: list[str], registry_tools: list[str]):
    retrieve_tools = get_retrieve_tools_function(tool_space="general", include_subagents=False)
    with patch(
        "app.agents.tools.core.retrieval.get_tool_registry",
        new=AsyncMock(return_value=_RetrieveRegistry(registry_tools)),
    ):
        return await retrieve_tools(
            store=MagicMock(),
            config={"configurable": {"user_id": "u1"}},
            exact_tool_names=names,
        )


@pytest.mark.asyncio
async def test_binding_announces_what_the_model_may_now_call():
    result = await _bind(["normal_tool"], ["normal_tool"])

    assert result["response_text"] == "Bound 1 tools, call them directly:\n  - normal_tool"


@pytest.mark.asyncio
async def test_a_hyphenated_alias_binds_its_canonical_tool():
    """Models routinely emit a hyphenated spelling. Dropping it would report the
    tool as missing while it sits in the registry under an underscore."""
    result = await _bind(["normal-tool"], ["normal_tool"])

    assert result["tools_to_bind"] == ["normal_tool"]


@pytest.mark.asyncio
async def test_a_resolved_alias_is_named_back_so_the_model_stops_using_it():
    """Binding silently would leave the model calling the alias every turn and
    relying on the same rescue each time."""
    result = await _bind(["normal-tool"], ["normal_tool"])

    assert (
        "Resolved to their canonical names, use these from now on: normal-tool -> normal_tool"
        in result["response_text"]
    )


@pytest.mark.asyncio
async def test_a_name_that_needed_no_resolving_is_not_reported_as_renamed():
    result = await _bind(["normal_tool"], ["normal_tool"])

    assert "Resolved to their canonical names" not in result["response_text"]


@pytest.mark.asyncio
async def test_an_unknown_name_is_named_back_with_a_do_not_retry():
    """An empty answer reads the same as 'the search found nothing', so the
    model retypes the name until it runs out of steps."""
    result = await _bind(["no_such_tool_xyz"], ["normal_tool"])

    assert result["tools_to_bind"] == []
    assert result["response_text"] == (
        "Not found, nothing bound: no_such_tool_xyz. Do not retry these names; "
        "run retrieve_tools(query=...) to find what actually exists."
    )


@pytest.mark.asyncio
async def test_one_bad_name_does_not_poison_the_batch():
    result = await _bind(["normal_tool", "no_such_tool_xyz"], ["normal_tool"])

    assert result["tools_to_bind"] == ["normal_tool"]
    assert "Bound 1 tools" in result["response_text"]
    assert "Not found, nothing bound: no_such_tool_xyz" in result["response_text"]


@pytest.mark.asyncio
async def test_several_unknown_names_are_listed_separately():
    result = await _bind(["nope_one", "nope_two"], ["normal_tool"])

    assert "Not found, nothing bound: nope_one, nope_two." in result["response_text"]


@pytest.mark.asyncio
async def test_several_resolved_aliases_are_listed_separately():
    result = await _bind(["normal-tool", "vfs-read"], ["normal_tool", "vfs_read"])

    assert (
        "use these from now on: normal-tool -> normal_tool, vfs-read -> vfs_read"
        in result["response_text"]
    )


@pytest.mark.asyncio
async def test_a_query_that_matches_nothing_says_so_and_echoes_the_query():
    """The zero-hit path is the one that degrades silently: built-ins are always
    injected, so without this signal an empty index looks like a result set."""
    retrieve_tools = get_retrieve_tools_function(tool_space="general", include_subagents=False)
    with (
        patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new=AsyncMock(return_value=_RetrieveRegistry(["normal_tool"])),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
            new=AsyncMock(return_value={"general"}),
        ),
    ):
        result = await retrieve_tools(
            store=_FakeStore({}),
            config={"configurable": {"user_id": "u1"}},
            query="send a carrier pigeon",
            exact_tool_names=[],
        )

    payload = json.loads(result["response_text"])
    assert payload["search_matched_nothing"] is True
    assert payload["query"] == "send a carrier pigeon"


def _zero_hit_warnings(log) -> list[dict[str, Any]]:
    """Kwargs of the 'namespace has no indexed docs' warnings only.

    Retrieval warns about several unrelated things in one call (an MCP lookup
    that failed, for one), so a bare log.warning.called cannot tell them apart.
    """
    return [
        call.kwargs
        for call in log.warning.call_args_list
        if "tool_space" in call.kwargs and "user_id" in call.kwargs
    ]


async def _query(store, *, tool_space: str = "general"):
    """Drive a query-mode retrieval and capture what it logged."""
    retrieve_tools = get_retrieve_tools_function(tool_space=tool_space, include_subagents=False)
    with (
        patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new=AsyncMock(return_value=_RetrieveRegistry(["normal_tool"])),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
            new=AsyncMock(return_value={"general"}),
        ),
        patch.object(retrieval_module, "log") as log,
    ):
        result = await retrieve_tools(
            store=store,
            config={"configurable": {"user_id": "u1"}},
            query="anything",
            exact_tool_names=[],
        )
    return result, log


@pytest.mark.asyncio
async def test_a_dead_index_warns_operators_even_in_the_general_namespace():
    """This dropped its `and tool_space != "general"` guard. General is the
    namespace every executor searches, so an index that wrote no docs there was
    the outage the warning exists for — and the one case it stayed silent for."""
    _result, log = await _query(_FakeStore({}))

    dead_index = _zero_hit_warnings(log)
    assert dead_index, "a namespace with zero indexed docs reported nothing"
    assert dead_index[0]["tool_space"] == "general"
    assert dead_index[0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_a_namespace_with_hits_is_not_reported_as_dead():
    """Control: warning unconditionally would satisfy the test above."""
    store = _FakeStore(
        {
            ("general",): [
                SimpleNamespace(key="normal_tool", score=0.9, namespace=("general",), value={})
            ]
        }
    )

    _result, log = await _query(store)

    assert _zero_hit_warnings(log) == []
