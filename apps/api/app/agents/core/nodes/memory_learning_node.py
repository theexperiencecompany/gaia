"""
Memory Learning Node - Unified end_graph_hook for both skill and user memory extraction.

Spawns TWO parallel background tasks (non-blocking):

1. SKILL MEMORY (agent_id namespace) - NEW: Uses custom skill learning
   - Learns procedural knowledge: "how to send DM", "how to create issue"
   - Two extraction strategies: LLM extraction + self-reflection
   - Stored in MongoDB (agent_skills collection)
   - Shared across all users of this subagent

2. USER MEMORY (user_id namespace) - Uses mem0
   - Learns user-specific data: IDs, contacts, preferences
   - Uses integration-specific prompts (SLACK_MEMORY_PROMPT, etc.)
   - Private to each user

These are completely isolated - skills in MongoDB, user memory in mem0.
Both tasks use fire-and-forget pattern - node returns immediately with zero latency.
"""

import asyncio
from typing import Dict, List, Optional

from app.agents.memory.skill_learning.service import learn_skills
from app.config.loggers import llm_logger as logger
from app.config.oauth_config import get_memory_extraction_prompt
from app.config.settings import settings
from app.services.memory_service import memory_service
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State

MAX_TOOL_OUTPUT_SIZE = 500

# Module-level set to hold references to background tasks, preventing GC
# Tasks are automatically removed from the set when they complete via done callback
_background_tasks: set[asyncio.Task] = set()


def _task_done_callback(task: asyncio.Task) -> None:
    """Callback to remove completed tasks from the background tasks set."""
    _background_tasks.discard(task)


def _get_user_id(config: RunnableConfig) -> Optional[str]:
    """Extract user_id from config for user memory namespace."""
    return config.get("configurable", {}).get("user_id")


def _get_subagent_id(config: RunnableConfig) -> Optional[str]:
    """Extract subagent ID from config for memory namespace."""
    return config.get("configurable", {}).get("subagent_id")


def _get_session_id(config: RunnableConfig) -> Optional[str]:
    """Extract session/thread ID for memory correlation."""
    return config.get("configurable", {}).get("thread_id")


def _check_worth_learning(messages: List[AnyMessage]) -> tuple[bool, str]:
    """Check if conversation has enough content for memory extraction.

    We skip trivial conversations to avoid noise in memory storage.

    Returns:
        Tuple of (should_learn, reason)
    """
    if len(messages) < 4:
        return False, "Too few messages"

    # Count tool calls - simple interactions don't need memory
    tool_calls = sum(
        len(msg.tool_calls)
        for msg in messages
        if isinstance(msg, AIMessage) and msg.tool_calls
    )

    if tool_calls < 2:
        return False, f"Only {tool_calls} tool calls - too simple"

    return True, "OK"


def _format_messages_for_user_memory(
    messages: List[AnyMessage],
) -> List[Dict[str, str]]:
    """Convert messages to mem0 format for user memory extraction.

    Key design decisions:
    - Keep tool INPUTS intact (they contain entity info like IDs, names, emails)
    - Truncate tool OUTPUTS only (API responses can be huge but rarely contain
      reusable entity info)
    - Skip system messages (not relevant for user memory)

    Returns:
        List of role/content dicts for mem0 API
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
                    tool_content = (
                        f"[TOOL CALL: {call['name']}({call.get('args', {})})]"
                    )
                    formatted.append({"role": "assistant", "content": tool_content})
            elif msg.content:
                formatted.append({"role": "assistant", "content": str(msg.content)})

        elif isinstance(msg, ToolMessage):
            # Truncate tool OUTPUTS only - they're usually large API responses
            content = str(msg.content)
            if len(content) > MAX_TOOL_OUTPUT_SIZE:
                content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
            formatted.append(
                {"role": "assistant", "content": f"[TOOL RESULT: {content}]"}
            )

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


async def _store_skill_background(
    messages: List[AnyMessage],
    subagent_id: str,
    session_id: Optional[str],
) -> None:
    """Background task - stores SKILL memory using custom skill learning.

    Uses our custom skill extraction system with two approaches:
    1. LLM Extraction - Cheap model analyzes the conversation
    2. Self-Reflection - Model documents its own experience

    Skills are stored in MongoDB (agent_skills collection).
    These skills are shared across all users of this subagent.
    """
    try:
        await learn_skills(
            messages=messages,
            agent_id=subagent_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(f"[{subagent_id}] Skill learning failed: {e}")


async def _store_user_memory_background(
    messages: List[AnyMessage],
    user_id: str,
    session_id: Optional[str],
    extraction_prompt: Optional[str],
    subagent_id: Optional[str],
) -> None:
    """Background task - stores USER memory (user_id namespace).

    Uses integration-specific prompts (if available) to extract:
    - Entity IDs (Slack channel IDs, GitHub repos, contact emails)
    - User preferences (formatting, timing, style)
    - Personal patterns (who they message, which repos they work on)

    These memories are private to each user.
    """
    try:
        formatted = _format_messages_for_user_memory(messages)
        if not formatted:
            return

        metadata = {
            "memory_type": "user",
        }
        if subagent_id:
            metadata["source_integration"] = subagent_id

        # Store to USER namespace (user_id is the entity)
        success = await memory_service.store_memory_batch(
            messages=formatted,
            user_id=user_id,
            conversation_id=session_id,
            metadata=metadata,
            custom_instructions=extraction_prompt,
            async_mode=True,
        )

        if success:
            logger.info(
                f"[{subagent_id or 'agent'}] User memory stored for {user_id[:8]}..."
            )
    except Exception as e:
        logger.error(f"[{subagent_id or 'agent'}] User memory storage failed: {e}")


async def memory_learning_node(
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """
    End-graph hook that learns from subagent executions.

    Spawns TWO parallel background tasks (non-blocking):

    1. SKILL MEMORY (if subagent_id available)
       - Entity: agent_id = subagent_id (twitter, github, etc.)
       - Prompt: Generic SKILL_EXTRACTION_PROMPT
       - Purpose: Learn procedural workflows shared across users

    2. USER MEMORY (if user_id available)
       - Entity: user_id
       - Prompt: Integration-specific (or mem0 default)
       - Purpose: Learn IDs, contacts, preferences private to user

    Both use fire-and-forget pattern via asyncio.create_task().
    Node returns immediately - zero added latency.
    """
    messages = state.get("messages", [])

    # Extract all config values upfront
    user_id = _get_user_id(config)
    subagent_id = _get_subagent_id(config)
    session_id = _get_session_id(config)

    # Look up extraction prompt from registry using subagent_id
    extraction_prompt = (
        get_memory_extraction_prompt(subagent_id) if subagent_id else None
    )

    # Quick validation - skip trivial conversations
    should_learn, reason = _check_worth_learning(messages)
    if not should_learn:
        logger.debug(f"Memory learning skipped: {reason}")
        return state

    # Track spawned Task objects to prevent GC and allow later awaiting/gathering
    tasks_spawned: list[asyncio.Task] = []

    # 1. SKILL MEMORY (requires subagent_id and feature flag enabled)
    if subagent_id and settings.SKILL_LEARNING_ENABLED:
        task = asyncio.create_task(
            _store_skill_background(
                messages=messages,
                subagent_id=subagent_id,
                session_id=session_id,
            ),
            name="skill_memory",
        )
        tasks_spawned.append(task)

    # 2. USER MEMORY (requires user_id for namespace)
    if user_id:
        task = asyncio.create_task(
            _store_user_memory_background(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                extraction_prompt=extraction_prompt,
                subagent_id=subagent_id,
            ),
            name="user_memory",
        )
        tasks_spawned.append(task)

    if tasks_spawned:
        # Register tasks in module-level set to prevent GC
        for task in tasks_spawned:
            _background_tasks.add(task)
            task.add_done_callback(_task_done_callback)

        task_names = [t.get_name() for t in tasks_spawned]
        logger.debug(
            f"[{subagent_id or 'agent'}] Memory learning spawned: {', '.join(task_names)}"
        )

    return state
