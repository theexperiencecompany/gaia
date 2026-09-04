"""Stream-state helpers — recovery from Redis, accumulator merges, token math.

Pure data manipulation on the orchestrator's accumulators
(``tool_data`` / ``tool_outputs`` / ``todo_progress_accumulated`` / LangChain
``usage_metadata``). No I/O except for the Redis progress read used on
cancellation paths where the ``nostream`` marker never arrives.

Entries inside the ``tool_data`` accumulator are :class:`ToolDataEntry`; the
accumulator envelope holding them stays ``dict[str, Any]`` because
``services/chat/persistence`` ``setattr``s every one of its keys onto the
message, so arbitrary non-``tool_data`` keys (``follow_up_actions``, …) ride
along in the same bag (see ``utils/stream_utils``).
"""

from datetime import UTC, datetime
from typing import Any, NamedTuple

from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry
from app.utils.message_breaks import append_message_bubble
from app.utils.stream_utils import apply_outputs_to_tool_data
from shared.py.wide_events import log


class TokenTotals(NamedTuple):
    """Per-turn token rollup across every model call in the turn."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int


def aggregate_usage_metadata(
    usage_metadata: dict[str, Any],
) -> TokenTotals:
    """Sum input, output, and cache-read tokens across all model entries.

    ``usage_metadata`` is LangChain's ``UsageMetadataCallbackHandler`` output
    keyed by model name. It stays ``dict[str, Any]``: the per-entry values are
    canonically ``UsageMetadata``, but some provider SDK versions add their own
    keys (``cached_content_token_count``) that the canonical TypedDict does not
    declare — hence the ``isinstance`` guard and the fallback below.
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
    return TokenTotals(total_input, total_output, total_cached)


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

    # Settled bubbles, plus whatever was streaming when the run stopped — the
    # same flush the graph driver does with its own held text. Joined as a
    # bubble, never concatenated: two messages run together read as one
    # sentence, which is how a planning preamble ended up glued to a reply.
    complete_message = progress.get("complete_message", "")
    if pending := progress.get("pending_message"):
        complete_message = append_message_bubble(complete_message, pending)
    progress_tool_data = progress.get("tool_data")
    if (
        isinstance(progress_tool_data, dict)
        and progress_tool_data.get("tool_data")
        and not tool_data.get("tool_data")
    ):
        tool_data = progress_tool_data
    log.debug(
        f"{LogTag.CHAT} Recovered chars from Redis progress",
        complete_message_count=len(complete_message),
    )
    return complete_message, tool_data


def merge_tool_outputs(
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
) -> None:
    """Merge captured tool outputs into ``tool_calls_data`` entries in-place.

    The envelope-taking counterpart of ``apply_outputs_to_tool_data``, which the
    background-executor drain calls with the entry list directly.
    """
    entries: list[ToolDataEntry] = tool_data.get("tool_data", [])
    apply_outputs_to_tool_data(entries, tool_outputs, only_tool_name="tool_calls_data")


def inject_todo_progress(
    tool_data: dict[str, Any],
    todo_progress_accumulated: dict[str, Any],
) -> None:
    """Append the accumulated todo snapshots as a single ``tool_data`` entry."""
    if todo_progress_accumulated:
        entry: ToolDataEntry = {
            "tool_name": "todo_progress",
            "data": todo_progress_accumulated,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        entries: list[ToolDataEntry] = tool_data["tool_data"]
        entries.append(entry)
