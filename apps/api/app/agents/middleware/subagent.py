"""SubagentMiddleware - Provides spawn_subagent tool for lightweight parallel task execution.

A spawned subagent is a real compiled graph (see
``app/agents/core/subagents/spawn_agent.py``), run imperatively on a disposable
thread of its own. That is what gives it the full middleware stack — including
the HIL gate, so a gated tool inside a spawn pauses for the user's approval and
bubbles that pause up to the parent, exactly as ``handoff`` does.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import time
from typing import Annotated, Any, Protocol

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
from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command

from app.agents.context.tiers import AgentTier
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
    ThreadSeed,
    build_initial_messages,
    execute_subagent_stream,
    recover_from_checkpoint,
    resume_for_gate,
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
from app.models.agent_models import AnyAgentMiddleware, agent_configurable
from app.utils.agent_utils import (
    StreamWriterCallable,
    SubagentStartDetails,
    format_subagent_end_event,
    format_subagent_start_event,
)
from shared.py.wide_events import log


class SpawnGraphProvider(Protocol):
    """Compiles the graph a spawn runs on.

    A Protocol rather than ``Callable[..., ...]`` because this is an injection
    seam: every call site passes these six by keyword, and an erased signature
    turns a renamed or dropped argument into a runtime ``TypeError`` instead of a
    type error. Satisfied by ``core.subagents.spawn_agent.get_spawn_graph``,
    which is injected rather than imported (see :meth:`set_spawn_graph_provider`).
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
    """Construction settings for :class:`SubagentMiddleware`.

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
        ) -> Command[Any]:
            """Spawn a subagent to handle a subtask with focused execution."""
            if middleware._llm is None:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="Error: Subagent LLM not configured",
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        ]
                    }
                )

            try:
                result = await middleware._run_spawn(
                    task=task,
                    context=context,
                    config=config,
                    tool_call_id=tool_call_id,
                    inherited_tool_names=selected_tool_ids,
                )
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=result,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )
            except GraphBubbleUp:
                # The HIL gate's interrupt bubbling up from the spawned graph.
                # Control flow, not a failure — converting it to a tool error
                # would drop the user's approval request on the floor.
                raise
            except Exception as e:
                log.error(f"{LogTag.AGENT} Subagent execution failed", error_type=type(e).__name__)
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=f"Subagent error: {e!s}",
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        ]
                    }
                )

        return spawn_subagent

    async def _run_spawn(
        self,
        task: str,
        context: str,
        config: RunnableConfig,
        tool_call_id: str,
        inherited_tool_names: list[str] | None,
    ) -> str:
        """Run one spawned subagent to completion, pausing the parent for approvals."""
        configurable = agent_configurable(config)
        # A fresh spawn has a brand-new tool_call_id, so nothing can already exist on
        # its thread — only a resume replay can, which is why the checkpoint probe is
        # gated on it and effectively every spawn skips that Postgres read.
        replaying = bool(configurable.get(HIL_RESUME_CONFIG_KEY))

        ctx = await self._build_context(task, context, config, tool_call_id, inherited_tool_names)

        # Stable across replays so an approval pause reuses the same UI row instead of
        # orphaning the paused one and opening a duplicate on resume.
        sa_id = subagent_row_id(tool_call_id)
        # Surface the task as the subagent's name so the UI shows what's running,
        # not three identical "Subagent" rows.
        spawn_name = (task[:40].rstrip() + "…") if len(task) > 40 else (task or "Subagent")
        writer = get_stream_writer()
        writer(
            {
                "subagent_start": format_subagent_start_event(
                    subagent_name=spawn_name,
                    agent_type="spawned",
                    subagent_id=sa_id,
                    details=SubagentStartDetails(
                        tool_category="spawn_subagent",
                        parent_subagent_id=configurable.get("subagent_id"),
                    ),
                )
            }
        )
        start_time = time.monotonic()

        paused = False
        try:
            outcome = await self._drive(ctx, writer, sa_id, probe_parked=replaying)
        except GraphBubbleUp:
            paused = True
            raise
        finally:
            # A pause is not an ending — the row stays live until the user decides
            # and the resumed run closes it. Every other exit terminates it, so a
            # failed spawn never leaves the UI spinning.
            if not paused:
                writer(
                    {
                        "subagent_end": format_subagent_end_event(
                            subagent_id=sa_id,
                            duration_ms=int((time.monotonic() - start_time) * 1000),
                        )
                    }
                )

        # The thread deliberately outlives the run: a later sibling in this same AI
        # message can still pause, which replays the tool node from the top, and the
        # checkpoint is what tells the replay this spawn already finished instead of
        # redoing its whole task. The nightly sweep reclaims it once it is stale.
        return outcome.text

    async def _drive(
        self,
        ctx: SubagentExecutionContext,
        writer: StreamWriterCallable,
        sa_id: str,
        probe_parked: bool,
    ) -> SubagentOutcome:
        """Run the graph, bubbling every HIL pause up to the parent.

        The spawn is invoked imperatively, so its GraphInterrupt never reaches the
        parent's runtime — each pause is re-raised here with ``interrupt()``. A LOOP,
        not an if: one task can gate several destructive calls in sequence, and each
        must suspend the parent again. ``resume_for_gate`` raises on the first pass and
        returns that gate's own decision on the replay (matching the recovered park, not
        an earlier gate's already-applied decision).
        """
        recovered = await recover_from_checkpoint(ctx) if probe_parked else None
        outcome = recovered or await execute_subagent_stream(
            ctx=ctx, stream_writer=writer, subagent_id=sa_id
        )
        while outcome.paused:
            decision = resume_for_gate(outcome.interrupt)
            outcome = await execute_subagent_stream(
                ctx=ctx,
                stream_writer=writer,
                subagent_id=sa_id,
                resume=Command(resume=decision),
            )
        return outcome

    async def _build_context(
        self,
        task: str,
        context: str,
        config: RunnableConfig,
        tool_call_id: str,
        inherited_tool_names: list[str] | None,
    ) -> SubagentExecutionContext:
        if self._llm is None:
            raise ValueError("LLM not configured for subagent execution")
        if self._spawn_middleware_factory is None or self._spawn_graph_provider is None:
            raise ValueError("Spawn graph not configured for subagent execution")

        configurable = agent_configurable(config)
        user_id = configurable.get("user_id")
        conversation_id = str(configurable.get("conversation_id") or "")

        middleware_factory = self._spawn_middleware_factory
        tool_space = self._tool_space
        graph = await self._spawn_graph_provider(
            llm=self._llm,
            registry=self._tool_registry or {t.name: t for t in self._available_tools},
            excluded_tool_names=self._excluded_tools,
            tool_space=tool_space,
            runtime=self._tool_runtime_config,
            middleware_factory=lambda: middleware_factory(tool_space),
        )

        # One thread per spawn call, never reused. ``tool_call_id`` is unique per call
        # AND stable across node replays (it lives in the checkpointed AI message),
        # which is what lets a resumed spawn find its own run — parked or finished —
        # instead of starting a second one. The ``spawn_`` prefix is what
        # workers/tasks/checkpoint_retention_tasks.py selects on to reclaim these once
        # stale; the conversation uuid keeps them collectable with the conversation.
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
                # Inherit whatever the parent has bound this turn. acall_model
                # unions initial_tool_ids with state["selected_tool_ids"], so
                # seeding the channel here is what carries the inheritance over.
                "selected_tool_ids": [
                    name
                    for name in (inherited_tool_names or [])
                    if name not in self._excluded_tools
                ],
            },
            user_id=user_id,
            stream_id=configurable.get("stream_id"),
        )

    def set_spawn_graph_provider(self, provider: SpawnGraphProvider) -> None:
        """Wire the builder that compiles the graph a spawn runs on.

        Injected rather than imported: the graph builder pulls in ``create_agent``,
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
