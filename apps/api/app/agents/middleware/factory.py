"""
Middleware Factory - Centralized creation of agent middleware.

Provides factory functions for creating the standard middleware stack
used across agents (executor, comms, subagents).

This module consolidates middleware creation to:
- Avoid code duplication across build_graph.py and base_subagent.py
- Centralize configuration (thresholds, models, etc.)
- Make it easy to modify middleware behavior globally
"""

from typing import Optional

from app.agents.middleware.vfs_compaction import VFSCompactionMiddleware
from app.agents.middleware.vfs_summarization import VFSArchivingSummarizationMiddleware
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.constants.summarization import (
    COMPACTION_THRESHOLD,
    MAX_OUTPUT_TOKENS,
    SUMMARIZATION_KEEP_TOKENS,
    SUMMARIZATION_MODEL,
    SUMMARIZATION_TRIGGER_FRACTION,
)
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

_summarization_llm: Optional[BaseChatModel] = None


def get_summarization_llm() -> Optional[BaseChatModel]:
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
        logger.warning(
            "Google API key not configured. Summarization middleware disabled."
        )
        return None

    _summarization_llm = ChatGoogleGenerativeAI(
        model=SUMMARIZATION_MODEL,
        temperature=0.1,  # Low temperature for consistent summaries
    )
    return _summarization_llm


def create_middleware_stack(
    *,
    enable_summarization: bool = True,
    enable_compaction: bool = True,
    summarization_trigger: tuple = ("fraction", SUMMARIZATION_TRIGGER_FRACTION),
    summarization_keep: tuple = ("tokens", SUMMARIZATION_KEEP_TOKENS),
    compaction_threshold: float = COMPACTION_THRESHOLD,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    vfs_enabled: bool = True,
) -> list:
    """
    Create the standard middleware stack for agents.

    Uses LangChain's AgentMiddleware system:
    - VFSArchivingSummarizationMiddleware: Archives to VFS and summarizes at threshold
    - VFSCompactionMiddleware: Compacts large tool outputs to VFS

    Args:
        enable_summarization: Whether to include summarization middleware
        enable_compaction: Whether to include compaction middleware
        summarization_trigger: When to trigger summarization (fraction/tokens/messages)
        summarization_keep: How much to keep after summarization (tokens recommended)
        compaction_threshold: Context usage ratio to trigger compaction
        max_output_tokens: Max tokens for single tool output before compaction
        vfs_enabled: Whether to archive to VFS before summarization

    Returns:
        List of AgentMiddleware instances in execution order
    """
    middleware = []

    # Summarization middleware (requires Gemini API key)
    if enable_summarization:
        summary_llm = get_summarization_llm()
        if summary_llm:
            summarization = VFSArchivingSummarizationMiddleware(
                model=summary_llm,
                trigger=summarization_trigger,
                keep=summarization_keep,
                vfs_enabled=vfs_enabled,
            )
            middleware.append(summarization)
            logger.debug(
                f"Summarization middleware enabled: trigger={summarization_trigger}, keep={summarization_keep}"
            )

    # Compaction middleware (always available, but respects enable flag)
    if enable_compaction:
        compaction = VFSCompactionMiddleware(
            compaction_threshold=compaction_threshold,
            max_output_tokens=max_output_tokens,
        )
        middleware.append(compaction)
        logger.debug(f"Compaction middleware enabled: threshold={compaction_threshold}")

    return middleware


def create_default_middleware() -> list:
    """
    Create the default middleware stack with standard settings.

    This is the most common configuration used by executor, comms, and subagents.
    """
    return create_middleware_stack()
