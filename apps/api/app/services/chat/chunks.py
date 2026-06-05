"""SSE chunk parsing and dispatch for the chat stream.

The agent emits two flavors of chunk: plain ``data: {...}`` SSE frames (forwarded
to the client) and ``nostream: {...}`` markers (consumed by the orchestrator and
never sent on). :func:`process_data_chunk` is the per-chunk side-effecting
dispatcher; :func:`extract_tool_data` and :func:`extract_response_text` are pure
parsers reused by both the dispatcher and the legacy ``call_agent_silent`` path
in ``agent_utils``.
"""

from datetime import UTC, datetime
import json
from typing import Any

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
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
) -> tuple[list[str], bool]:
    """Process a ``data:``-prefixed agent chunk.

    Extracts tool data, follow-up actions, todo progress, and tool outputs,
    publishes appropriate sub-chunks to Redis, and updates stream progress.

    Returns ``(follow_up_actions, published)`` where ``published`` indicates
    whether the chunk was already sent (``True``) or should be sent as-is
    (``False``).
    """
    chunk_payload = chunk[6:]

    chunk_json = _parse_chunk_json(chunk_payload)
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
            f"data: {json.dumps({'todo_progress': chunk_json['todo_progress']})}\n\n",
        )

    response_text = extract_response_text(chunk)
    await stream_manager.update_progress(
        stream_id,
        message_chunk=response_text,
        tool_data=new_data,
    )
    return follow_up_actions, True


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


def extract_tool_data(json_str: str) -> dict[str, Any]:
    """Parse and extract structured tool output from an agent JSON chunk.

    Converts individual tool fields (e.g. ``calendar_options``, ``search_results``)
    into the unified ``ToolDataEntry`` array format the frontend consumes.

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

    timestamp = datetime.now(UTC).isoformat()

    other_data: dict[str, Any] = {}
    if data.get("follow_up_actions") is not None:
        other_data["follow_up_actions"] = data["follow_up_actions"]

    tool_data_entries: list[ToolDataEntry] = []

    # Source A: already in unified format (from backend tool_data emission).
    if "tool_data" in data:
        td = data["tool_data"]
        tool_data_entries = td if isinstance(td, list) else [td]
    # Source B: legacy individual tool fields.
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
