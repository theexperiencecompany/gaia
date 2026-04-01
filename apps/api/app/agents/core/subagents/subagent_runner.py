"""
Subagent Execution Core — shared logic for subagent invocation.

Used by handoff_tools.py, executor_tool.py, and call_subagent (direct testing).

Exports:
- SubagentExecutionContext  — data container for a prepared subagent run
- build_initial_messages    — construct the standard [system, context, human] list
- prepare_subagent_execution — prepare a provider subagent context
- prepare_executor_execution — prepare the executor agent context
- execute_subagent_stream   — stream a subagent graph, return final message string
- call_subagent             — stream a subagent as SSE (direct/testing path)
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.agents.core.subagents.subagent_helpers import (
    check_subagent_integration,
    create_agent_context_message,
    create_subagent_system_message,
    get_subagent_by_id,
)
from app.agents.core.subagents.token_budget import (
    SubagentTokenLimitError,
    get_token_limit_summary,
    inject_token_budget,
)
from app.config.oauth_config import get_subagent_integrations
from app.constants.llm import SUBAGENT_MAX_TOKENS
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config
from app.models.models_models import ModelConfig
from app.utils.stream_utils import extract_tool_entries_from_update
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from shared.py.wide_events import log


@dataclass
class SubagentExecutionContext:
    """All data needed to execute a subagent."""

    subagent_graph: Any
    agent_name: str
    config: dict
    configurable: dict
    integration_id: str
    initial_state: dict
    user_id: str | None = None
    stream_id: str | None = None


async def build_initial_messages(
    system_message: SystemMessage,
    agent_name: str,
    configurable: dict,
    task: str,
    user_id: str | None = None,
    subagent_id: str | None = None,
    retrieval_query: str | None = None,
) -> list:
    """Build [system, context, human] message list for a subagent/executor run.

    Args:
        retrieval_query: Query for memory/skill retrieval. Defaults to ``task``.
                         Pass the original task when ``task`` has been enhanced
                         with hints that would pollute semantic search.
    """
    context_message = await create_agent_context_message(
        configurable=configurable,
        user_id=user_id,
        query=retrieval_query if retrieval_query is not None else task,
        subagent_id=subagent_id,
    )
    return [
        system_message,
        context_message,
        HumanMessage(content=task, additional_kwargs={"visible_to": {agent_name}}),
    ]


async def prepare_subagent_execution(
    subagent_id: str,
    task: str,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    base_configurable: dict | None = None,
    user_model_config: Optional[ModelConfig] = None,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare a SubagentExecutionContext for a provider subagent.

    Returns ``(ctx, None)`` on success or ``(None, error_message)`` on failure.
    """
    user_id = user.get("user_id")
    clean_id = subagent_id.replace("subagent:", "").strip()

    integration = get_subagent_by_id(clean_id)
    if not integration or not integration.subagent_config:
        available = [i.id for i in get_subagent_integrations()][:5]
        suffix = "..." if len(available) == 5 else ""
        return None, (
            f"Subagent '{subagent_id}' not found. "
            f"Available: {', '.join(available)}{suffix}"
        )

    agent_name = integration.subagent_config.agent_name
    log.set(subagent={"name": agent_name, "provider": integration.provider, "task_length": len(task)})

    subagent_graph = await providers.aget(agent_name)
    if not subagent_graph:
        return None, f"Subagent {agent_name} not available"

    config = build_agent_config(
        conversation_id=conversation_id,
        user=user,
        user_time=user_time,
        thread_id=f"{integration.id}_{conversation_id}",
        base_configurable=base_configurable,
        agent_name=agent_name,
        user_model_config=user_model_config,
        subagent_id=agent_name,
    )
    configurable = config.get("configurable", {})

    system_message = await create_subagent_system_message(
        integration_id=integration.id,
        agent_name=agent_name,
        user_id=user_id,
    )
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name=agent_name,
        configurable=configurable,
        task=task,
        user_id=user_id,
        subagent_id=agent_name,
    )

    return SubagentExecutionContext(
        subagent_graph=subagent_graph,
        agent_name=agent_name,
        config=config,
        configurable=configurable,
        integration_id=integration.id,
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None


async def prepare_executor_execution(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare a SubagentExecutionContext for the executor agent.

    Returns ``(ctx, None)`` on success or ``(None, error_message)`` on failure.
    """
    # Lazy imports to avoid circular dependency
    from app.agents.core.graph_manager import GraphManager
    from app.helpers.message_helpers import create_system_message

    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    executor_graph = await GraphManager.get_graph("executor_agent")
    if not executor_graph:
        return None, "Executor agent not available"

    user = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }
    config = build_agent_config(
        conversation_id=thread_id,
        user=user,
        user_time=user_time,
        thread_id=f"executor_{thread_id}",
        base_configurable=configurable,
        agent_name="executor_agent",
        subagent_id="executor_agent",
        vfs_session_id=configurable.get("vfs_session_id") or thread_id,
    )
    new_configurable = config.get("configurable", {})

    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # Inject a direct handoff hint when we already know which subagent to use,
    # letting the executor skip the retrieve_tools discovery round-trip.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    if tool_category and selected_tool and get_subagent_by_id(tool_category):
        enhanced_task = (
            f"{task}\n\n"
            f"DIRECT EXECUTION HINT: The tool '{selected_tool}' belongs to the "
            f"'{tool_category}' subagent. Skip retrieve_tools discovery and directly "
            f'call handoff(subagent_id="{tool_category}", task="{task}").'
        )

    # Use original task as retrieval_query so the hint doesn't pollute memory search.
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        configurable=new_configurable,
        task=enhanced_task,
        user_id=user_id,
        retrieval_query=task,
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id="executor",
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

@dataclass
class _StreamEvent:
    """Typed event emitted by _iter_subagent_events."""
    kind: str  # "content" | "tool_data" | "tool_output" | "custom"
    data: Any
    tool_call_id: str | None = field(default=None)


async def _iter_subagent_events(
    ctx: SubagentExecutionContext,
    config: dict,
    emitted_tool_calls: set[str],
    integration_metadata: dict | None = None,
) -> AsyncGenerator[_StreamEvent, None]:
    """Yield typed events from the subagent graph stream.

    Handles cancellation checks and normalises the three LangGraph stream
    modes (updates / messages / custom) into a single flat event stream.
    """
    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=config,
    ):
        if ctx.stream_id and await stream_manager.is_cancelled(ctx.stream_id):
            log.info("Subagent stream cancelled", stream_id=ctx.stream_id)
            break

        if len(event) != 2:
            continue
        mode, payload = event

        if mode == "updates":
            for _, state_update in payload.items():
                for _, tool_entry in await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                    integration_metadata=integration_metadata,
                ):
                    yield _StreamEvent("tool_data", tool_entry)

        elif mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue
            if isinstance(chunk, AIMessageChunk):
                content = chunk.text
                if content:
                    yield _StreamEvent("content", content)
            elif isinstance(chunk, ToolMessage):
                output = (
                    chunk.content[:3000]
                    if isinstance(chunk.content, str)
                    else str(chunk.content)[:3000]
                )
                yield _StreamEvent("tool_output", output, tool_call_id=chunk.tool_call_id)

        elif mode == "custom":
            yield _StreamEvent("custom", payload)


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer: Any = None,
    integration_metadata: dict | None = None,
    max_tokens: int = SUBAGENT_MAX_TOKENS,
) -> str:
    """Execute a subagent graph with streaming. Returns the complete message string.

    - tool_data and tool_output are forwarded to ``stream_writer`` if provided.
    - Content is accumulated and returned.
    - If the token budget is exceeded, a final summary LLM call is made.
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    complete_message = ""
    emitted_tool_calls: set[str] = set()
    token_limit_hit = False

    config, budget_cb = inject_token_budget(ctx.config, max_tokens)

    try:
        async for ev in _iter_subagent_events(ctx, config, emitted_tool_calls, integration_metadata):
            if ev.kind == "content":
                complete_message += ev.data
            elif ev.kind == "tool_data" and stream_writer:
                stream_writer({"tool_data": ev.data})
            elif ev.kind == "tool_output" and stream_writer:
                stream_writer({"tool_output": {"tool_call_id": ev.tool_call_id, "output": ev.data}})
            elif ev.kind == "custom" and stream_writer:
                stream_writer(ev.data)
    except SubagentTokenLimitError as e:
        token_limit_hit = True
        complete_message = await get_token_limit_summary(
            graph=ctx.subagent_graph,
            config=config,
            initial_state=ctx.initial_state,
            tokens_used=e.tokens_used,
            limit=e.limit,
        )

    final_message = complete_message or "Task completed"
    log.set(subagent={
        "name": ctx.agent_name,
        "provider": ctx.integration_id,
        "response_length": len(final_message),
        "messages_count": len(ctx.initial_state.get("messages", [])),
        "total_tokens": budget_cb.total_tokens,
        "token_limit_hit": token_limit_hit,
    })
    return final_message


async def call_subagent(
    subagent_id: str,
    query: str,
    user: dict,
    conversation_id: str,
    user_time: datetime,
    skip_integration_check: bool = True,
    user_model_config: Optional[ModelConfig] = None,
    stream_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Directly invoke a subagent with SSE streaming (testing / direct-call path).

    Yields SSE-formatted strings compatible with chat_service streaming.
    """
    user_id = user.get("user_id")

    if not skip_integration_check and user_id:
        integration = get_subagent_by_id(subagent_id.replace("subagent:", "").strip())
        if integration:
            error = await check_subagent_integration(integration.id, user_id)
            if error:
                yield f"data: {json.dumps({'error': error})}\n\n"
                yield "data: [DONE]\n\n"
                return

    ctx, error = await prepare_subagent_execution(
        subagent_id=subagent_id,
        task=query,
        user=user,
        user_time=user_time,
        conversation_id=conversation_id,
        user_model_config=user_model_config,
        stream_id=stream_id,
    )
    if error or ctx is None:
        log.error(error or "Failed to prepare subagent execution")
        yield f"data: {json.dumps({'error': error or 'Failed to prepare subagent execution'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    log.info(f"[DIRECT] Invoking subagent '{ctx.agent_name}' — query: {query[:80]}...")

    complete_message = ""
    emitted_tool_calls: set[str] = set()
    token_limit_hit = False
    config, budget_cb = inject_token_budget(ctx.config, SUBAGENT_MAX_TOKENS)

    try:
        async for ev in _iter_subagent_events(ctx, config, emitted_tool_calls):
            if ev.kind == "content":
                complete_message += ev.data
                yield f"data: {json.dumps({'response': ev.data})}\n\n"
            elif ev.kind == "tool_data":
                yield f"data: {json.dumps({'tool_data': ev.data})}\n\n"
            elif ev.kind == "tool_output":
                yield f"data: {json.dumps({'tool_output': {'tool_call_id': ev.tool_call_id, 'output': ev.data}})}\n\n"
            elif ev.kind == "custom":
                yield f"data: {json.dumps(ev.data)}\n\n"
    except SubagentTokenLimitError as e:
        token_limit_hit = True
        complete_message = await get_token_limit_summary(
            graph=ctx.subagent_graph,
            config=config,
            initial_state=ctx.initial_state,
            tokens_used=e.tokens_used,
            limit=e.limit,
        )
        yield f"data: {json.dumps({'response': complete_message})}\n\n"

    yield f"nostream: {json.dumps({'complete_message': complete_message})}"
    yield "data: [DONE]\n\n"

    log.set(subagent={
        "name": ctx.agent_name,
        "provider": ctx.integration_id,
        "response_length": len(complete_message),
        "total_tokens": budget_cb.total_tokens,
        "token_limit_hit": token_limit_hit,
    })
    log.info(f"[DIRECT] Subagent '{ctx.agent_name}' completed — {len(complete_message)} chars")
