"""
Subagent Execution Core - Shared logic for subagent invocation.

This module contains the reusable classes and functions for invoking subagents.
Both handoff_tools.py, executor_tool.py, and direct call_subagent use these.

Keeping shared code here avoids cyclic dependencies since handoff_tools.py
imports from this file, not the other way around.

Key exports:
- SubagentExecutionContext: Container for execution data
- build_initial_messages(): Construct standard message list with context
- execute_subagent_stream(): Unified streaming with configurable tool tracking
- prepare_subagent_execution(): Prepare context for platform subagents
- prepare_executor_execution(): Prepare context for executor agent
"""

from collections.abc import AsyncGenerator
from datetime import datetime
import json
import uuid

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.core.graph_manager import GraphManager
from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.core.subagents.subagent_helpers import (
    create_agent_context_message,
    create_subagent_system_message,
)
from app.constants.general import FINISH_TASK_NAME
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import (
    build_current_time_message,
    create_system_message,
)
from app.models.models_models import ModelConfig
from app.services.oauth.oauth_service import check_integration_status
from app.utils.stream_utils import extract_tool_entries_from_update
from shared.py.wide_events import log


def _capture_finish_task_content(chunk: ToolMessage, current_message: str) -> str:
    """Return the finish_task chunk's textual content if applicable.

    `finish_task` (when used by a subagent) carries the final answer in its
    return value. Capture it as the complete message so the parent handoff
    returns the actual content rather than the literal "Task completed"
    fallback. Subagents with include_finish_task=False terminate via a
    normal AIMessage and never enter this branch.
    """
    if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
        return chunk.content
    return current_message


class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    def __init__(
        self,
        subagent_graph,
        agent_name: str,
        config: dict,
        configurable: dict,
        integration_id: str,
        initial_state: dict,
        user_id: str | None = None,
        stream_id: str | None = None,
    ):
        self.subagent_graph = subagent_graph
        self.agent_name = agent_name
        self.config = config
        self.configurable = configurable
        self.integration_id = integration_id
        self.initial_state = initial_state
        self.user_id = user_id
        self.stream_id = stream_id


async def build_initial_messages(
    system_message: SystemMessage,
    agent_name: str,
    configurable: dict,
    task: str,
    user_id: str | None = None,
    subagent_id: str | None = None,
    retrieval_query: str | None = None,
    integration_id: str | None = None,
    memories_text: str | None = None,
    skills_text: str | None = None,
) -> list:
    """Build the [static_prompt, dynamic_context, human_task] triplet.

    The static system prompt is byte-identical across users/channels. The
    dynamic-context message carries user_name, memories, skills, platform
    restrictions, and (for provider subagents) service-specific username
    metadata. ``manage_system_prompts_node`` collapses repeats at run time.

    Args:
        system_message: Pre-built STATIC system message (must not include
            any per-user or per-time content — keeps the cache prefix stable).
        agent_name: Name of the agent (for HumanMessage visibility metadata).
        configurable: Config dict with user_time, user_name, etc.
        task: The task/query to execute (goes into the HumanMessage).
        user_id: Optional user ID for memory retrieval.
        subagent_id: Optional subagent ID for skill retrieval.
        retrieval_query: Query for memory/context retrieval. Defaults to
            ``task`` but should be set to the original unenhanced task when
            ``task`` contains injected hints that would pollute semantic
            search.
        integration_id: When invoking a provider subagent, the underlying
            integration ID — used to fetch provider metadata (GitHub login,
            Gmail address, etc.) for the dynamic-context message.
        memories_text: Pre-fetched memories section. The parent can fetch in
            parallel with its own work and pass it down here to avoid the
            subagent running a duplicate ChromaDB lookup.
        skills_text: Pre-fetched skills section; same rationale.
    """
    log.set(agent_prep={"agent_name": agent_name, "task_length": len(task)})

    context_message = await create_agent_context_message(
        configurable=configurable,
        user_id=user_id,
        query=retrieval_query if retrieval_query is not None else task,
        subagent_id=subagent_id,
        integration_id=integration_id,
        memories_text=memories_text,
        skills_text=skills_text,
    )

    # Current time rides in a HumanMessage so the system_instruction prefix
    # stays stable — minute ticks would otherwise reset the cache boundary
    # at whatever byte position the timestamp occupies.
    time_message = build_current_time_message(
        user_timezone=configurable.get("user_timezone"),
    )

    return [
        system_message,
        context_message,
        time_message,
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
    ]


async def prepare_subagent_execution(
    subagent_id: str,
    task: str,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    base_configurable: dict | None = None,
    user_model_config: ModelConfig | None = None,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """
    Prepare everything needed to execute a subagent.

    This is the shared setup logic used by both handoff tool and call_subagent.

    Args:
        subagent_id: The subagent ID (e.g., "googlecalendar", "gmail")
        task: The task/query to execute
        user: User dict with user_id, email, name
        user_time: User's local time
        conversation_id: Thread/conversation ID
        base_configurable: Optional configurable to inherit from (for handoff tool)
        user_model_config: Optional model configuration for LLM settings

    Returns:
        Tuple of (SubagentExecutionContext, None) on success, or
        (None, error_message) on failure
    """
    user_id = user.get("user_id")
    clean_id = subagent_id.replace("subagent:", "").strip()

    # Resolve subagent
    subagent = get_subagent_by_id(clean_id)
    if not subagent:
        available = [s.id for s in all_subagents()][:5]
        return None, (
            f"Subagent '{subagent_id}' not found. "
            f"Available: {', '.join(available)}{'...' if len(available) == 5 else ''}"
        )

    agent_name = subagent.config.agent_name
    log.set(
        subagent={
            "name": agent_name,
            "provider": subagent.provider,
            "task_length": len(task),
        }
    )

    # Load subagent graph
    subagent_graph = await providers.aget(agent_name)
    if not subagent_graph:
        return None, f"Subagent {agent_name} not available"

    # Build thread ID and config
    subagent_thread_id = f"{subagent.id}_{conversation_id}"
    config = build_agent_config(
        conversation_id=conversation_id,
        user=user,
        user_time=user_time,
        thread_id=subagent_thread_id,
        base_configurable=base_configurable,
        agent_name=agent_name,
        user_model_config=user_model_config,
        subagent_id=agent_name,
    )
    configurable = config.get("configurable", {})

    # Create messages using shared helper
    system_message = await create_subagent_system_message(
        integration_id=subagent.id,
        agent_name=agent_name,
        user_id=user_id,
    )

    # Pass provider metadata (usernames/emails) into the DYNAMIC context
    # message so the STATIC subagent prompt stays byte-identical across users.
    # Handoff payload can pre-fetch memories/skills at the executor level and
    # forward them here via base_configurable["__pinned_memories__" /
    # "__pinned_skills__"] to avoid a duplicate ChromaDB round-trip.
    pinned_memories = (base_configurable or {}).get("__pinned_memories__")
    pinned_skills = (base_configurable or {}).get("__pinned_skills__")

    messages = await build_initial_messages(
        system_message=system_message,
        agent_name=agent_name,
        configurable=configurable,
        task=task,
        user_id=user_id,
        subagent_id=agent_name,
        integration_id=subagent.id,
        memories_text=pinned_memories,
        skills_text=pinned_skills,
    )

    initial_state = {"messages": messages, "todos": []}

    log.set(
        subagent_prep={
            "agent_name": agent_name,
            "integration_id": subagent.id,
            "thread_id": subagent_thread_id,
            "had_pinned_memories": pinned_memories is not None,
            "had_pinned_skills": pinned_skills is not None,
        }
    )

    return SubagentExecutionContext(
        subagent_graph=subagent_graph,
        agent_name=agent_name,
        config=config,
        configurable=configurable,
        integration_id=subagent.id,
        initial_state=initial_state,
        user_id=user_id,
        stream_id=stream_id,
    ), None


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer=None,
    integration_metadata: dict | None = None,
) -> str:
    """
    Execute subagent with streaming and tool tracking.

    Args:
        ctx: SubagentExecutionContext from prepare_subagent_execution
        stream_writer: Callback for custom events (from get_stream_writer())
        integration_metadata: Optional dict with {icon_url, integration_id, name}
                              for custom MCP icon display

    Returns:
        Complete message string

    Stream Event Flow:
        1. "updates" - Emit tool_data with complete args when tool is called
        2. "messages" - Stream content, emit tool_output when ToolMessage arrives
        3. "custom" - Forward custom events (progress messages, etc.) to parent
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    complete_message = ""
    finish_task_result: str | None = None
    emitted_tool_calls: set[str] = set()

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=ctx.config,
    ):
        # Check for cancellation
        if ctx.stream_id and await stream_manager.is_cancelled(ctx.stream_id):
            log.info(f"Subagent stream {ctx.stream_id} cancelled by user")
            break

        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        stream_mode, payload = event

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                    integration_metadata=integration_metadata,
                )
                for tc_id, tool_entry in entries:
                    if stream_writer:
                        stream_writer({"tool_data": tool_entry})
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Accumulate AI response content
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                content_str = (
                    chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                )
                complete_message = _capture_finish_task_content(chunk, complete_message)
                if stream_writer:
                    stream_writer(
                        {
                            "tool_output": {
                                "tool_call_id": chunk.tool_call_id,
                                "output": content_str[:3000],
                            }
                        }
                    )
            continue

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(payload)

    final_message = (
        finish_task_result
        if finish_task_result is not None
        else complete_message
        if complete_message
        else "Task completed"
    )
    log.set(
        subagent={
            "name": ctx.agent_name,
            "provider": ctx.integration_id,
            "response_length": len(final_message),
            "messages_count": len(ctx.initial_state.get("messages", [])),
        }
    )
    return final_message


async def prepare_executor_execution(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """
    Prepare execution context for the executor agent.

    Similar to prepare_subagent_execution but:
    - Uses GraphManager for graph resolution (not providers)
    - Uses create_system_message for executor-specific prompts
    - Injects direct handoff hints when selected_tool/tool_category is known

    Args:
        task: The task/query to execute
        configurable: Config dict from RunnableConfig (with user_id, user_time, etc.)
        user_time: User's local time

    Returns:
        Tuple of (SubagentExecutionContext, None) on success, or
        (None, error_message) on failure
    """
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    # Fresh executor thread per call_executor invocation. Architecturally the
    # comms agent owns the conversation thread; the executor is a subroutine
    # invoked with a task description + the last user message. Giving it its
    # own ephemeral thread keeps its context small and prevents stale tool
    # observations from one task bleeding into the next. If a later user turn
    # needs prior context, comms passes it explicitly in the new task
    # description.
    call_scope = uuid.uuid4().hex[:12]
    executor_thread_id = f"executor_{thread_id}_{call_scope}"

    # VFS session stays pinned to the PARENT conversation thread so files
    # written by one executor call are visible to the next — the ephemeral
    # thread only scopes agent reasoning, not persisted artefacts.
    vfs_session_id = configurable.get("vfs_session_id") or thread_id

    # Load executor graph
    executor_graph = await GraphManager.get_graph("executor_agent")
    if not executor_graph:
        return None, "Executor agent not available"

    # Build user dict for config
    user = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    # Build config
    config = build_agent_config(
        conversation_id=thread_id,
        user=user,
        user_time=user_time,
        thread_id=executor_thread_id,
        base_configurable=configurable,
        agent_name="executor_agent",
        subagent_id="executor_agent",  # Use agent_name as agent_id in mem0
        vfs_session_id=vfs_session_id,
    )
    new_configurable = config.get("configurable", {})

    # Create system message (executor-specific)
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # When comms provides a known tool_category, hint the executor to go
    # straight to handoff(subagent_id=...) and skip the ChromaDB discovery
    # call. We do NOT pre-bind tools — the target subagent still does its own
    # retrieval. This only removes one redundant round-trip where comms
    # already knows the category.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    if tool_category and get_subagent_by_id(tool_category):
        tool_hint = f"the '{selected_tool}' tool" if selected_tool else "the user's request"
        enhanced_task = (
            f"{task}\n\n"
            f"DIRECT EXECUTION HINT: This request should be handled by "
            f"'{tool_category}'. Skip retrieve_tools discovery and directly "
            f'call handoff(subagent_id="{tool_category}", task="{task}") to '
            f"route {tool_hint}."
        )
        log.set(
            executor_prep={
                "direct_hint_applied": True,
                "tool_category": tool_category,
                "selected_tool": selected_tool,
            }
        )

    # Build messages using shared helper.
    # Pass original task as retrieval_query so memory/context semantic search
    # is not polluted by the DIRECT EXECUTION HINT injected into enhanced_task.
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


async def check_subagent_integration(
    integration_id: str,
    user_id: str,
) -> str | None:
    """
    Check if integration is connected. Returns error message if not connected.

    This is a simpler version that doesn't use stream_writer (for direct calls).
    """
    try:
        is_connected = await check_integration_status(integration_id, user_id)
        if is_connected:
            return None
        return f"Integration {integration_id} is not connected. Please connect it first."
    except Exception as e:
        log.warning(f"Integration check failed: {e}")
        return None


async def call_subagent(
    subagent_id: str,
    query: str,
    user: dict,
    conversation_id: str,
    user_time: datetime,
    skip_integration_check: bool = True,
    user_model_config: ModelConfig | None = None,
    stream_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Directly invoke a subagent with streaming - drop-in for call_agent in chat_service.

    Primarily used for testing subagents directly without going through the main agent.

    Args:
        subagent_id: e.g., "googlecalendar", "gmail", "github"
        query: The user's message/query
        user: User dict with user_id, email, name
        conversation_id: Conversation thread ID
        user_time: User's local time
        skip_integration_check: Skip OAuth check (default True for testing)
        user_model_config: Optional model configuration

    Yields:
        SSE-formatted strings compatible with chat_service streaming

    Usage:
        async for chunk in call_subagent(
            subagent_id="googlecalendar",
            query="What's on my calendar today?",
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
        ):
            yield chunk
    """
    user_id = user.get("user_id")

    # Optional integration check (before prepare to fail fast)
    if not skip_integration_check and user_id:
        clean_id = subagent_id.replace("subagent:", "").strip()
        subagent = get_subagent_by_id(clean_id)
        if subagent:
            error_message = await check_subagent_integration(subagent.id, user_id)
            if error_message:
                yield f"data: {json.dumps({'error': error_message})}\n\n"
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

    log.info(f"[DIRECT] Invoking subagent '{ctx.agent_name}' with query: {query[:80]}...")

    complete_message = ""
    finish_task_result: str | None = None
    emitted_tool_calls: set[str] = set()

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=ctx.config,
    ):
        # Check for cancellation
        if stream_id and await stream_manager.is_cancelled(stream_id):
            log.info(f"Subagent stream {stream_id} cancelled by user")
            break
        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        stream_mode, payload = event

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                )
                for tc_id, tool_entry in entries:
                    yield f"data: {json.dumps({'tool_data': tool_entry})}\n\n"
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Stream AI response content
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content
                    yield f"data: {json.dumps({'response': content})}\n\n"

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                content_str = (
                    chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                )
                complete_message = _capture_finish_task_content(chunk, complete_message)
                if chunk.name == FINISH_TASK_NAME:
                    yield f"data: {json.dumps({'response': content_str})}\n\n"
                yield f"data: {json.dumps({'tool_output': {'tool_call_id': chunk.tool_call_id, 'output': content_str[:3000]}})}\n\n"
            continue

        if stream_mode == "custom":
            yield f"data: {json.dumps(payload)}\n\n"

    final_message = finish_task_result if finish_task_result is not None else complete_message
    # Final message for DB storage
    yield f"nostream: {json.dumps({'complete_message': final_message})}"
    yield "data: [DONE]\n\n"

    log.set(
        subagent={
            "name": ctx.agent_name,
            "provider": ctx.integration_id,
            "response_length": len(final_message),
        }
    )
    log.info(
        f"[DIRECT] Subagent '{ctx.agent_name}' completed. Response: {len(final_message)} chars"
    )
