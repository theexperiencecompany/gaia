"""Stream-state helpers — recovery from Redis, accumulator merges, token math.

Pure data manipulation on the orchestrator's accumulators
(``tool_data`` / ``tool_outputs`` / ``todo_progress_accumulated`` / LangChain
``usage_metadata``). No I/O except for the Redis progress read used on
cancellation paths where the ``nostream`` marker never arrives.

Entries inside the ``tool_data`` accumulator are :class:`ToolDataEntry`; the
accumulator envelope holding them stays ``dict[str, object]`` because
``services/chat/persistence`` ``setattr``s every one of its keys onto the
message, so arbitrary non-``tool_data`` keys (``follow_up_actions``, …) ride
along in the same bag (see ``utils/stream_utils``).
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NamedTuple, cast

from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry
from app.utils.json_helpers import text_bag
from app.utils.stream_utils import apply_outputs_to_tool_data
from shared.py.wide_events import log


class TokenTotals(NamedTuple):
    """Per-turn token rollup across every model call in the turn."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int


def aggregate_usage_metadata(
    usage_metadata: Mapping[str, object],
) -> TokenTotals:
    """Sum input, output, and cache-read tokens across all model entries.

    ``usage_metadata`` is LangChain's ``UsageMetadataCallbackHandler`` output
    keyed by model name. It stays ``dict[str, object]``: the per-entry values are
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
    tool_data: dict[str, object],
) -> tuple[str, dict[str, object]]:
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

    complete_message = text_bag(progress, "complete_message")
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


def _entry_list(tool_data: dict[str, object]) -> list[ToolDataEntry]:
    """The envelope's entry list, installed in place when the key is absent.

    Callers mutate the returned list and expect the result to be persisted, so
    it must be the list the envelope holds — never a throwaway copy.

    ``cast``, not ``isinstance`` (API CLAUDE.md item 12): the envelope is the
    orchestrator's own accumulator (``services/chat/stream``), whose
    ``tool_data`` slot starts as ``[]`` and is only ever appended to with
    ``ToolDataEntry``.
    """
    return cast(list[ToolDataEntry], tool_data.setdefault("tool_data", []))


def merge_tool_outputs(
    tool_data: dict[str, object],
    tool_outputs: dict[str, str],
) -> None:
    """Merge captured tool outputs into ``tool_calls_data`` entries in-place.

    The envelope-taking counterpart of ``apply_outputs_to_tool_data``, which the
    background-executor drain calls with the entry list directly.
    """
    apply_outputs_to_tool_data(
        _entry_list(tool_data), tool_outputs, only_tool_name="tool_calls_data"
    )


def inject_todo_progress(
    tool_data: dict[str, object],
    todo_progress_accumulated: dict[str, object],
) -> None:
    """Append the accumulated todo snapshots as a single ``tool_data`` entry."""
    if todo_progress_accumulated:
        entry: ToolDataEntry = {
            "tool_name": "todo_progress",
            "data": todo_progress_accumulated,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        _entry_list(tool_data).append(entry)
