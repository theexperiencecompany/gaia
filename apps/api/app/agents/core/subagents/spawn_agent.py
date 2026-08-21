"""The graph a ``spawn_subagent`` call runs.

The generic counterpart to ``SubAgentFactory.create_provider_subagent``: no
provider, no integration, whatever tool space its parent hands down. It is a real
compiled graph rather than a hand-rolled loop so a spawned subagent gets the same
middleware every other agent has — above all the HIL gate, which is what lets a
gated tool inside a spawn pause for the user's approval instead of being refused.

Cached per (tool_space, tool-runtime signature): the tool registry is global, so
the graph is user-agnostic — the same assumption ``build_executor_graph`` makes.

The middleware stack arrives as a factory rather than being built here: the
module that composes middleware stacks is also the one that constructs
``SubagentMiddleware``, so importing it from this side would close a cycle.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence

from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.agents.core.nodes.pre_model_hooks import worker_pre_model_hooks
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_create_agent_tool_kwargs,
)
from app.agents.tools.finish_task_tool import finish_task
from app.constants.general import FINISH_TASK_NAME, SPAWN_AGENT_NAME
from app.constants.log_tags import LogTag
from app.models.agent_models import AnyAgentMiddleware
from app.override.langgraph_bigtool.create_agent import create_agent
from shared.py.wide_events import log

#: What ``_cache_key`` produces: (model identity, tool space, initial tool names,
#: retrieve-tools enabled, subagents-in-retrieve enabled).
SpawnGraphCacheKey = tuple[str, str, tuple[str, ...], bool, bool]

_graph_cache: dict[SpawnGraphCacheKey, CompiledStateGraph] = {}
_cache_lock = asyncio.Lock()


def _cache_key(
    llm: LanguageModelLike, tool_space: str, runtime: ToolRuntimeConfig
) -> SpawnGraphCacheKey:
    """What makes two spawn graphs interchangeable.

    The model belongs in the key: it is bound into the compiled graph, so two
    parents that differ only by model must not share one. Keyed by model identity
    rather than object identity because per-run model selection still happens
    through ``llm.with_config(configurable=...)`` inside the model node — two
    handles on the same model are genuinely interchangeable.
    """
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or type(llm).__name__
    return (
        str(model),
        tool_space,
        tuple(runtime.initial_tool_names),
        runtime.enable_retrieve_tools,
        runtime.include_subagents_in_retrieve,
    )


async def get_spawn_graph(
    llm: LanguageModelLike,
    registry: Mapping[str, BaseTool],
    excluded_tool_names: set[str],
    tool_space: str,
    runtime: ToolRuntimeConfig,
    middleware_factory: Callable[[], Sequence[AnyAgentMiddleware]],
) -> CompiledStateGraph:
    """The compiled graph for this parent's spawn configuration, built once."""
    key = _cache_key(llm, tool_space, runtime)
    cached = _graph_cache.get(key)
    if cached is not None:
        return cached

    async with _cache_lock:
        cached = _graph_cache.get(key)
        if cached is not None:
            return cached
        graph = await _build_spawn_graph(
            llm, registry, excluded_tool_names, tool_space, runtime, middleware_factory
        )
        _graph_cache[key] = graph
        return graph


async def _build_spawn_graph(
    llm: LanguageModelLike,
    registry: Mapping[str, BaseTool],
    excluded_tool_names: set[str],
    tool_space: str,
    runtime: ToolRuntimeConfig,
    middleware_factory: Callable[[], Sequence[AnyAgentMiddleware]],
) -> CompiledStateGraph:
    store = await get_tools_store()

    # ``excluded_tool_names`` always contains spawn_subagent (SubagentMiddleware
    # adds it), so a spawned subagent cannot spawn again — the middleware stack
    # below is built with enable_subagent=False for the same reason.
    scoped_tools: dict[str, BaseTool] = {
        name: tool for name, tool in registry.items() if name not in excluded_tool_names
    }
    scoped_tools[FINISH_TASK_NAME] = finish_task

    kwargs = {
        "llm": llm,
        "tool_registry": scoped_tools,
        "agent_name": SPAWN_AGENT_NAME,
        "middleware": middleware_factory(),
        # No todo hook and no memory end-hook: a spawn is a one-shot scratch
        # task, not an agent that owns a task list or learns per-integration
        # facts about the user.
        "pre_model_hooks": worker_pre_model_hooks(),
    }
    kwargs.update(
        build_create_agent_tool_kwargs(
            runtime,
            tool_space=tool_space,
            bindable_tool_names=set(scoped_tools.keys()),
        )
    )

    builder = create_agent(**kwargs)  # type: ignore[arg-type]  # kwargs assembled as a runtime dict; **-unpacking defeats mypy's kwarg checking

    try:
        checkpointer_manager = await get_checkpointer_manager()
        checkpointer: BaseCheckpointSaver = checkpointer_manager.get_checkpointer()
    except Exception as e:
        # A spawn's thread must be durable while it is parked on an approval —
        # the decision can arrive hours later in another process. In-memory means
        # such a pause cannot be resumed, so this is a real degradation.
        log.warning(
            f"{LogTag.AGENT} PostgreSQL checkpointer unavailable for spawned subagents; "
            "using InMemorySaver — HIL pauses inside a spawn will not survive a restart",
            error_type=type(e).__name__,
            error=str(e),
        )
        checkpointer = InMemorySaver()

    graph = builder.compile(store=store, name=SPAWN_AGENT_NAME, checkpointer=checkpointer)
    log.info(
        f"{LogTag.AGENT} Built spawned-subagent graph",
        tool_space=tool_space,
        tools=len(scoped_tools),
        retrieve_tools=runtime.enable_retrieve_tools,
    )
    return graph
