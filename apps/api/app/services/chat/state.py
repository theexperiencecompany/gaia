"""Stream-state helpers — recovery from Redis, accumulator merges, token math.

Pure data manipulation on the orchestrator's accumulators
(``tool_data`` / ``tool_outputs`` / ``todo_progress_accumulated`` / LangChain
``usage_metadata``). No I/O except for the Redis progress read used on
cancellation paths where the ``nostream`` marker never arrives.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.stream_manager import stream_manager
from shared.py.wide_events import log


def aggregate_usage_metadata(
    usage_metadata: dict[str, Any],
) -> tuple[int, int, int]:
    """Sum input, output, and cache-read tokens across all model entries.

    Returns ``(total_input, total_output, total_cached)``. ``cache_read`` lives
    in each entry's ``input_token_details`` (LangChain canonical shape); some
    provider SDK versions surface it under ``cached_content_token_count`` so we
    fall back to that.
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


async def recover_stream_state(
    stream_id: str,
    complete_message: str,
    tool_data: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Recover accumulated state from Redis progress.

    Called on cancellation / error paths where the ``nostream`` complete-message
    marker never arrived. ``stream_manager.update_progress`` accumulates the
    streamed text and tool-data shape, so we can rebuild what we missed.
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


def merge_tool_outputs(
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
) -> None:
    """Merge captured tool outputs into ``tool_calls_data`` entries in-place."""
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
    """Append the accumulated todo snapshots as a single ``tool_data`` entry."""
    if todo_progress_accumulated:
        tool_data["tool_data"].append(
            {
                "tool_name": "todo_progress",
                "data": todo_progress_accumulated,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
