"""SSE chunk parsing and dispatch for the chat stream.

The agent emits two flavors of chunk: plain ``data: {...}`` SSE frames (forwarded
to the client) and ``nostream: {...}`` markers (consumed by the orchestrator and
never sent on). :func:`process_data_chunk` is the per-chunk side-effecting
dispatcher; :func:`extract_tool_data`, :func:`normalize_custom_event`, and
:func:`extract_response_text` are pure parsers reused by the dispatcher, the
LangGraph stream processor in ``stream_utils``, and the legacy
``call_agent_silent`` path in ``agent_utils``.
"""

from datetime import UTC, datetime
import json
from typing import Any

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
from app.models.stream_events import TodoProgressFrame
from app.utils.stream_publishers import (
    accumulate_todo_progress,
    publish_other_data,
    publish_tool_data,
    publish_tool_output,
)


async def process_data_chunk(
    stream_id: str,
    chunk: str,
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
    todo_progress_accumulated: dict[str, Any],
    follow_up_actions: list[str],
    *,
    forward_subagents: bool = False,
) -> tuple[list[str], bool]:
    """Process a ``data:``-prefixed agent chunk.

    Extracts tool data, follow-up actions, todo progress, and tool outputs,
    publishes appropriate sub-chunks to Redis, and updates stream progress.

    When ``forward_subagents`` is set, ``subagent_start``/``subagent_end`` markers
    are forwarded to the client and accumulated into ``tool_data`` for later
    grouping by :func:`app.utils.stream_utils.reconstruct_subagent_groups`.

    Returns ``(follow_up_actions, published)`` where ``published`` indicates
    whether the chunk was already sent (``True``) or should be sent as-is
    (``False``).
    """
    chunk_payload = chunk[6:]

    chunk_json = _parse_chunk_json(chunk_payload)
    if forward_subagents and chunk_json:
        await _forward_subagent_lifecycle(stream_id, chunk_json, tool_data)
    accumulate_todo_progress(chunk_json, todo_progress_accumulated)

    new_data = extract_tool_data(chunk_payload)
    if not new_data:
        # No tool data — pass through as-is.
        await stream_manager.publish_chunk(stream_id, chunk)
        response_text = extract_response_text(chunk)
        if response_text:
            await stream_manager.update_progress(
                stream_id,
                message_chunk=response_text,
                tool_data=None,
            )
        return follow_up_actions, True

    follow_up_actions = await publish_other_data(stream_id, new_data, follow_up_actions)
    await publish_tool_data(stream_id, new_data, tool_data)
    await publish_tool_output(stream_id, new_data, tool_outputs)

    if chunk_json and "todo_progress" in chunk_json:
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps(TodoProgressFrame(todo_progress=chunk_json['todo_progress']).model_dump())}\n\n",
        )

    response_text = extract_response_text(chunk)
    await stream_manager.update_progress(
        stream_id,
        message_chunk=response_text,
        tool_data=new_data,
    )
    return follow_up_actions, True


async def _forward_subagent_lifecycle(
    stream_id: str, chunk_json: dict[str, Any], tool_data: dict[str, Any]
) -> None:
    """Forward subagent start/end events to the client and accumulate them."""
    if "subagent_start" in chunk_json:
        start = chunk_json["subagent_start"]
        tool_data.setdefault("subagent_starts", {})[start["subagent_id"]] = start
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_start': start})}\n\n",
        )
    if "subagent_end" in chunk_json:
        end = chunk_json["subagent_end"]
        tool_data.setdefault("subagent_ends", {})[end["subagent_id"]] = end
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_end': end})}\n\n",
        )


def _parse_chunk_json(chunk_payload: str) -> dict[str, Any] | None:
    """Parse a chunk payload as JSON, returning ``None`` on malformed input."""
    try:
        return json.loads(chunk_payload)
    except json.JSONDecodeError:
        return None


def extract_response_text(chunk: str) -> str:
    """Extract the ``response`` field from a ``data:`` chunk, or empty string."""
    try:
        chunk = chunk.removeprefix("data: ")
        data = json.loads(chunk)
        return data.get("response", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def normalize_custom_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize any tool payload dict into the unified tool_data format.

    Hooks emit raw field payloads like {"email_compose_data": [...]} via
    get_stream_writer(). This is the single conversion point used by the executor
    streaming path (subagent_runner), the comms loop (extract_tool_data below),
    and the background collector (executor_capture).

    - Already-normalized payloads (has "tool_data" key) pass through unchanged.
    - Recognized tool fields are wrapped as {"tool_data": {"tool_name": ..., "data": ..., "timestamp": ...}}.
      Multiple matching fields produce a list under "tool_data".
    - Non-tool payloads (progress, subagent_start, etc.) pass through unchanged.
    """
    if "tool_data" in payload:
        return payload

    timestamp = datetime.now(UTC).isoformat()
    entries: list[ToolDataEntry] = []
    for field_name in tool_fields:
        if payload.get(field_name) is not None:
            entries.append(
                {
                    "tool_name": field_name,
                    "data": payload[field_name],
                    "timestamp": timestamp,
                }
            )

    if not entries:
        return payload  # Non-tool event — pass through

    # Preserve non-tool keys (e.g. nextPageToken alongside email_fetch_data)
    other_keys = {k: v for k, v in payload.items() if k not in tool_fields}
    tool_data_value: Any = entries[0] if len(entries) == 1 else entries
    return {**other_keys, "tool_data": tool_data_value}


def extract_tool_data(json_str: str) -> dict[str, Any]:
    """Parse and extract structured tool output from an agent JSON chunk.

    Converts individual tool fields (e.g. ``calendar_options``, ``search_results``)
    into the unified ``ToolDataEntry`` array format the frontend consumes, using
    :func:`normalize_custom_event` so the tool-field registry lives in one place.

    Returns a dict that may contain:
      - ``tool_data``: list of ``ToolDataEntry`` objects (if any tool data found)
      - ``other_data``: non-tool fields like ``follow_up_actions``
      - ``tool_output``: a single ``tool_output`` event to be merged before save

    Malformed JSON or no recognized tool keys yields an empty dict.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return {}

    other_data: dict[str, Any] = {}
    if data.get("follow_up_actions") is not None:
        other_data["follow_up_actions"] = data["follow_up_actions"]

    normalized = normalize_custom_event(data)
    tool_data_entries: list[ToolDataEntry] = []
    if "tool_data" in normalized:
        td = normalized["tool_data"]
        tool_data_entries = td if isinstance(td, list) else [td]

    result: dict[str, Any] = {}
    if tool_data_entries:
        result["tool_data"] = tool_data_entries
    if other_data:
        result["other_data"] = other_data
    if "tool_output" in data:
        result["tool_output"] = data["tool_output"]
    return result
