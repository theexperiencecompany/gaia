"""Factory functions for the standard agent middleware stack (executor, comms,
subagents). Centralized here so build_graph.py and base_subagent.py share one
configuration.

Summarization and compaction receive the graph's own ``chat_llm`` and invoke it
inside the graph, where the ambient request config routes them to the same
model the conversation is using."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.hil_approval import HILApprovalMiddleware
from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.media import MediaDescriptionMiddleware
from app.agents.middleware.style_guard import StyleGuardMiddleware
from app.agents.middleware.subagent import SubagentMiddleware, SubagentMiddlewareConfig
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


@dataclass(frozen=True)
class AccountingOptions:
    """LLMAccountingMiddleware knobs; ``enabled=False`` leaves it out."""

    enabled: bool = True
    recursion_limit: int = AGENT_RECURSION_LIMIT


@dataclass(frozen=True)
class SubagentStackOptions:
    """SubagentMiddleware wiring; ``enabled=False`` leaves it out.

    ``join`` adds SubagentJoinMiddleware (executor only), which rewrites a
    turn-ending response into a wait_for_subagents call while background
    subagents are uncollected.
    """

    enabled: bool = False
    llm: LanguageModelLike | None = None
    tools: list[BaseTool] | None = None
    registry: Mapping[str, BaseTool] | None = None
    excluded_tools: set[str] | None = None
    tool_space: str = "general"
    tool_runtime_config: ToolRuntimeConfig | None = None
    join: bool = False


@dataclass(frozen=True)
class ContextOptions:
    """Summarization and compaction knobs.

    ``summarize`` / ``compact`` include the respective middleware; summarization
    is also skipped, with a warning, when the stack has no ``chat_llm``.
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
    """LoopGuardMiddleware knobs; warn-only unless ``hard_stop``."""

    enabled: bool = True
    hard_stop: bool = LOOP_GUARD_HARD_STOP


def create_middleware_stack(
    *,
    agent_name: str = "agent",
    chat_llm: LanguageModelLike | None = None,
    accounting: AccountingOptions = AccountingOptions(),
    subagent: SubagentStackOptions = SubagentStackOptions(),
    context: ContextOptions = ContextOptions(),
    loop_guard: LoopGuardOptions = LoopGuardOptions(),
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
        accounting: LLMAccountingMiddleware (on by default) and the recursion
            limit it reports against.
        subagent: SubagentMiddleware wiring (off by default): the spawned
            subagents' LLM, tools, registry, exclusions, tool space and runtime
            config, plus the executor-only join enforcement.
        context: Summarization and compaction: whether each is on, the
            summarization trigger/keep sizes and archive flag, the compaction
            threshold and per-output cap, and the tools each must leave alone.
        loop_guard: LoopGuardMiddleware (on by default) and whether it hard-stops.

    Returns:
        List of AgentMiddleware instances in execution order
    """
    middleware: AgentMiddlewareStack = []

    # LLM accounting middleware — emits `llm_call` wide events + recursion
    # high-water-mark signals. Inserted FIRST so it observes every model call
    # on the way in (before_model) and on the way out (after_model).
    # ``caching_debug`` flips on a second diagnostic instance that runs LAST,
    # so we can compare state.messages before vs. after other middleware.
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

    # HIL approval gate — outermost tool-call wrapper (only accounting, a
    # before/after_model hook, precedes it) so no other middleware runs a side
    # effect before the user decides. A no-op unless the user's HIL preference is
    # on, so it needs no build-time flag.
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

    # Media description — a lane that can't see pixels gets prose for any tool
    # result carrying images. Inner to compaction, so the description is attached
    # before compaction inspects the result; compaction never spills media anyway.
    # No enable flag: it no-ops on every result without media, i.e. nearly all.
    middleware.append(MediaDescriptionMiddleware())
    log.debug(f"{LogTag.AGENT} Media description middleware enabled", agent_name=agent_name)

    # Loop-guard middleware — added LAST so it sits innermost and observes the
    # raw tool result before compaction/summarization transform it, counting the
    # tool's actual failures. warn-only unless hard_stop is enabled.
    if loop_guard.enabled:
        middleware.append(LoopGuardMiddleware(hard_stop=loop_guard.hard_stop))
        log.debug(
            f"{LogTag.AGENT} Loop guard middleware enabled",
            agent_name=agent_name,
            hard_stop=loop_guard.hard_stop,
        )

    # Subagent-join enforcement (executor only) — after everything else so it
    # sees the response other after_model hooks may have adjusted. Rewrites a
    # turn-ending response into a wait_for_subagents call while background
    # subagents are uncollected; collection must never depend on the model
    # remembering to call the join.
    if subagent.join:
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
        accounting=AccountingOptions(recursion_limit=EXECUTOR_RECURSION_LIMIT),
        subagent=SubagentStackOptions(
            enabled=True,
            llm=subagent_llm,
            tools=subagent_tools,
            registry=subagent_registry,
            excluded_tools=subagent_excluded_tools,
            tool_runtime_config=subagent_tool_runtime_config,
            join=True,
        ),
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
        context=ContextOptions(compact=False),
    )
    # Innermost of the wrap_model_call chain, so it scores the response the
    # model actually produced rather than one an outer middleware has already
    # substituted (the budget wall's stop text, for one, is not the model's
    # prose and must not be rewritten).
    stack.append(StyleGuardMiddleware())
    log.debug(f"{LogTag.AGENT} StyleGuardMiddleware enabled", agent_name="comms_agent")
    return stack


def create_subagent_middleware(
    *,
    agent_name: str = "provider_subagent",
    subagent: SubagentStackOptions = SubagentStackOptions(enabled=True),
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
        subagent: The spawn wiring. ``llm`` is both the subagent's own model
            (its summarization and compaction ride it) and the model its spawned
            sub-subagents run on; ``tools``/``registry``/``excluded_tools``/
            ``tool_space``/``tool_runtime_config`` shape what those sub-subagents
            may reach. ``enabled=False`` leaves out the spawn_subagent middleware,
            for authoring-only subagents that must not spawn or execute.

    Returns:
        List of middleware for provider subagents
    """
    return create_middleware_stack(
        agent_name=agent_name,
        chat_llm=subagent.llm,
        subagent=subagent,
        context=ContextOptions(
            # Summarization and compaction stay on (the ContextOptions defaults):
            # without summarization a subagent run grows unbounded, averaging 91k
            # input tokens per call in production against 43k for comms/executor.
            compaction_excluded_tools=CODING_TOOL_NAMES
            | SPAWN_SUBAGENT_TOOL
            | SELF_OFFLOADING_TOOL_NAMES,
        ),
    )
