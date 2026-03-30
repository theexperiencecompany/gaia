"""
Stream Utilities - Shared helpers for LangGraph streaming.

This module provides reusable functions for processing LangGraph stream events,
particularly for extracting and formatting tool call data.

Used by:
- execute_graph_streaming() in agent_helpers.py (main agent)
- execute_subagent_stream() in subagent_runner.py (subagents via handoff/executor)
- call_subagent() in subagent_runner.py (direct subagent calls for testing)
- chat_service.py and comms_notifier.py (SSE chunk processing)
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from shared.py.wide_events import ChatContext, log

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
from app.models.message_models import MessageRequestWithHistory
from app.utils.agent_utils import format_tool_call_entry


async def extract_tool_entries_from_update(
    state_update: dict,
    emitted_tool_calls: set[str],
    integration_metadata: Optional[dict] = None,
) -> list[tuple[str, dict]]:
    """
    Extract tool_data entries from a LangGraph state update.

    Processes the nested structure of state updates to find tool calls
    and format them for frontend streaming. Handles deduplication via
    the emitted_tool_calls set.

    Args:
        state_update: State update dict from LangGraph 'updates' stream.
                      Expected structure: {"messages": [AIMessage with tool_calls, ...]}
        emitted_tool_calls: Set of already-emitted tool_call_ids.
                            Modified in place to track new emissions.
        integration_metadata: Optional dict with {icon_url, integration_id, name}
                              for custom MCP integrations. If provided, applied
                              to all tool entries.

    Returns:
        List of (tool_call_id, tool_entry) tuples for tool calls that haven't
        been emitted yet. Each tool_entry is ready for streaming to frontend.

    Example:
        >>> entries = await extract_tool_entries_from_update(
        ...     state_update={"messages": [ai_message_with_tools]},
        ...     emitted_tool_calls=set(),
        ...     integration_metadata={"icon_url": "...", "name": "Gmail"},
        ... )
        >>> for tc_id, entry in entries:
        ...     stream_writer({"tool_data": entry})
    """
    entries: list[tuple[str, dict]] = []

    if not isinstance(state_update, dict) or "messages" not in state_update:
        return entries

    for msg in state_update["messages"]:
        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            tc_id = tc.get("id")
            if not tc_id or tc_id in emitted_tool_calls:
                continue

            # Format tool call as tool_data entry
            tool_entry = await format_tool_call_entry(
                tc,
                icon_url=(
                    integration_metadata.get("icon_url")
                    if integration_metadata
                    else None
                ),
                integration_id=(
                    integration_metadata.get("integration_id")
                    if integration_metadata
                    else None
                ),
                integration_name=(
                    integration_metadata.get("name") if integration_metadata else None
                ),
            )

            if tool_entry:
                entries.append((tc_id, tool_entry))
                emitted_tool_calls.add(tc_id)

    return entries


def _extract_response_text(chunk: str) -> str:
    """Extract response text from a data chunk."""
    try:
        if chunk.startswith("data: "):
            chunk = chunk[6:]
        data = json.loads(chunk)
        return data.get("response", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def extract_tool_data(json_str: str) -> dict[str, Any]:
    """
    Parse and extract structured tool output from an agent's JSON response chunk.

    Converts individual tool fields (e.g., calendar_options, search_results, etc.)
    into unified ToolDataEntry array format for consistent frontend handling.

    Returns:
        Dict containing:
        - "tool_data": Array of ToolDataEntry objects (if any tool data found)
        - "other_data": Dict with non-tool fields like follow_up_actions
    """
    try:
        data = json.loads(json_str)
        timestamp = datetime.now(timezone.utc).isoformat()

        other_data: dict[str, Any] = {}
        if data.get("follow_up_actions") is not None:
            other_data["follow_up_actions"] = data["follow_up_actions"]

        tool_data_entries: list[ToolDataEntry] = []

        if "tool_data" in data:
            td = data["tool_data"]
            if isinstance(td, list):
                tool_data_entries = td
            else:
                tool_data_entries = [td]
        else:
            for field_name in tool_fields:
                if data.get(field_name) is not None:
                    tool_data_entries.append(
                        {
                            "tool_name": field_name,
                            "data": data[field_name],
                            "timestamp": timestamp,
                        }
                    )

        result: dict[str, Any] = {}

        if tool_data_entries:
            result["tool_data"] = tool_data_entries
        if other_data:
            result["other_data"] = other_data

        if "tool_output" in data:
            result["tool_output"] = data["tool_output"]

        return result

    except json.JSONDecodeError:
        return {}


async def process_data_chunk(
    stream_id: str,
    chunk: str,
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
    todo_progress_accumulated: dict[str, Any],
    follow_up_actions: list[str],
) -> tuple[list[str], bool]:
    """
    Process a 'data: ' prefixed agent chunk.

    Extracts tool data, follow-up actions, todo progress, and tool outputs,
    publishes appropriate sub-chunks to Redis, and updates stream progress.

    Returns (follow_up_actions, published) where published indicates whether
    the chunk was already sent (True) or should be sent as-is (False).
    """
    chunk_payload = chunk[6:]

    chunk_json: Optional[dict[str, Any]] = None
    try:
        chunk_json = json.loads(chunk_payload)
    except json.JSONDecodeError:
        chunk_json = None

    if chunk_json and "todo_progress" in chunk_json:
        snapshot = chunk_json["todo_progress"]
        source = snapshot.get("source", "executor")
        todo_progress_accumulated[source] = snapshot

    new_data = extract_tool_data(chunk_payload)
    if new_data:
        if "other_data" in new_data:
            other_data_dict = new_data["other_data"]
            if "follow_up_actions" in other_data_dict:
                follow_up_actions = other_data_dict["follow_up_actions"]
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'follow_up_actions': follow_up_actions})}\n\n",
                )

        if "tool_data" in new_data:
            for tool_entry in new_data["tool_data"]:
                tool_data["tool_data"].append(tool_entry)
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
                )

        if "tool_output" in new_data:
            output_data = new_data["tool_output"]
            tool_call_id = output_data.get("tool_call_id")
            output = output_data.get("output")
            if tool_call_id and output:
                tool_outputs[tool_call_id] = output
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'tool_output': output_data})}\n\n",
            )

        if chunk_json and "todo_progress" in chunk_json:
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'todo_progress': chunk_json['todo_progress']})}\n\n",
            )

        response_text = _extract_response_text(chunk)
        if response_text or new_data:
            await stream_manager.update_progress(
                stream_id,
                message_chunk=response_text,
                tool_data=new_data,
            )
        return follow_up_actions, True

    await stream_manager.publish_chunk(stream_id, chunk)
    response_text = _extract_response_text(chunk)
    if response_text:
        await stream_manager.update_progress(
            stream_id,
            message_chunk=response_text,
            tool_data=None,
        )
    return follow_up_actions, True


def set_stream_log_context(
    body: MessageRequestWithHistory,
    user_id: Optional[str],
    conversation_id: str,
    stream_id: str,
    is_new_conversation: bool,
) -> None:
    """Attach structured log context for a chat stream."""
    log.set(
        user={"id": str(user_id)} if user_id else {},
        chat=ChatContext(
            conversation_id=conversation_id,
            stream_id=stream_id,
            is_new_conversation=is_new_conversation,
            message_count=len(body.messages) if body.messages else 0,
            has_files=bool(body.fileIds or body.fileData),
            file_count=len(body.fileIds or []) + len(body.fileData or []),
            tool_category=body.toolCategory or "",
            has_reply=bool(body.replyToMessage),
            has_calendar_event=bool(body.selectedCalendarEvent),
            selected_workflow_id=body.selectedWorkflow.id
            if body.selectedWorkflow
            else "",
        ),
        user_message_length=len(body.messages[-1]["content"]) if body.messages else 0,
        selected_tool=body.selectedTool,
    )


def aggregate_usage_metadata(usage_metadata: dict[str, Any]) -> tuple[int, int]:
    """Sum input and output tokens across all model entries in usage metadata."""
    total_input = sum(
        v.get("input_tokens", 0) for v in usage_metadata.values() if isinstance(v, dict)
    )
    total_output = sum(
        v.get("output_tokens", 0)
        for v in usage_metadata.values()
        if isinstance(v, dict)
    )
    return total_input, total_output


def merge_tool_outputs(
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
) -> None:
    """Merge captured tool outputs into the tool_data entries before saving."""
    for entry in tool_data.get("tool_data", []):
        if entry.get("tool_name") == "tool_calls_data":
            data = entry.get("data", {})
            if isinstance(data, dict):
                tool_call_id = data.get("tool_call_id")
                if tool_call_id and tool_call_id in tool_outputs:
                    data["output"] = tool_outputs[tool_call_id]


def inject_todo_progress(
    tool_data: dict[str, Any],
    todo_progress_accumulated: dict[str, Any],
) -> None:
    """Inject accumulated todo_progress snapshots as a single tool_data entry."""
    if todo_progress_accumulated:
        tool_data["tool_data"].append(
            {
                "tool_name": "todo_progress",
                "data": todo_progress_accumulated,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


async def recover_stream_state(
    stream_id: str,
    complete_message: str,
    tool_data: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """
    Recover complete_message and tool_data from Redis progress when the nostream
    marker was never delivered (e.g. on cancellation).
    """
    if complete_message:
        return complete_message, tool_data

    progress = await stream_manager.get_progress(stream_id)
    if not progress:
        return complete_message, tool_data

    complete_message = progress.get("complete_message", "")
    progress_tool_data = progress.get("tool_data")
    if (
        isinstance(progress_tool_data, dict)
        and progress_tool_data.get("tool_data")
        and not tool_data.get("tool_data")
    ):
        tool_data = progress_tool_data
    log.debug(f"Recovered {len(complete_message)} chars from Redis progress")
    return complete_message, tool_data


async def publish_description_if_ready(
    stream_id: str,
    description_task: Optional[asyncio.Task],
) -> Optional[asyncio.Task]:
    """Publish conversation description chunk if the task has completed. Returns None to clear it."""
    if not description_task or not description_task.done():
        return description_task
    try:
        description = description_task.result()
        await stream_manager.publish_chunk(
            stream_id,
            f"""data: {json.dumps({"conversation_description": description})}\n\n""",
        )
    except Exception as e:
        log.error(f"Failed to get conversation description: {e}")
    return None  # Clear to prevent duplicate sends
