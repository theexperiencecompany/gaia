"""SSE chunk parsing and dispatch for the chat stream.

The agent emits two flavors of chunk: plain ``data: {...}`` SSE frames (forwarded
to the client) and ``nostream: {...}`` markers (consumed by the orchestrator and
never sent on). :func:`process_data_chunk` is the per-chunk side-effecting
dispatcher; :func:`extract_tool_data`, :func:`normalize_custom_event`, and
:func:`extract_response_text` are pure parsers reused by the dispatcher, the
LangGraph stream processor in ``stream_utils``, and the legacy
``call_agent_silent`` path in ``agent_utils``.

Two shapes here stay ``dict[str, Any]`` on purpose (Type Safety item 14):

* the chunk payloads themselves — an agent chunk is arbitrary JSON emitted by
  whichever tool/hook wrote it, and ``normalize_custom_event`` passes anything
  it does not recognise straight through, so there is no closed shape to name;
* :func:`extract_tool_data`'s ``{tool_data?, other_data?, tool_output?}``
  envelope — it is consumed by ``utils/stream_publishers`` and
  ``utils/agent_utils``, both of which declare it as a plain ``dict[str, Any]``
  parameter, so naming it would have to retype those in the same pass.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, cast

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
from app.models.stream_events import TodoProgressFrame
from app.utils.stream_publishers import (
    accumulate_todo_progress,
    publish_other_data,
    publish_tool_data,
    publish_tool_output,
)


@dataclass(slots=True)
class ChunkAccumulators:
    """Per-turn accumulators that :func:`process_data_chunk` mutates in place."""

    tool_data: dict[str, Any]
    tool_outputs: dict[str, str]
    todo_progress: dict[str, Any]
    follow_up_actions: list[str]


async def process_data_chunk(
    stream_id: str,
    chunk: str,
    acc: ChunkAccumulators,
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
    lifecycle_forwarded = False
    if forward_subagents and chunk_json:
        lifecycle_forwarded = await _forward_subagent_lifecycle(
            stream_id, chunk_json, acc.tool_data
        )
    accumulate_todo_progress(chunk_json, acc.todo_progress)
    await _settle_boundary(stream_id, chunk_json)

    new_data = extract_tool_data(chunk_payload)
    if not new_data:
        if lifecycle_forwarded:
            # Already published as dedicated lifecycle frames — republishing the
            # raw chunk would send the same event twice.
            return acc.follow_up_actions, True
        # No tool data — pass through as-is.
        await stream_manager.publish_chunk(stream_id, chunk)
        response_text = extract_response_text(chunk)
        if response_text:
            await stream_manager.update_progress(
                stream_id,
                message_chunk=response_text,
                tool_data=None,
            )
        return acc.follow_up_actions, True

    acc.follow_up_actions = await publish_other_data(stream_id, new_data, acc.follow_up_actions)
    await publish_tool_data(stream_id, new_data, acc.tool_data)
    await publish_tool_output(stream_id, new_data, acc.tool_outputs)

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
    return acc.follow_up_actions, True


async def _settle_boundary(stream_id: str, chunk_json: dict[str, Any] | None) -> None:
    """Apply a ``message_boundary`` frame to the Redis progress record.

    The frame is the turn's own verdict on the message that just ended — kept,
    or a discarded preamble to a tool call. The live client acts on it; the
    progress record used for recovery has to act on it too, or a recovered turn
    resurrects text the user was explicitly told to drop.
    """
    if not chunk_json:
        return
    boundary = chunk_json.get("message_boundary")
    if not isinstance(boundary, dict):
        return
    await stream_manager.settle_message_progress(
        stream_id, discarded=bool(boundary.get("discarded"))
    )


async def _forward_subagent_lifecycle(
    stream_id: str, chunk_json: dict[str, Any], tool_data: dict[str, Any]
) -> bool:
    """Forward subagent start/end events to the client and accumulate them.

    Returns ``True`` when a lifecycle frame was published, so the caller skips
    the generic passthrough that would republish the same event.
    """
    forwarded = False
    if "subagent_start" in chunk_json:
        start = chunk_json["subagent_start"]
        tool_data.setdefault("subagent_starts", {})[start["subagent_id"]] = start
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_start': start})}\n\n",
        )
        forwarded = True
    if "subagent_end" in chunk_json:
        end = chunk_json["subagent_end"]
        tool_data.setdefault("subagent_ends", {})[end["subagent_id"]] = end
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_end': end})}\n\n",
        )
        forwarded = True
    return forwarded


def _parse_chunk_json(chunk_payload: str) -> dict[str, Any] | None:
    """Parse a chunk payload as JSON, returning ``None`` on malformed input."""
    try:
        return cast(dict[str, Any], json.loads(chunk_payload))
    except json.JSONDecodeError:
        return None


def extract_response_text(chunk: str) -> str:
    """Extract the ``response`` field from a ``data:`` chunk, or empty string."""
    try:
        chunk = chunk.removeprefix("data: ")
        data = json.loads(chunk)
        return cast(str, data.get("response", ""))
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
    # A lone entry rides the envelope unwrapped; several ride as a list. The
    # frontend parser accepts both, and normalizing to a list here would change
    # the wire shape for every single-tool chunk.
    tool_data_value: ToolDataEntry | list[ToolDataEntry] = (
        entries[0] if len(entries) == 1 else entries
    )
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
