"""SubagentMiddleware - Provides the spawn_subagent tool, the executor's delegation tool.

A spawned subagent is a real compiled graph (see
app/agents/core/subagents/spawn_agent.py) on a disposable thread of its own,
which gives it the full middleware stack — including the HIL gate. It runs on the
shared delegation runner (core/subagents/delegation.py): in the background by
default, blocking on request.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any, Protocol
from weakref import WeakKeyDictionary

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    OmitFromInput,
)
from langchain.tools import InjectedToolCallId
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphBubbleUp
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command

from app.agents.context.tiers import AgentTier
from app.agents.core.subagents.delegation import Delegation, SubagentDisplay, delegate
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    ThreadSeed,
    build_initial_messages,
    subagent_row_id,
)
from app.agents.prompts.spawn_subagent_prompts import (
    SPAWN_SUBAGENT_DESCRIPTION,
    SPAWN_SUBAGENT_SYSTEM_PROMPT,
)
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.general import SPAWN_AGENT_NAME, SPAWN_THREAD_PREFIX
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.constants.llm import SUBAGENT_RECURSION_LIMIT
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import AgentIdentity, AgentThread, build_agent_config
from app.models.agent_models import (
    AgentConfigurable,
    AnyAgentMiddleware,
    SubagentKind,
    agent_configurable,
)
from shared.py.wide_events import log


def _tool_result(content: str, tool_call_id: str, status: str = "success") -> Command[str]:
    return Command(
        update={
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id, status=status)]
        }
    )


class SpawnGraphProvider(Protocol):
    """Compiles the graph a spawn runs on.

    A Protocol rather than Callable[..., ...] because this is an injection
    seam: every call site passes these six by keyword, and an erased signature
    turns a renamed or dropped argument into a runtime TypeError instead of a
    type error. Satisfied by core.subagents.spawn_agent.get_spawn_graph,
    which is injected rather than imported (see :meth:set_spawn_graph_provider).
    """

    async def __call__(
        self,
        llm: LanguageModelLike,
        registry: Mapping[str, BaseTool],
        excluded_tool_names: set[str],
        tool_space: str,
        runtime: ToolRuntimeConfig,
        middleware_factory: Callable[[], Sequence[AnyAgentMiddleware]],
    ) -> CompiledStateGraph: ...


@dataclass(frozen=True)
class SubagentMiddlewareConfig:
    """Construction settings for :class:SubagentMiddleware.

    One object rather than ten constructor arguments: these are all build-time
    wiring for the same middleware, and every field keeps the default the
    constructor used to carry.
    """

    llm: LanguageModelLike | None = None
    available_tools: list[BaseTool] | None = None
    tool_registry: Mapping[str, BaseTool] | None = None
    max_turns: int = SUBAGENT_RECURSION_LIMIT
    system_prompt: str = SPAWN_SUBAGENT_SYSTEM_PROMPT
    excluded_tool_names: set[str] | None = None
    tool_space: str = "general"
    store: BaseStore | None = None
    tool_runtime_config: ToolRuntimeConfig | None = None
    spawn_middleware_factory: Callable[[str], Sequence[AnyAgentMiddleware]] | None = None
    #: Carry the parent's bound tools into each spawn. On under integration
    #: activation, where the parent binds an integration in its own turn and
    #: delegates the work here; off otherwise, keeping the lean spawn start.
    inherit_parent_tools: bool = False


class SubagentState(AgentState[Any]):
    """State schema for subagent middleware."""

    active_subagents: Annotated[list[str], OmitFromInput]


class SubagentMiddleware(AgentMiddleware[SubagentState, Any]):
    """Middleware that exposes a spawn_subagent tool for focused subtask execution."""

    state_schema = SubagentState

    def __init__(self, config: SubagentMiddlewareConfig | None = None) -> None:
        super().__init__()
        settings = config or SubagentMiddlewareConfig()
        self._llm = settings.llm
        self._spawn_middleware_factory = settings.spawn_middleware_factory
        # Injected by whoever builds the parent graph (see set_spawn_graph_provider):
        # the builder imports create_agent, which imports this package, so this
        # module cannot reach the graph builder itself.
        self._spawn_graph_provider: SpawnGraphProvider | None = None
        self._available_tools = settings.available_tools or []
        self._tool_registry = settings.tool_registry
        self._max_turns = settings.max_turns
        self._system_prompt = settings.system_prompt
        self._excluded_tools = settings.excluded_tool_names or set()
        self._excluded_tools.add("spawn_subagent")
        self._inherit_parent_tools = settings.inherit_parent_tools
        self._tool_space = settings.tool_space
        self._store: BaseStore | None = settings.store
        self._tool_runtime_config = settings.tool_runtime_config or ToolRuntimeConfig(
            initial_tool_names=["read", "bash"],
            enable_retrieve_tools=True,
            include_subagents_in_retrieve=False,
        )

        self.tools = [self._create_spawn_subagent_tool()]

    def _create_spawn_subagent_tool(self) -> BaseTool:
        middleware = self

        @tool(description=SPAWN_SUBAGENT_DESCRIPTION)
        async def spawn_subagent(
            task: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            selected_tool_ids: Annotated[list[str], InjectedState("selected_tool_ids")],
            config: RunnableConfig,
            context: str = "",
            background: bool = True,
        ) -> Command[str]:
            """Spawn a subagent to handle a subtask with focused execution."""
            if middleware._llm is None:
                return _tool_result("Error: Subagent LLM not configured", tool_call_id, "error")

            configurable: AgentConfigurable = agent_configurable(config)
            try:
                delegation = await middleware.build_delegation(
                    task=task,
                    context=context,
                    parent_configurable=configurable,
                    tool_call_id=tool_call_id,
                    inherited_tool_names=selected_tool_ids,
                )
                result = await delegate(
                    delegation,
                    background=background,
                    # Only a resume replay can find this spawn's thread already run.
                    probe_parked=bool(configurable.get(HIL_RESUME_CONFIG_KEY)),
                )
                return _tool_result(result, tool_call_id)
            except GraphBubbleUp:
                # The HIL gate's interrupt bubbling up from a blocking spawn. Control
                # flow, not a failure — converting it to a tool error would drop the
                # user's approval request on the floor.
                raise
            except Exception as e:
                log.error(f"{LogTag.AGENT} Subagent execution failed", error_type=type(e).__name__)
                return _tool_result(f"Subagent error: {e!s}", tool_call_id, "error")

        return spawn_subagent

    async def build_delegation(
        self,
        *,
        task: str,
        context: str,
        parent_configurable: AgentConfigurable,
        tool_call_id: str,
        inherited_tool_names: list[str] | None,
    ) -> Delegation:
        """Build the delegation one spawn_subagent call runs; a parked spawn is rebuilt the same way."""
        ctx = await self._build_context(
            task, context, parent_configurable, tool_call_id, inherited_tool_names
        )
        # The task names the row, so the UI shows what is running rather than
        # three identical "Subagent" rows.
        name = (task[:40].rstrip() + "…") if len(task) > 40 else (task or "Subagent")
        return Delegation(
            ctx=ctx,
            kind=SubagentKind.SPAWN,
            # Stable across replays, so an approval pause reuses its UI row.
            subagent_id=subagent_row_id(tool_call_id),
            tool_call_id=tool_call_id,
            task=task,
            context=context,
            inherited_tool_names=tuple(inherited_tool_names or ()),
            parent_configurable=parent_configurable,
            display=SubagentDisplay(
                name=name,
                agent_type="spawned",
                tool_category="spawn_subagent",
                parent_subagent_id=parent_configurable.get("subagent_id"),
            ),
        )

    async def _build_context(
        self,
        task: str,
        context: str,
        configurable: AgentConfigurable,
        tool_call_id: str,
        inherited_tool_names: list[str] | None,
    ) -> SubagentExecutionContext:
        inherited = (
            [name for name in (inherited_tool_names or []) if name not in self._excluded_tools]
            if self._inherit_parent_tools
            else []
        )
        if self._llm is None:
            raise ValueError("LLM not configured for subagent execution")
        if self._spawn_middleware_factory is None or self._spawn_graph_provider is None:
            raise ValueError("Spawn graph not configured for subagent execution")

        user_id = configurable.get("user_id")
        conversation_id = str(configurable.get("conversation_id") or "")

        middleware_factory = self._spawn_middleware_factory
        tool_space = self._tool_space
        # Seed initial_tool_names, not just state: the spawn graph is cached with
        # its bindable set frozen at compile time, so this changes the cache key
        # (see spawn_agent._cache_key) for a fresh graph holding the tools.
        runtime = self._tool_runtime_config
        if inherited:
            runtime = replace(
                runtime,
                initial_tool_names=[
                    *runtime.initial_tool_names,
                    *(n for n in inherited if n not in runtime.initial_tool_names),
                ],
            )
        graph = await self._spawn_graph_provider(
            llm=self._llm,
            registry=self._tool_registry or {t.name: t for t in self._available_tools},
            excluded_tool_names=self._excluded_tools,
            tool_space=tool_space,
            runtime=runtime,
            middleware_factory=lambda: middleware_factory(tool_space),
        )

        # One thread per spawn call, never reused: ``tool_call_id`` is unique
        # and stable across replays. ``spawn_`` prefix lets
        # checkpoint_retention_tasks.py reclaim these once stale.
        thread_id = f"{SPAWN_THREAD_PREFIX}{conversation_id}_{tool_call_id}"

        spawn_config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=conversation_id,
                user={
                    "user_id": user_id,
                    "email": configurable.get("email"),
                    "name": configurable.get("user_name"),
                },
                agent_name=SPAWN_AGENT_NAME,
            ),
            thread=AgentThread(
                thread_id=thread_id,
                base_configurable=configurable,
                subagent_id=SPAWN_AGENT_NAME,
                recursion_limit=self._max_turns,
            ),
        )
        new_configurable = agent_configurable(spawn_config)

        user_content = f"Context:\n{context}\n\nTask:\n{task}" if context else f"Task:\n{task}"
        messages = await build_initial_messages(
            system_message=SystemMessage(content=self._system_prompt),
            agent_name=SPAWN_AGENT_NAME,
            task=user_content,
            seed=ThreadSeed(
                tier=AgentTier.SPAWN,
                configurable=new_configurable,
                user_id=user_id,
                retrieval_query=task,
            ),
        )

        return SubagentExecutionContext(
            subagent_graph=graph,
            agent_name=SPAWN_AGENT_NAME,
            config=spawn_config,
            configurable=new_configurable,
            integration_id="spawn",
            initial_state={
                "messages": messages,
                "todos": [],
                # Empty unless inheriting: spawn binds its minimal set, retrieves
                # the rest on demand; activated parent tools are seeded here and
                # in initial_tool_names above, which makes them bindable.
                "selected_tool_ids": inherited,
            },
            user_id=user_id,
            stream_id=configurable.get("stream_id"),
        )

    def set_spawn_graph_provider(self, provider: SpawnGraphProvider) -> None:
        """Wire the builder that compiles the graph a spawn runs on.

        Injected rather than imported: the graph builder pulls in create_agent,
        which imports this package, so importing it from here would close a cycle.
        """
        self._spawn_graph_provider = provider

    def set_llm(self, llm: LanguageModelLike) -> None:
        self._llm = llm

    def set_store(self, store: BaseStore) -> None:
        self._store = store

    def set_tools(
        self,
        tools: list[BaseTool] | None = None,
        registry: Mapping[str, BaseTool] | None = None,
        excluded_tool_names: set[str] | None = None,
        tool_space: str | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
    ) -> None:
        if tools is not None:
            self._available_tools = tools
        if registry is not None:
            self._tool_registry = registry
        if excluded_tool_names is not None:
            self._excluded_tools.update(excluded_tool_names)
            self._excluded_tools.add("spawn_subagent")
        if tool_space is not None:
            self._tool_space = tool_space
        if tool_runtime_config is not None:
            self._tool_runtime_config = tool_runtime_config


#: The spawner each compiled executor graph was built with. A parked background
#: spawn is resumed by whichever process receives the user's decision, possibly
#: after a restart, so it is rebuilt from its executor graph's own spawner.
_SPAWNERS: WeakKeyDictionary[CompiledStateGraph, SubagentMiddleware] = WeakKeyDictionary()


def bind_spawner(graph: CompiledStateGraph, spawner: SubagentMiddleware) -> None:
    """Record the spawner a compiled executor graph carries."""
    _SPAWNERS[graph] = spawner


def spawner_of(graph: CompiledStateGraph) -> SubagentMiddleware:
    """Return the spawner a compiled executor graph was built with."""
    return _SPAWNERS[graph]
