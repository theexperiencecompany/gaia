"""Factory functions for the standard agent middleware stack (executor, comms,
subagents). Centralized here so build_graph.py and base_subagent.py share one
configuration.

Summarization and compaction receive the graph's own ``chat_llm`` and invoke it
inside the graph, where the ambient request config routes them to the same
model the conversation is using."""

from collections.abc import Mapping
from typing import cast

from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.hil_approval import HILApprovalMiddleware
from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.media import MediaDescriptionMiddleware
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.middleware.subagent_join import SubagentJoinMiddleware
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
    COMPACTION_THRESHOLD,
    MAX_OUTPUT_CHARS,
    SUMMARIZATION_KEEP_TOKENS,
    SUMMARIZATION_TRIGGER_FRACTION,
)
from app.models.agent_models import AgentMiddlewareStack
from shared.py.wide_events import log

# Coding tools operate on the persistent E2B workspace; their outputs are
# already capped by the bash output limiter, the read tool's pagination, and the
# query_json/grep output cap, so the compaction middleware should leave them alone.
CODING_TOOL_NAMES = {"bash", "read", "write", "edit", "query_json", "grep"}
SPAWN_SUBAGENT_TOOL = {"spawn_subagent"}

# Tools that already perform their own context-safe offload (return a small
# digest + write a clean file the agent mines). The generic compaction
# middleware must leave their output alone — re-handling it would clobber the
# tool's own file format with the generic wrapper.
SELF_OFFLOADING_TOOL_NAMES = {"GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"}

# Loop-guard hard-stop is OFF by default: it must never silently abandon a tool
# call in an interactive run where the user is watching and can intervene. It is
# only safe to enable for unattended (silent / workflow) runs. Because the
# executor graph — and therefore its middleware — is a single per-process
# instance shared by BOTH interactive and workflow runs, we cannot select
# hard-stop per run at graph-build time; flipping this constant would enable it
# for every run on the graph. See create_middleware_stack for the wiring note.
LOOP_GUARD_HARD_STOP = False


def create_middleware_stack(
    *,
    agent_name: str = "agent",
    chat_llm: LanguageModelLike | None = None,
    recursion_limit: int = AGENT_RECURSION_LIMIT,
    enable_accounting: bool = True,
    enable_summarization: bool = True,
    enable_compaction: bool = True,
    enable_subagent: bool = False,
    subagent_llm: LanguageModelLike | None = None,
    subagent_tools: list[BaseTool] | None = None,
    subagent_registry: Mapping[str, BaseTool] | None = None,
    subagent_excluded_tools: set[str] | None = None,
    subagent_tool_space: str = "general",
    subagent_tool_runtime_config: ToolRuntimeConfig | None = None,
    summarization_trigger: ContextSize = ("fraction", SUMMARIZATION_TRIGGER_FRACTION),
    summarization_keep: ContextSize = ("tokens", SUMMARIZATION_KEEP_TOKENS),
    compaction_threshold: float = COMPACTION_THRESHOLD,
    max_output_chars: int = MAX_OUTPUT_CHARS,
    enable_archive: bool = True,
    compaction_excluded_tools: set[str] | None = None,
    summarization_excluded_tools: set[str] | None = None,
    enable_loop_guard: bool = True,
    loop_guard_hard_stop: bool = LOOP_GUARD_HARD_STOP,
    enable_subagent_join: bool = False,
) -> AgentMiddlewareStack:
    """
    Create the standard middleware stack for agents.

    Uses LangChain's AgentMiddleware system:
    - SubagentMiddleware: Spawn subagents for parallel/focused work
    - WorkspaceArchivingSummarizationMiddleware: Archives history to the user's
      persistent workspace and summarizes at threshold
    - WorkspaceCompactionMiddleware: Persists large tool outputs to the
      persistent workspace and replaces them with a /workspace/... reference

    Args:
        agent_name: Name used for accounting/log attribution
        chat_llm: The graph's own configurable LLM. Summarization and the
            compaction digest invoke it inside the graph, so ambient request
            config routes them to the same model the conversation uses. When
            None, summarization is skipped and compaction keeps its
            deterministic tiers.
        enable_summarization: Whether to include summarization middleware
        enable_compaction: Whether to include compaction middleware
        enable_subagent: Whether to include subagent spawning middleware
        subagent_llm: LLM for subagent execution (required if enable_subagent=True)
        subagent_tools: Tools available to subagents
        subagent_registry: Alternative tool registry for subagents
        subagent_excluded_tools: Tool names to exclude from subagent access
        subagent_tool_space: Tool space for spawned subagent retrieve_tools search
        summarization_trigger: When to trigger summarization (fraction/tokens/messages)
        summarization_keep: How much to keep after summarization (tokens recommended)
        compaction_threshold: Context usage ratio to trigger compaction
        max_output_chars: Max chars for single tool output before compaction
        enable_archive: Whether to archive history to the workspace before
            summarization fires
        compaction_excluded_tools: Tools that should never be compacted
        summarization_excluded_tools: Tools that should never trigger summarization

    Returns:
        List of AgentMiddleware instances in execution order
    """
    middleware: AgentMiddlewareStack = []

    # LLM accounting middleware — emits `llm_call` wide events + recursion
    # high-water-mark signals. Inserted FIRST so it observes every model call
    # on the way in (before_model) and on the way out (after_model).
    # ``caching_debug`` flips on a second diagnostic instance that runs LAST,
    # so we can compare state.messages before vs. after other middleware.
    if enable_accounting:
        middleware.append(
            LLMAccountingMiddleware(agent_name=agent_name, recursion_limit=recursion_limit)
        )
        log.debug(f"{LogTag.AGENT} LLMAccountingMiddleware enabled", agent_name=agent_name)
        log.set(
            middleware_stack={
                "agent_name": agent_name,
                "accounting_enabled": True,
            }
        )

    # HIL approval gate — outermost tool-call wrapper (only accounting, a
    # before/after_model hook, precedes it) so no other middleware runs a side
    # effect before the user decides. A no-op unless the user's HIL preference is
    # on, so it needs no build-time flag.
    middleware.append(HILApprovalMiddleware())
    log.debug(f"{LogTag.AGENT} HILApprovalMiddleware enabled", agent_name=agent_name)

    # SubagentMiddleware - spawn_subagent tool for parallel/focused work
    if enable_subagent:
        subagent = SubagentMiddleware(
            llm=subagent_llm,
            available_tools=subagent_tools,
            tool_registry=subagent_registry,
            excluded_tool_names=subagent_excluded_tools,
            tool_space=subagent_tool_space,
            tool_runtime_config=subagent_tool_runtime_config,
            spawn_middleware_factory=lambda space: create_subagent_middleware(
                enable_subagent=False, subagent_tool_space=space
            ),
        )
        middleware.append(subagent)
        log.debug(f"{LogTag.AGENT} SubagentMiddleware enabled with spawn_subagent tool")

    # Summarization middleware (skipped without a chat LLM)
    if enable_summarization:
        if chat_llm is None:
            log.warning(f"{LogTag.AGENT} No chat_llm provided; summarization middleware skipped.")
        else:
            summarization = WorkspaceArchivingSummarizationMiddleware(
                # The configurable-alternatives wrapper is a Runnable, not a
                # BaseChatModel; LangChain only ever calls .ainvoke/.profile on it.
                model=cast("BaseChatModel", chat_llm),
                trigger=summarization_trigger,
                keep=summarization_keep,
                enable_archive=enable_archive,
                excluded_tools=summarization_excluded_tools,
            )
            middleware.append(summarization)
            log.debug(
                f"{LogTag.AGENT} Summarization middleware enabled",
                summarization_trigger=summarization_trigger,
                summarization_keep=summarization_keep,
            )

    # Compaction middleware (always available, but respects enable flag). It also
    # binds query_json/grep when a tool output is offloaded.
    if enable_compaction:
        compaction = WorkspaceCompactionMiddleware(
            compaction_threshold=compaction_threshold,
            max_output_chars=max_output_chars,
            context_window=DEFAULT_MAX_TOKENS,
            excluded_tools=compaction_excluded_tools,
            summary_llm=chat_llm,  # same model as the conversation; None keeps deterministic tiers
        )
        middleware.append(compaction)
        log.debug(
            f"{LogTag.AGENT} Compaction middleware enabled",
            compaction_threshold=compaction_threshold,
            llm_summary=chat_llm is not None,
        )

    # Media description — a lane that can't see pixels gets prose for any tool
    # result carrying images. Inner to compaction, so the description is attached
    # before compaction inspects the result; compaction never spills media anyway.
    # No enable flag: it no-ops on every result without media, i.e. nearly all.
    middleware.append(MediaDescriptionMiddleware())
    log.debug(f"{LogTag.AGENT} Media description middleware enabled", agent_name=agent_name)

    # Loop-guard middleware — added LAST so it sits innermost and observes the
    # raw tool result before compaction/summarization transform it, counting the
    # tool's actual failures. warn-only unless hard_stop is enabled.
    if enable_loop_guard:
        middleware.append(LoopGuardMiddleware(hard_stop=loop_guard_hard_stop))
        log.debug(
            f"{LogTag.AGENT} Loop guard middleware enabled",
            agent_name=agent_name,
            hard_stop=loop_guard_hard_stop,
        )

    # Subagent-join enforcement (executor only) — after everything else so it
    # sees the response other after_model hooks may have adjusted. Rewrites a
    # turn-ending response into a wait_for_subagents call while background
    # subagents are uncollected; collection must never depend on the model
    # remembering to call the join.
    if enable_subagent_join:
        middleware.append(SubagentJoinMiddleware())
        log.debug(f"{LogTag.AGENT} SubagentJoinMiddleware enabled", agent_name=agent_name)

    return middleware


def create_executor_middleware(
    *,
    chat_llm: LanguageModelLike | None = None,
    subagent_llm: LanguageModelLike | None = None,
    subagent_tools: list[BaseTool] | None = None,
    subagent_registry: Mapping[str, BaseTool] | None = None,
    subagent_excluded_tools: set[str] | None = None,
    subagent_tool_runtime_config: ToolRuntimeConfig | None = None,
) -> AgentMiddlewareStack:
    """
    Create middleware stack for the executor agent.

    The executor agent handles complex multi-step tasks and should have:
    - SubagentMiddleware: For parallel/focused work with lightweight subagents
    - Summarization and compaction middleware

    The executor's SubagentMiddleware needs LLM and tool_registry set after
    creation via set_llm()/set_tools() since they aren't available at factory time.

    Args:
        chat_llm: The graph's chat LLM; also serves summarization + compaction
        subagent_llm: LLM for subagent execution
        subagent_tools: Tools available to subagents
        subagent_registry: Alternative tool registry for subagents
        subagent_excluded_tools: Tool names to exclude from subagent access
                                 (e.g., handoff, subagent:-prefixed tools)

    Returns:
        List of middleware for executor agent
    """
    return create_middleware_stack(
        agent_name="executor_agent",
        chat_llm=chat_llm,
        recursion_limit=EXECUTOR_RECURSION_LIMIT,
        enable_subagent=True,
        subagent_llm=subagent_llm,
        subagent_tools=subagent_tools,
        subagent_registry=subagent_registry,
        subagent_excluded_tools=subagent_excluded_tools,
        subagent_tool_runtime_config=subagent_tool_runtime_config,
        compaction_excluded_tools=CODING_TOOL_NAMES
        | SPAWN_SUBAGENT_TOOL
        | SELF_OFFLOADING_TOOL_NAMES,
        enable_subagent_join=True,
    )


def create_comms_middleware(chat_llm: LanguageModelLike | None = None) -> AgentMiddlewareStack:
    """Create the middleware stack for the comms agent.

    Comms delegates all real work to the executor, so it only gets summarization.
    File-offload compaction is intentionally off: comms has no read/bash/subagent
    tool, so a compacted output would leave it holding an unreadable file path.
    """
    return create_middleware_stack(
        agent_name="comms_agent",
        chat_llm=chat_llm,
        enable_subagent=False,
        enable_compaction=False,
    )


def create_subagent_middleware(
    *,
    agent_name: str = "provider_subagent",
    subagent_llm: LanguageModelLike | None = None,
    subagent_tools: list[BaseTool] | None = None,
    subagent_registry: Mapping[str, BaseTool] | None = None,
    subagent_excluded_tools: set[str] | None = None,
    subagent_tool_space: str = "general",
    subagent_tool_runtime_config: ToolRuntimeConfig | None = None,
    enable_subagent: bool = True,
) -> AgentMiddlewareStack:
    """
    Create middleware stack for provider subagents.

    Provider subagents handle focused integration work and should have:
    - SubagentMiddleware: For spawning focused sub-subagents
    - WorkspaceCompactionMiddleware: Persist oversized tool outputs to /workspace
    - Summarization: compaction bounds a single tool output, not the accumulated
      history. Without summarization a run grows unbounded up to
      EXECUTOR_RECURSION_LIMIT steps — in production this averaged 91k input
      tokens per call against 43k for comms/executor, peaking at a full 1M-token
      window. Trimming is safe here because the result is read from the
      finish_task call, never from replayed history.

    Spawned sub-subagents will NOT have SubagentMiddleware (enforced by
    SubagentMiddleware itself which excludes spawn_subagent from child tools).

    Args:
        agent_name: The subagent's own name, used to attribute its ``llm_call``
            events. Without it every one of the ~35 integration subagents meters
            under a single ``provider_subagent`` bucket, so per-subagent cost and
            cache behaviour cannot be told apart.
        subagent_llm: LLM for spawned sub-subagent execution
        subagent_tools: Tools available to spawned sub-subagents
        subagent_registry: Alternative tool registry for spawned sub-subagents
        subagent_excluded_tools: Tool names to exclude from sub-subagent access
        subagent_tool_space: Tool space for spawned sub-subagent retrieve_tools search
        enable_subagent: Whether to include the spawn_subagent middleware. False
            for authoring-only subagents that must not spawn or execute.

    Returns:
        List of middleware for provider subagents
    """
    return create_middleware_stack(
        agent_name=agent_name,
        chat_llm=subagent_llm,
        enable_subagent=enable_subagent,
        enable_summarization=True,
        enable_compaction=True,
        subagent_llm=subagent_llm,
        subagent_tools=subagent_tools,
        subagent_registry=subagent_registry,
        subagent_excluded_tools=subagent_excluded_tools,
        subagent_tool_space=subagent_tool_space,
        subagent_tool_runtime_config=subagent_tool_runtime_config,
        compaction_excluded_tools=CODING_TOOL_NAMES
        | SPAWN_SUBAGENT_TOOL
        | SELF_OFFLOADING_TOOL_NAMES,
    )
