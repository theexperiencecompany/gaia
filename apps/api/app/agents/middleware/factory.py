"""
Middleware Factory - Centralized creation of agent middleware.

Provides factory functions for creating the standard middleware stack
used across agents (executor, comms, subagents).

This module consolidates middleware creation to:
- Avoid code duplication across build_graph.py and base_subagent.py
- Centralize configuration (thresholds, models, etc.)
- Make it easy to modify middleware behavior globally
"""

from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.middleware.summarization import (
    WorkspaceArchivingSummarizationMiddleware,
)
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.config.settings import settings
from app.constants.summarization import (
    COMPACTION_THRESHOLD,
    MAX_OUTPUT_CHARS,
    SUMMARIZATION_KEEP_TOKENS,
    SUMMARIZATION_MODEL,
    SUMMARIZATION_TRIGGER_FRACTION,
)
from shared.py.wide_events import log

# Coding tools operate on the persistent E2B workspace; their outputs are
# already capped by the bash output limiter and the read tool's pagination,
# so the compaction middleware should leave them alone.
CODING_TOOL_NAMES = {"bash", "read", "write", "edit"}
SPAWN_SUBAGENT_TOOL = {"spawn_subagent"}

_summarization_llm: BaseChatModel | None = None


def get_summarization_llm() -> BaseChatModel | None:
    """
    Get the LLM instance for summarization.

    Uses Gemini Flash 2 for fast, cost-effective context summarization.
    Returns None if Google API key is not configured.

    The LLM is cached for reuse across middleware instances.
    """
    global _summarization_llm

    if _summarization_llm is not None:
        return _summarization_llm

    if not settings.GOOGLE_API_KEY:
        log.warning("Google API key not configured. Summarization middleware disabled.")
        return None

    _summarization_llm = ChatGoogleGenerativeAI(
        model=SUMMARIZATION_MODEL,
        temperature=0.1,  # Low temperature for consistent summaries
    )
    return _summarization_llm


def create_middleware_stack(
    *,
    agent_name: str = "agent",
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
    summarization_trigger: tuple = ("fraction", SUMMARIZATION_TRIGGER_FRACTION),
    summarization_keep: tuple = ("tokens", SUMMARIZATION_KEEP_TOKENS),
    compaction_threshold: float = COMPACTION_THRESHOLD,
    max_output_chars: int = MAX_OUTPUT_CHARS,
    enable_archive: bool = True,
    compaction_excluded_tools: set[str] | None = None,
    summarization_excluded_tools: set[str] | None = None,
) -> list[Any]:
    """
    Create the standard middleware stack for agents.

    Uses LangChain's AgentMiddleware system:
    - SubagentMiddleware: Spawn subagents for parallel/focused work
    - WorkspaceArchivingSummarizationMiddleware: Archives history to the user's
      persistent workspace and summarizes at threshold
    - WorkspaceCompactionMiddleware: Persists large tool outputs to the
      persistent workspace and replaces them with a /workspace/... reference

    Args:
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
    middleware: list[Any] = []

    # LLM accounting middleware — emits `llm_call` wide events + recursion
    # high-water-mark signals. Inserted FIRST so it observes every model call
    # on the way in (before_model) and on the way out (after_model).
    # ``caching_debug`` flips on a second diagnostic instance that runs LAST,
    # so we can compare state.messages before vs. after other middleware.
    if enable_accounting:
        middleware.append(LLMAccountingMiddleware(agent_name=agent_name))
        log.debug(f"LLMAccountingMiddleware enabled for {agent_name}")
        log.set(
            middleware_stack={
                "agent_name": agent_name,
                "accounting_enabled": True,
            }
        )

    # SubagentMiddleware - spawn_subagent tool for parallel/focused work
    if enable_subagent:
        subagent = SubagentMiddleware(
            llm=subagent_llm,
            available_tools=subagent_tools,
            tool_registry=subagent_registry,
            excluded_tool_names=subagent_excluded_tools,
            tool_space=subagent_tool_space,
            tool_runtime_config=subagent_tool_runtime_config,
        )
        middleware.append(subagent)
        log.debug("SubagentMiddleware enabled with spawn_subagent tool")

    # Summarization middleware (requires Gemini API key)
    if enable_summarization:
        summary_llm = get_summarization_llm()
        if summary_llm:
            summarization = WorkspaceArchivingSummarizationMiddleware(
                model=summary_llm,
                trigger=summarization_trigger,
                keep=summarization_keep,
                enable_archive=enable_archive,
                excluded_tools=summarization_excluded_tools,
            )
            middleware.append(summarization)
            log.debug(
                f"Summarization middleware enabled: trigger={summarization_trigger}, keep={summarization_keep}"
            )

    # Compaction middleware (always available, but respects enable flag)
    if enable_compaction:
        compaction = WorkspaceCompactionMiddleware(
            compaction_threshold=compaction_threshold,
            max_output_chars=max_output_chars,
            excluded_tools=compaction_excluded_tools,
        )
        middleware.append(compaction)
        log.debug(f"Compaction middleware enabled: threshold={compaction_threshold}")

    return middleware


def create_executor_middleware(
    *,
    subagent_llm: LanguageModelLike | None = None,
    subagent_tools: list[BaseTool] | None = None,
    subagent_registry: Mapping[str, BaseTool] | None = None,
    subagent_excluded_tools: set[str] | None = None,
    subagent_tool_runtime_config: ToolRuntimeConfig | None = None,
) -> list[Any]:
    """
    Create middleware stack for the executor agent.

    The executor agent handles complex multi-step tasks and should have:
    - SubagentMiddleware: For parallel/focused work with lightweight subagents
    - Summarization and compaction middleware

    The executor's SubagentMiddleware needs LLM and tool_registry set after
    creation via set_llm()/set_tools() since they aren't available at factory time.

    Args:
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
        enable_subagent=True,
        subagent_llm=subagent_llm,
        subagent_tools=subagent_tools,
        subagent_registry=subagent_registry,
        subagent_excluded_tools=subagent_excluded_tools,
        subagent_tool_runtime_config=subagent_tool_runtime_config,
        compaction_excluded_tools=CODING_TOOL_NAMES | SPAWN_SUBAGENT_TOOL,
    )


def create_comms_middleware() -> list[Any]:
    """
    Create middleware stack for the comms agent.

    The comms agent handles user communication and delegates complex work
    to the executor. Only includes summarization and compaction middleware.

    Returns:
        List of middleware for comms agent
    """
    return create_middleware_stack(
        agent_name="comms_agent",
        enable_subagent=False,
        compaction_excluded_tools=CODING_TOOL_NAMES,
    )


def create_subagent_middleware(
    *,
    todo_source: str = "subagent",
    subagent_llm: LanguageModelLike | None = None,
    subagent_tools: list[BaseTool] | None = None,
    subagent_registry: Mapping[str, BaseTool] | None = None,
    subagent_excluded_tools: set[str] | None = None,
    subagent_tool_space: str = "general",
    subagent_tool_runtime_config: ToolRuntimeConfig | None = None,
) -> list[Any]:
    """
    Create middleware stack for provider subagents.

    Provider subagents handle focused integration work and should have:
    - SubagentMiddleware: For spawning focused sub-subagents
    - WorkspaceCompactionMiddleware: Persist oversized tool outputs to /workspace
    - NO summarization

    Spawned sub-subagents will NOT have SubagentMiddleware (enforced by
    SubagentMiddleware itself which excludes spawn_subagent from child tools).

    Args:
        todo_source: Kept for API compatibility (unused — todo source set in todo_tools)
        subagent_llm: LLM for spawned sub-subagent execution
        subagent_tools: Tools available to spawned sub-subagents
        subagent_registry: Alternative tool registry for spawned sub-subagents
        subagent_excluded_tools: Tool names to exclude from sub-subagent access
        subagent_tool_space: Tool space for spawned sub-subagent retrieve_tools search

    Returns:
        List of middleware for provider subagents
    """
    return create_middleware_stack(
        agent_name="provider_subagent",
        enable_subagent=True,
        enable_summarization=False,
        enable_compaction=True,
        subagent_llm=subagent_llm,
        subagent_tools=subagent_tools,
        subagent_registry=subagent_registry,
        subagent_excluded_tools=subagent_excluded_tools,
        subagent_tool_space=subagent_tool_space,
        subagent_tool_runtime_config=subagent_tool_runtime_config,
        compaction_excluded_tools=CODING_TOOL_NAMES | SPAWN_SUBAGENT_TOOL,
    )
