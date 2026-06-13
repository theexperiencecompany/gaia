"""Shared helpers for processing LangGraph stream events and tool call data.

Used by agent_helpers, subagent_runner, and chat_service.
"""

from datetime import UTC, datetime
import json
from typing import Any

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
from app.utils.agent_utils import IntegrationMetadata, format_tool_call_entry
from app.utils.stream_publishers import (
    accumulate_todo_progress,
    publish_other_data,
    publish_tool_data,
    publish_tool_output,
)
from shared.py.wide_events import log


async def extract_tool_entries_from_update(
    state_update: dict,
    emitted_tool_calls: set[str],
    integration_metadata: IntegrationMetadata | None = None,
) -> list[tuple[str, dict]]:
    """Extract new tool_data entries from a LangGraph state update.

    Formats each tool call for frontend streaming, deduplicating against
    ``emitted_tool_calls`` (mutated in place). ``integration_metadata``, if
    given, is applied to every entry. Returns (tool_call_id, tool_entry) tuples
    for tool calls not yet emitted.
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
                icon_url=(integration_metadata.get("icon_url") if integration_metadata else None),
                integration_id=(
                    integration_metadata.get("integration_id") if integration_metadata else None
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
        chunk = chunk.removeprefix("data: ")
        data = json.loads(chunk)
        return data.get("response", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def normalize_custom_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize any tool payload dict into the unified tool_data format.

    Hooks emit raw field payloads like {"email_compose_data": [...]} via
    get_stream_writer(). This is the single conversion point used by both
    the executor streaming path (subagent_runner) and the comms loop
    (extract_tool_data below).

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
    """
    Parse and extract structured tool output from an agent's JSON response chunk.

    Uses normalize_custom_event for tool detection so the field registry lives
    in exactly one place. Returns a dict with:
    - "tool_data": list of ToolDataEntry objects (if any tool data found)
    - "other_data": dict with non-tool fields like follow_up_actions
    - "tool_output": forwarded as-is if present
    """
    try:
        data = json.loads(json_str)

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

    chunk_json: dict[str, Any] | None = None
    try:
        chunk_json = json.loads(chunk_payload)
    except json.JSONDecodeError:
        chunk_json = None

    if chunk_json:
        await _forward_subagent_lifecycle(stream_id, chunk_json, tool_data)
        accumulate_todo_progress(chunk_json, todo_progress_accumulated)

    new_data = extract_tool_data(chunk_payload)
    if not new_data:
        await stream_manager.publish_chunk(stream_id, chunk)
        response_text = _extract_response_text(chunk)
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

    response_text = _extract_response_text(chunk)
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


def aggregate_usage_metadata(usage_metadata: dict[str, Any]) -> tuple[int, int, int]:
    """Sum input, output, and cache_read tokens across all model entries.

    Returns (total_input, total_output, total_cached). ``cache_read`` lives in
    each entry's ``input_token_details`` (LangChain canonical shape). Some
    provider SDK versions surface it under different keys, hence the fallbacks.
    """
    total_input = 0
    total_output = 0
    total_cached = 0
    for v in usage_metadata.values():
        if not isinstance(v, dict):
            continue
        total_input += int(v.get("input_tokens") or 0)
        total_output += int(v.get("output_tokens") or 0)
        details = v.get("input_token_details") or {}
        cached = details.get("cache_read") or v.get("cached_content_token_count") or 0
        total_cached += int(cached or 0)
    return total_input, total_output, total_cached


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
                "timestamp": datetime.now(UTC).isoformat(),
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


def absorb_collector_event(
    evt: dict[str, Any],
    accumulated: dict[str, Any],
    tool_outputs: dict[str, str],
) -> None:
    """Route a single tool-event-collector event into the right bucket.

    Used by both the live-streaming path (chat_service) and the queued executor
    path (executor_runner) to drain the per-stream collector into a tool_data
    list with associated outputs and subagent start/end pairs.
    """
    if "tool_data" in evt:
        accumulated["tool_data"].append(evt["tool_data"])
    if "tool_output" in evt:
        out = evt["tool_output"]
        tid, val = out.get("tool_call_id"), out.get("output")
        if tid and val:
            tool_outputs[tid] = val
    if "subagent_start" in evt:
        sid = evt["subagent_start"]["subagent_id"]
        accumulated.setdefault("subagent_starts", {})[sid] = evt["subagent_start"]
    if "subagent_end" in evt:
        sid = evt["subagent_end"]["subagent_id"]
        accumulated.setdefault("subagent_ends", {})[sid] = evt["subagent_end"]


def apply_outputs_to_tool_data(
    entries: list[dict[str, Any]],
    tool_outputs: dict[str, str],
    *,
    only_tool_name: str | None = None,
) -> None:
    """Backfill each tool_data entry's `data.output` from the collected outputs map.

    Pass `only_tool_name` to restrict the update to entries with that
    `tool_name` (e.g. `"tool_calls_data"` for the chat_service path, which only
    enriches tool_calls_data entries; the executor_runner path applies to all).
    """
    for entry in entries:
        if only_tool_name is not None and entry.get("tool_name") != only_tool_name:
            continue
        data = entry.get("data", {})
        if not isinstance(data, dict):
            continue
        tc_id = data.get("tool_call_id")
        if tc_id and tc_id in tool_outputs:
            data["output"] = tool_outputs[tc_id]


def reconstruct_subagent_groups(tool_data: dict[str, Any]) -> None:
    """Group flat tool_data entries tagged with subagent_id into subagent_group
    entries for MongoDB persistence. Mutates tool_data in place.

    Uses subagent_starts/subagent_ends accumulated by process_data_chunk.
    """
    subagent_starts: dict[str, Any] = tool_data.pop("subagent_starts", {})
    subagent_ends: dict[str, Any] = tool_data.pop("subagent_ends", {})

    if not subagent_starts:
        return

    now = datetime.now(UTC).isoformat()

    # Build groups from start events
    groups: dict[str, dict[str, Any]] = {}
    for subagent_id, start in subagent_starts.items():
        end = subagent_ends.get(subagent_id, {})
        groups[subagent_id] = {
            "subagent_id": subagent_id,
            "subagent_name": start.get("subagent_name", ""),
            "agent_type": start.get("agent_type", "spawned"),
            "tool_calls": [],
            "duration_ms": end.get("duration_ms"),
            "token_count": end.get("token_count"),
            "started_at": start.get("started_at", now),
            "completed_at": now if subagent_id in subagent_ends else None,
            "icon_url": start.get("icon_url"),
            "tool_category": start.get("tool_category"),
            "nested_subagents": [],
        }

    # Route subagent-tagged entries into their group
    flat_entries: list[dict[str, Any]] = tool_data.get("tool_data", [])
    top_level: list[dict[str, Any]] = []
    for entry in flat_entries:
        target_id: str | None = entry.get("subagent_id")
        if target_id and target_id in groups and entry.get("tool_name") == "tool_calls_data":
            groups[target_id]["tool_calls"].append(entry.get("data", {}))
        else:
            top_level.append(entry)

    # Nest child groups inside their parent
    root_groups: list[dict[str, Any]] = []
    for subagent_id, group in groups.items():
        parent_id: str | None = subagent_starts[subagent_id].get("parent_subagent_id")
        if parent_id and parent_id in groups:
            groups[parent_id]["nested_subagents"].append(group)
        else:
            root_groups.append(group)

    # Rebuild tool_data
    tool_data["tool_data"] = top_level + [
        {
            "tool_name": "subagent_group",
            "data": group,
            "timestamp": group["started_at"],
        }
        for group in root_groups
    ]
