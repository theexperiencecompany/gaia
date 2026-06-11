"""Memory learning node — end_graph_hook for user memory ingestion.

After a worth-learning conversation ends, spawns a fire-and-forget
background task that feeds the transcript through
``memory_engine.retain`` (plan F2). The node returns immediately —
zero added latency on the turn.
"""

import asyncio

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.config.oauth_config import get_memory_extraction_prompt
from app.constants.memory import (
    MIN_MESSAGES_TO_LEARN,
    MIN_TOOL_CALLS_TO_LEARN,
    MemorySourceType,
)
from app.memory.engine import memory_engine
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log

MAX_TOOL_OUTPUT_SIZE = 500

# Module-level set to hold references to background tasks, preventing GC
# Tasks are automatically removed from the set when they complete via done callback
_background_tasks: set[asyncio.Task] = set()


def _task_done_callback(task: asyncio.Task) -> None:
    """Callback to remove completed tasks from the background tasks set."""
    _background_tasks.discard(task)


def _get_user_id(config: RunnableConfig) -> str | None:
    """Extract user_id from config for user memory namespace."""
    return config.get("configurable", {}).get("user_id")


def _get_user_name(config: RunnableConfig) -> str | None:
    """Extract the user's display name from config for fact attribution."""
    return config.get("configurable", {}).get("user_name")


def _get_subagent_id(config: RunnableConfig) -> str | None:
    """Extract subagent ID from config for memory namespace."""
    return config.get("configurable", {}).get("subagent_id")


def _get_session_id(config: RunnableConfig) -> str | None:
    """Extract session/thread ID for memory correlation."""
    return config.get("configurable", {}).get("thread_id")


def _check_worth_learning(messages: list[AnyMessage]) -> tuple[bool, str]:
    """Check if a conversation has enough content to be worth extracting.

    The gate is OR, not AND: a substantial pure-text conversation (no tool
    calls) is the richest memory source — the user disclosing relationships,
    preferences, and dates is exactly what must be remembered. A shorter
    exchange still qualifies if it drove enough tool activity to be
    meaningful. Only genuinely trivial turns are skipped.

    Returns:
        Tuple of (should_learn, reason)
    """
    if len(messages) >= MIN_MESSAGES_TO_LEARN:
        return True, "OK"

    tool_calls = sum(
        len(msg.tool_calls) for msg in messages if isinstance(msg, AIMessage) and msg.tool_calls
    )
    if tool_calls >= MIN_TOOL_CALLS_TO_LEARN:
        return True, "OK"

    return False, f"Trivial turn ({len(messages)} messages, {tool_calls} tool calls)"


def _format_messages_for_user_memory(
    messages: list[AnyMessage],
) -> list[dict[str, str]]:
    """Convert messages to a role/content transcript for the extraction LLM.

    Key design decisions:
    - Keep tool INPUTS intact (they contain entity info like IDs, names, emails)
    - Truncate tool OUTPUTS only (API responses can be huge but rarely contain
      reusable entity info)
    - Skip system messages (not relevant for user memory)

    Returns:
        List of role/content dicts for the memory engine
    """
    formatted = []

    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = _extract_text_content(msg.content)
            if content:
                formatted.append({"role": "user", "content": content})

        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for call in msg.tool_calls:
                    tool_content = f"[TOOL CALL: {call['name']}({call.get('args', {})})]"
                    formatted.append({"role": "assistant", "content": tool_content})
            elif msg.content:
                formatted.append({"role": "assistant", "content": str(msg.content)})

        elif isinstance(msg, ToolMessage):
            # Truncate tool OUTPUTS only - they're usually large API responses
            content = str(msg.content)
            if len(content) > MAX_TOOL_OUTPUT_SIZE:
                content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
            formatted.append({"role": "assistant", "content": f"[TOOL RESULT: {content}]"})

    return formatted


def _extract_text_content(content) -> str:
    """Extract text from potentially multimodal message content.

    Handles both simple strings and list-of-blocks format.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return " ".join(text_parts)

    return str(content)


async def _store_user_memory_background(
    messages: list[AnyMessage],
    user_id: str,
    session_id: str | None,
    extraction_prompt: str | None,
    subagent_id: str | None,
    user_name: str | None,
) -> None:
    """Background task — ingests the conversation through the memory engine.

    Integration-specific extraction prompts (Slack, GitHub, ...) ride along
    as extraction hints so the engine pulls out entity IDs, contacts, and
    preferences relevant to that integration. Memories are private per user.
    """
    try:
        formatted = _format_messages_for_user_memory(messages)
        if not formatted:
            return

        result = await memory_engine.retain(
            user_id,
            formatted,
            source_type=MemorySourceType.CONVERSATION,
            source_id=session_id,
            extraction_hints=extraction_prompt,
            user_name=user_name,
        )
        log.info(
            f"[{subagent_id or 'agent'}] User memory ingested for {user_id[:8]}...: "
            f"{result.facts_extracted} facts extracted"
        )
    except Exception as e:
        log.error(f"[{subagent_id or 'agent'}] User memory storage failed: {e}")


async def memory_node(
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """
    End-graph hook that stores user memory from agent executions.

    Spawns a background task (non-blocking) that runs ``memory_engine.retain``
    over the transcript with the integration-specific extraction prompt.
    Uses fire-and-forget via asyncio.create_task() — zero added latency.
    """
    messages = state.get("messages", [])

    # Extract all config values upfront
    user_id = _get_user_id(config)
    subagent_id = _get_subagent_id(config)
    session_id = _get_session_id(config)
    user_name = _get_user_name(config)

    # Look up extraction prompt from registry using subagent_id
    extraction_prompt = get_memory_extraction_prompt(subagent_id) if subagent_id else None

    # Quick validation - skip trivial conversations
    should_learn, reason = _check_worth_learning(messages)
    if not should_learn:
        log.debug(f"Memory learning skipped: {reason}")
        return state

    if user_id:
        task = asyncio.create_task(
            _store_user_memory_background(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                extraction_prompt=extraction_prompt,
                subagent_id=subagent_id,
                user_name=user_name,
            ),
            name="user_memory",
        )

        _background_tasks.add(task)
        task.add_done_callback(_task_done_callback)
        log.debug(f"[{subagent_id or 'agent'}] Memory learning spawned: {task.get_name()}")

    return state
