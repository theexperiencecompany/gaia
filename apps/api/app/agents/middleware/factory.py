"""Factory functions for the standard agent middleware stack (executor, comms, subagents).

Centralized here so build_graph.py and base_subagent.py share one
configuration. Summarization and compaction receive the graph's own
chat_llm and invoke it inside the graph, where the ambient request config
routes them to the same model the conversation is using.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import cast

from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.empty_completion import EmptyCompletionRetryMiddleware
from app.agents.middleware.hil_approval import HILApprovalMiddleware
from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.media import MediaDescriptionMiddleware
from app.agents.middleware.subagent import SubagentMiddleware, SubagentMiddlewareConfig
from app.agents.middleware.summarization import (
    WorkspaceArchivingSummarizationMiddleware,
)
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    DEFAULT_MAX_TOKENS,
    EXECUTOR_RECURSION_LIMIT,
)
from app.constants.log_tags import LogTag
from app.constants.summarization import (
    COMMS_SUMMARIZATION_TRIGGER_TOKENS,
    COMPACTION_THRESHOLD,
    MAX_OUTPUT_CHARS,
    SUMMARIZATION_KEEP_TOKENS,
    SUMMARIZATION_TRIGGER_FRACTION,
)
from app.models.agent_models import AgentMiddlewareStack
from shared.py.wide_events import log

# Coding tools' outputs are already capped by the bash output limiter, read
# tool pagination, and query_json/grep, so compaction should leave them alone.
CODING_TOOL_NAMES = {"bash", "read", "write", "edit", "query_json", "grep"}
SPAWN_SUBAGENT_TOOL = {"spawn_subagent"}

# Tools that already perform their own context-safe offload (small digest +
# clean file). Generic compaction must leave their output alone.
SELF_OFFLOADING_TOOL_NAMES = {"GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"}


@dataclass(frozen=True)
class AccountingOptions:
    """LLMAccountingMiddleware knobs; enabled=False leaves it out."""

    enabled: bool = True
    recursion_limit: int = AGENT_RECURSION_LIMIT


@dataclass(frozen=True)
class SubagentStackOptions:
    """SubagentMiddleware wiring; enabled=False leaves it out."""

    enabled: bool = False
    llm: LanguageModelLike | None = None
    tools: list[BaseTool] | None = None
    registry: Mapping[str, BaseTool] | None = None
    excluded_tools: set[str] | None = None
    tool_space: str = "general"
    tool_runtime_config: ToolRuntimeConfig | None = None
    #: Carry the parent's bound tools into each spawn (integration activation).
    inherit_parent_tools: bool = False


@dataclass(frozen=True)
class ContextOptions:
    """Summarization and compaction knobs.

    summarize / compact include the respective middleware; summarization
    is also skipped, with a warning, when the stack has no chat_llm.
    """

    summarize: bool = True
    compact: bool = True
    summarization_trigger: ContextSize = ("fraction", SUMMARIZATION_TRIGGER_FRACTION)
    summarization_keep: ContextSize = ("tokens", SUMMARIZATION_KEEP_TOKENS)
    archive: bool = True
    summarization_excluded_tools: set[str] | None = None
    compaction_threshold: float = COMPACTION_THRESHOLD
    max_output_chars: int = MAX_OUTPUT_CHARS
    compaction_excluded_tools: set[str] | None = None


@dataclass(frozen=True)
class LoopGuardOptions:
    """LoopGuardMiddleware knobs; enabled=False leaves it out.

    Whether it may block a call is decided per call from the run's
    execution_mode (background runs only), never here: the executor graph is
    a per-process singleton shared by interactive and background runs.
    """

    enabled: bool = True


def create_middleware_stack(
    *,
    agent_name: str = "agent",
    chat_llm: LanguageModelLike | None = None,
    accounting: AccountingOptions = AccountingOptions(),
    subagent: SubagentStackOptions = SubagentStackOptions(),
    context: ContextOptions = ContextOptions(),
    loop_guard: LoopGuardOptions = LoopGuardOptions(),
) -> AgentMiddlewareStack:
    """Create the standard middleware stack for agents.

    agent_name carries accounting and log attribution; chat_llm is the
    graph's own model for summarization and the compaction digest. When
    None, summarization is skipped. Returns middleware in execution order.
    """
    middleware: AgentMiddlewareStack = []

    # Emits `llm_call` wide events + recursion high-water-mark signals.
    # Inserted FIRST so it observes every model call in and out.
    if accounting.enabled:
        middleware.append(
            LLMAccountingMiddleware(
                agent_name=agent_name, recursion_limit=accounting.recursion_limit
            )
        )
        log.debug(f"{LogTag.AGENT} LLMAccountingMiddleware enabled", agent_name=agent_name)
        log.set(
            middleware_stack={
                "agent_name": agent_name,
                "accounting_enabled": True,
            }
        )

    # HIL approval gate — outermost tool-call wrapper so no other middleware
    # runs a side effect before the user decides. A no-op unless HIL is on.
    middleware.append(HILApprovalMiddleware())
    log.debug(f"{LogTag.AGENT} HILApprovalMiddleware enabled", agent_name=agent_name)

    # SubagentMiddleware - spawn_subagent tool for parallel/focused work
    if subagent.enabled:
        spawner = SubagentMiddleware(
            SubagentMiddlewareConfig(
                llm=subagent.llm,
                available_tools=subagent.tools,
                tool_registry=subagent.registry,
                excluded_tool_names=subagent.excluded_tools,
                tool_space=subagent.tool_space,
                tool_runtime_config=subagent.tool_runtime_config,
                inherit_parent_tools=subagent.inherit_parent_tools,
                spawn_middleware_factory=lambda space: create_subagent_middleware(
                    # No enabled=True here: a spawned child must not spawn again,
                    # and SubagentStackOptions defaults to enabled=False.
                    subagent=SubagentStackOptions(tool_space=space)
                ),
            )
        )
        middleware.append(spawner)
        log.debug(f"{LogTag.AGENT} SubagentMiddleware enabled with spawn_subagent tool")

    # Summarization middleware (skipped without a chat LLM)
    if context.summarize:
        if chat_llm is None:
            log.warning(f"{LogTag.AGENT} No chat_llm provided; summarization middleware skipped.")
        else:
            summarization = WorkspaceArchivingSummarizationMiddleware(
                # The configurable-alternatives wrapper is a Runnable, not a
                # BaseChatModel; LangChain only ever calls .ainvoke/.profile on it.
                model=cast("BaseChatModel", chat_llm),
                trigger=context.summarization_trigger,
                keep=context.summarization_keep,
                enable_archive=context.archive,
                excluded_tools=context.summarization_excluded_tools,
            )
            middleware.append(summarization)
            log.debug(
                f"{LogTag.AGENT} Summarization middleware enabled",
                summarization_trigger=context.summarization_trigger,
                summarization_keep=context.summarization_keep,
            )

    # Compaction middleware (always available, but respects enable flag). It also
    # binds query_json/grep when a tool output is offloaded.
    if context.compact:
        compaction = WorkspaceCompactionMiddleware(
            compaction_threshold=context.compaction_threshold,
            max_output_chars=context.max_output_chars,
            context_window=DEFAULT_MAX_TOKENS,
            excluded_tools=context.compaction_excluded_tools,
            summary_llm=chat_llm,  # same model as the conversation; None keeps deterministic tiers
        )
        middleware.append(compaction)
        log.debug(
            f"{LogTag.AGENT} Compaction middleware enabled",
            compaction_threshold=context.compaction_threshold,
            llm_summary=chat_llm is not None,
        )

    # Inner to compaction, so the description is attached before compaction
    # inspects the result. No enable flag: it no-ops without media.
    middleware.append(MediaDescriptionMiddleware())
    log.debug(f"{LogTag.AGENT} Media description middleware enabled", agent_name=agent_name)

    # Added LAST so it sits innermost, observing the raw tool result before
    # compaction/summarization transform it. Blocks only in background runs.
    if loop_guard.enabled:
        middleware.append(LoopGuardMiddleware())
        log.debug(f"{LogTag.AGENT} Loop guard middleware enabled", agent_name=agent_name)

    return middleware


def create_executor_middleware(
    *,
    chat_llm: LanguageModelLike | None = None,
    subagent: SubagentStackOptions | None = None,
) -> AgentMiddlewareStack:
    """Create middleware stack for the executor agent: SubagentMiddleware plus summarization/compaction.

    The executor's SubagentMiddleware needs LLM and tool_registry set after
    creation via set_llm()/set_tools() since they aren't available at factory time.
    """
    return create_middleware_stack(
        agent_name="executor_agent",
        chat_llm=chat_llm,
        accounting=AccountingOptions(recursion_limit=EXECUTOR_RECURSION_LIMIT),
        # The executor is the tier that spawns, so enablement is not the caller's to choose.
        subagent=replace(subagent or SubagentStackOptions(), enabled=True),
        context=ContextOptions(
            compaction_excluded_tools=CODING_TOOL_NAMES
            | SPAWN_SUBAGENT_TOOL
            | SELF_OFFLOADING_TOOL_NAMES,
        ),
    )


def create_comms_middleware(chat_llm: LanguageModelLike | None = None) -> AgentMiddlewareStack:
    """Create the middleware stack for the comms agent.

    Comms delegates all real work to the executor, so it only gets summarization.
    File-offload compaction is intentionally off: comms has no read/bash/subagent
    tool, so a compacted output would leave it holding an unreadable file path.
    """
    stack = create_middleware_stack(
        agent_name="comms_agent",
        chat_llm=chat_llm,
        subagent=SubagentStackOptions(enabled=False),
        context=ContextOptions(
            compact=False,
            summarization_trigger=("tokens", COMMS_SUMMARIZATION_TRIGGER_TOKENS),
        ),
    )
    # Innermost of all: the retry has to happen before anything reads the
    # completion, so what the turn delivers is the model's real reply rather
    # than the silence that preceded it.
    stack.append(EmptyCompletionRetryMiddleware())
    log.debug(f"{LogTag.AGENT} EmptyCompletionRetryMiddleware enabled", agent_name="comms_agent")
    return stack


def create_subagent_middleware(
    *,
    agent_name: str = "provider_subagent",
    subagent: SubagentStackOptions = SubagentStackOptions(),
) -> AgentMiddlewareStack:
    """Create the middleware stack for worker subagents.

    Summarization stays on: compaction alone cannot bound accumulated
    history, and the result is read from the finish_task call, never from
    replayed history. Subagents can never spawn; nesting stops one tier
    below the executor.
    """
    # Only the executor spawns; whatever a caller passed, a subagent's stack
    # never carries the spawn middleware (see the docstring). Annotated so the
    # dataclasses.replace return type is explicit at the call site below.
    child_subagent: SubagentStackOptions = replace(subagent, enabled=False)
    return create_middleware_stack(
        agent_name=agent_name,
        chat_llm=subagent.llm,
        subagent=child_subagent,
        context=ContextOptions(
            # Summarization and compaction stay on (the ContextOptions defaults):
            # without summarization a subagent run grows unbounded, averaging 91k
            # input tokens per call in production against 43k for comms/executor.
            compaction_excluded_tools=CODING_TOOL_NAMES
            | SPAWN_SUBAGENT_TOOL
            | SELF_OFFLOADING_TOOL_NAMES,
        ),
    )
