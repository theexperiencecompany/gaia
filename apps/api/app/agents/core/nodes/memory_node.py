"""Memory learning node — end_graph_hook for user memory ingestion.

After a worth-learning comms turn ends, spawns a fire-and-forget background
task that feeds the NEW part of the transcript through memory_engine.retain.
The node returns immediately — zero added latency. Three things bound what
the extractor is shown: Roles (assistant/tool/user were all "assistant",
confusing what the user said with GAIA's own words); Delta (a 152-checkpoint
conversation once re-extracted the same transcript ~76 times); Provenance
(a system-generated conversation's "user" turn is a generated instruction,
not a disclosure).
"""

import contextlib

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import PromptSlot, slot_of
from app.config.oauth_config import get_memory_extraction_prompt
from app.constants.log_tags import LogTag
from app.constants.memory import (
    MEMORY_DELTA_CONTEXT_MESSAGES,
    MEMORY_INGEST_MARK_KEY,
    MEMORY_INGEST_MARK_TTL,
    MIN_USER_CONTENT_CHARS,
    MemorySourceType,
)
from app.db.redis import redis_cache
from app.db.repositories.conversations import conversation_repository
from app.memory.engine import memory_engine
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import State
from app.utils.background_tasks import spawn_background_task
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import UserContext, log, wide_task

MAX_TOOL_OUTPUT_SIZE = 500

# Transcript roles the extractor sees. "gaia" is deliberately not "assistant":
# the extraction prompt tells the model that a gaia turn is never itself a fact
# about the user, and a distinct label is what makes that rule applicable.
_ROLE_USER = "user"
_ROLE_GAIA = "gaia"
_ROLE_TOOL = "tool"
_ROLE_MARKER = "transcript"

_CONTEXT_MARKER = "--- earlier context: already extracted, do NOT re-extract ---"
_DELTA_MARKER = "--- new since the last extraction ---"


def _check_worth_learning(messages: list[AnyMessage]) -> tuple[bool, str]:
    """Return whether a turn carries any substantive user content worth extracting.

    No message-count or tool-call gating: a single-message disclosure must
    be learned. Ingests whenever any user message has real text and lets the
    extraction LLM decide if anything durable is present.
    """
    for msg in messages:
        # slot_of filters graph plumbing that rides the thread as a
        # HumanMessage — the re-stamped current-time slot lands in every
        # delta, and counted as user text it made this check always-true.
        if isinstance(msg, HumanMessage) and slot_of(msg) is PromptSlot.CONVERSATION:
            if len(extract_text_content(msg.content).strip()) >= MIN_USER_CONTENT_CHARS:
                return True, "OK"
    return False, "No substantive user message"


def _delta_worth_learning(delta: list[AnyMessage]) -> bool:
    """Return whether the NEW slice of a thread justifies an extraction call.

    The node's thread-level check passes on ANY substantive user message,
    however old, which once made half of production extraction calls yield
    zero facts. Substance is real user text OR tool activity — a short "yes"
    that triggered work still journals what was done.
    """
    worth, _ = _check_worth_learning(delta)
    if worth:
        return True
    return any(
        isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage) and msg.tool_calls)
        for msg in delta
    )


def _format_messages_for_user_memory(
    messages: list[AnyMessage],
    context_count: int = 0,
) -> list[dict[str, str]]:
    """Convert messages to a role/content transcript for the extraction LLM.

    Three roles: user, gaia (its own words aren't evidence about the user),
    tool. Tool INPUTS are kept intact (ids, names, emails); tool OUTPUTS are
    truncated. context_count leading messages are prior context, fenced off
    so the extractor reads them without re-extracting.
    """
    formatted: list[dict[str, str]] = []
    if context_count:
        formatted.append({"role": _ROLE_MARKER, "content": _CONTEXT_MARKER})

    for index, msg in enumerate(messages):
        if context_count and index == context_count:
            formatted.append({"role": _ROLE_MARKER, "content": _DELTA_MARKER})

        if isinstance(msg, HumanMessage):
            # Non-conversation slots (the re-stamped current-time message)
            # are graph plumbing that would pollute the transcript.
            if slot_of(msg) is not PromptSlot.CONVERSATION:
                continue
            content = extract_text_content(msg.content)
            if content:
                formatted.append({"role": _ROLE_USER, "content": content})

        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for call in msg.tool_calls:
                    formatted.append(
                        {
                            "role": _ROLE_GAIA,
                            "content": f"[CALLED TOOL: {call['name']}({call['args']})]",
                        }
                    )
            elif msg.content:
                formatted.append({"role": _ROLE_GAIA, "content": extract_text_content(msg.content)})

        elif isinstance(msg, ToolMessage):
            # Text-extract first so inline media blocks never leak base64 here.
            content = extract_text_content(msg.content)
            if len(content) > MAX_TOOL_OUTPUT_SIZE:
                content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
            formatted.append({"role": _ROLE_TOOL, "content": content})

    return formatted


async def _messages_to_ingest(
    user_id: str, thread_id: str | None, messages: list[AnyMessage]
) -> tuple[list[AnyMessage], int]:
    """Return the slice of the thread to extract from, and how much of it is context.

    Returns (messages, context_count): the first context_count entries were
    already ingested. Falls back to the whole thread when the high-water
    mark is missing or stale — a re-ingest is wasteful, losing a disclosure is not.
    """
    if not thread_id:
        return messages, 0
    if not redis_cache.client:
        return messages, 0
    raw_mark = await redis_cache.client.get(
        MEMORY_INGEST_MARK_KEY.format(user_id=user_id, thread_id=thread_id)
    )
    if raw_mark is None:
        return messages, 0
    mark = str(raw_mark)
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].id == mark:
            cut = index + 1
            if cut >= len(messages):
                return [], 0
            context_start = max(0, cut - MEMORY_DELTA_CONTEXT_MESSAGES)
            return messages[context_start:], cut - context_start
    return messages, 0


async def _mark_ingested(user_id: str, thread_id: str | None, messages: list[AnyMessage]) -> None:
    """Record the last message this thread has extracted from.

    Written only after retain returns, so a failed ingestion is retried on
    the next turn instead of being silently skipped.
    """
    if not thread_id or not messages or not messages[-1].id or not redis_cache.client:
        return
    await redis_cache.client.set(
        MEMORY_INGEST_MARK_KEY.format(user_id=user_id, thread_id=thread_id),
        messages[-1].id,
        ex=MEMORY_INGEST_MARK_TTL,
    )


async def _store_user_memory_background(
    messages: list[AnyMessage],
    user_id: str,
    session_id: str | None,
    extraction_prompt: str | None,
    subagent_id: str | None,
    user_name: str | None,
    conversation_id: str | None = None,
) -> None:
    """Background task — ingests the new part of the conversation.

    Integration-specific extraction hints (Slack, GitHub, ...) let the
    engine pull out entity IDs and preferences relevant to that integration.
    Runs in its own wide_task scope since fire-and-forget work sits outside
    any request middleware.
    """
    # wide_task already records any failure; suppress the re-raise so this
    # fire-and-forget task doesn't surface an un-retrieved-exception warning.
    with contextlib.suppress(Exception):
        async with wide_task("memory_retain", user=UserContext(id=user_id)):
            log.set(subagent_id=subagent_id or "agent", session_id=session_id)
            # A workflow/email/reminder run is GAIA driving itself. Checked
            # here, not in the node, so it never sits on the turn's critical path.
            if conversation_id and await conversation_repository.is_system_generated(
                conversation_id
            ):
                log.set(memory_ingest={"skipped": "system_generated_conversation"})
                return
            to_ingest, context_count = await _messages_to_ingest(user_id, session_id, messages)
            delta = to_ingest[context_count:]
            if delta and not _delta_worth_learning(delta):
                # Not advancing the mark keeps the trivial turn in the next
                # delta, so its content is still extracted alongside the next
                # substantive turn instead of being silently dropped.
                log.set(
                    memory_ingest={
                        "skipped": "trivial_delta",
                        "thread_messages": len(messages),
                        "delta_messages": len(delta),
                    }
                )
                return
            formatted = _format_messages_for_user_memory(to_ingest, context_count)
            if not formatted:
                return
            log.set(
                memory_ingest={
                    "thread_messages": len(messages),
                    "ingested_messages": len(to_ingest) - context_count,
                    "context_messages": context_count,
                }
            )
            await memory_engine.retain(
                user_id,
                formatted,
                source_type=MemorySourceType.CONVERSATION,
                source_id=session_id,
                extraction_hints=extraction_prompt,
                user_name=user_name,
            )
            await _mark_ingested(user_id, session_id, messages)


async def memory_node(
    state: State,
    config: RunnableConfig,
    store: BaseStore,  # noqa: ARG001 -- framework contract
) -> State:
    """End-graph hook that stores user memory from comms turns.

    Spawns a background task (non-blocking) that runs memory_engine.retain
    over the new part of the transcript with the integration-specific
    extraction prompt.
    """
    messages = state.get("messages", [])

    configurable = agent_configurable(config)
    user_id = configurable.get("user_id")
    subagent_id = configurable.get("subagent_id")
    session_id = configurable.get("thread_id")
    conversation_id = configurable.get("conversation_id")
    user_name = configurable.get("user_name")

    extraction_prompt = get_memory_extraction_prompt(subagent_id) if subagent_id else None

    should_learn, reason = _check_worth_learning(messages)
    if not should_learn:
        log.debug(f"{LogTag.AGENT} Memory learning skipped", reason=reason)
        return state

    if not user_id:
        return state

    task = spawn_background_task(
        _store_user_memory_background(
            messages=messages,
            user_id=user_id,
            session_id=session_id,
            extraction_prompt=extraction_prompt,
            subagent_id=subagent_id,
            user_name=user_name,
            conversation_id=conversation_id,
        ),
        name="user_memory",
    )
    log.debug(
        f"{LogTag.AGENT} Memory learning spawned",
        subagent_id=subagent_id,
        task_name=task.get_name(),
    )

    return state
