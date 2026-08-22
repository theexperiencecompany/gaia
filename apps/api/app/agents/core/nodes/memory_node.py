"""Memory learning node — end_graph_hook for user memory ingestion.

After a worth-learning conversation ends, spawns a fire-and-forget
background task that feeds the transcript through
``memory_engine.retain`` (plan F2). The node returns immediately —
zero added latency on the turn.
"""

import contextlib

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.config.oauth_config import get_memory_extraction_prompt
from app.constants.log_tags import LogTag
from app.constants.memory import (
    MIN_USER_CONTENT_CHARS,
    MemorySourceType,
)
from app.memory.engine import memory_engine
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import State
from app.utils.background_tasks import spawn_background_task
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import UserContext, log, wide_task

MAX_TOOL_OUTPUT_SIZE = 500


def _check_worth_learning(messages: list[AnyMessage]) -> tuple[bool, str]:
    """Whether a turn carries any substantive user content worth extracting.

    No message-count or tool-call gating: a single-message disclosure ("my
    name is Sam", "my girlfriend's birthday is March 12") must be learned.
    We ingest whenever any user message has real text and let the extraction
    LLM decide if anything durable is present — it returns an empty batch for
    smalltalk, so only truly empty turns ("hi", "ok") are skipped here.

    Returns:
        Tuple of (should_learn, reason)
    """
    for msg in messages:
        if isinstance(msg, HumanMessage):
            if len(extract_text_content(msg.content).strip()) >= MIN_USER_CONTENT_CHARS:
                return True, "OK"
    return False, "No substantive user message"


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
            content = extract_text_content(msg.content)
            if content:
                formatted.append({"role": "user", "content": content})

        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for call in msg.tool_calls:
                    tool_content = f"[TOOL CALL: {call['name']}({call.get('args', {})})]"
                    formatted.append({"role": "assistant", "content": tool_content})
            elif msg.content:
                formatted.append(
                    {"role": "assistant", "content": extract_text_content(msg.content)}
                )

        elif isinstance(msg, ToolMessage):
            # Truncate tool OUTPUTS only - they're usually large API responses.
            # Text-extract first so inline media blocks never leak base64 here.
            content = extract_text_content(msg.content)
            if len(content) > MAX_TOOL_OUTPUT_SIZE:
                content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
            formatted.append({"role": "assistant", "content": f"[TOOL RESULT: {content}]"})

    return formatted


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

    Runs in its own ``wide_task`` scope: this is a fire-and-forget background
    task outside any request middleware, so without an explicit task scope the
    engine's structured logging (and any failure) would never be emitted.
    """
    formatted = _format_messages_for_user_memory(messages)
    if not formatted:
        return

    # wide_task records any failure (error_type + outcome=failed) as an emitted
    # wide event and a real-time error line; suppress the re-raised exception so
    # this fire-and-forget task doesn't surface an un-retrieved-exception warning.
    with contextlib.suppress(Exception):
        async with wide_task("memory_retain", user=UserContext(id=user_id)):
            log.set(subagent_id=subagent_id or "agent", session_id=session_id)
            await memory_engine.retain(
                user_id,
                formatted,
                source_type=MemorySourceType.CONVERSATION,
                source_id=session_id,
                extraction_hints=extraction_prompt,
                user_name=user_name,
            )


async def memory_node(
    state: State,
    config: RunnableConfig,
    store: BaseStore,  # noqa: ARG001 -- framework contract
) -> State:
    """
    End-graph hook that stores user memory from agent executions.

    Spawns a background task (non-blocking) that runs ``memory_engine.retain``
    over the transcript with the integration-specific extraction prompt.
    Uses fire-and-forget via asyncio.create_task() — zero added latency.
    """
    messages = state.get("messages", [])

    # Extract all config values upfront
    configurable = agent_configurable(config)
    user_id = configurable.get("user_id")
    subagent_id = configurable.get("subagent_id")
    session_id = configurable.get("thread_id")
    user_name = configurable.get("user_name")

    # Look up extraction prompt from registry using subagent_id
    extraction_prompt = get_memory_extraction_prompt(subagent_id) if subagent_id else None

    # Quick validation - skip trivial conversations
    should_learn, reason = _check_worth_learning(messages)
    if not should_learn:
        log.debug(f"{LogTag.AGENT} Memory learning skipped", reason=reason)
        return state

    if user_id:
        task = spawn_background_task(
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
        log.debug(
            f"{LogTag.AGENT} Memory learning spawned",
            subagent_id=subagent_id,
            task_name=task.get_name(),
        )

    return state
