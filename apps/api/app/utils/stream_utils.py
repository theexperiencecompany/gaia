"""Shared helpers for processing LangGraph stream events and tool call data.

Used by the subagent runner, the workflow subagent, the background executor
collector, and the chat-stream orchestrator's turn finalization.

Every entry these helpers move around is a :class:`ToolDataEntry` — that shape
is closed and is what reaches MongoDB, so an emitted key it does not declare is
dropped on persist (see the type's own docstring).

The accumulator ENVELOPE around it (``{"tool_data": [...], "subagent_starts":
{...}, "subagent_ends": {...}}``) stays ``dict[str, object]`` deliberately: the
chat and silent paths also merge whatever non-``tool_data`` keys a custom event
produced (``follow_up_actions``, …) into the same dict, and
``services/chat/persistence`` then ``setattr``s each of them onto the message.
It is an open bag by design, so a TypedDict would misdescribe it.
"""

from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.chat_models import ToolDataEntry
from app.utils.agent_utils import IntegrationMetadata, format_tool_call_entry
from app.utils.json_helpers import int_opt_bag, text_bag, text_opt_bag


class SubagentGroup(TypedDict):
    """One delegated subagent's rolled-up record, persisted as the ``data`` of a
    ``subagent_group`` tool_data entry. Built by
    :func:`reconstruct_subagent_groups` from the turn's start/end events."""

    subagent_id: str
    subagent_name: str
    agent_type: str
    tool_calls: list[Any]
    duration_ms: int | None
    token_count: int | None
    started_at: str
    completed_at: str
    icon_url: str | None
    tool_category: str | None
    nested_subagents: list["SubagentGroup"]


async def extract_tool_entries_from_update(
    state_update: object,
    emitted_tool_calls: set[str],
    integration_metadata: IntegrationMetadata | None = None,
) -> list[tuple[str, ToolDataEntry]]:
    """Extract new tool_data entries from a LangGraph state update.

    Formats each tool call for frontend streaming, deduplicating against
    ``emitted_tool_calls`` (mutated in place). ``integration_metadata``, if
    given, is applied to every entry. Returns (tool_call_id, tool_entry) tuples
    for tool calls not yet emitted.

    ``state_update`` is typed ``object``: callers pass whatever a node yielded
    from an ``updates`` stream event, which is not always a mapping — the
    ``isinstance`` guard below is load-bearing, not defensive padding.
    """
    entries: list[tuple[str, ToolDataEntry]] = []

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


def _approval_id_of(entry: ToolDataEntry) -> str | None:
    """The approval_id of a HIL ``approval_request`` tool_data entry, or None."""
    if entry.get("tool_name") != APPROVAL_REQUEST_TOOL_NAME:
        return None
    data = entry.get("data")
    if not isinstance(data, dict):
        return None
    approval_id = data.get("approval_id")
    if not isinstance(approval_id, str):
        return None
    return approval_id


def _append_or_upsert_tool_data(entries: list[ToolDataEntry], entry: ToolDataEntry) -> None:
    """Append ``entry``, except a HIL approval frame replaces the prior frame for
    the same approval_id in place — so the persisted turn carries exactly one
    entry per approval, in its final (resolved) status rather than a stuck one."""
    approval_id = _approval_id_of(entry)
    if approval_id is not None:
        for index, existing in enumerate(entries):
            if _approval_id_of(existing) == approval_id:
                entries[index] = entry
                return
    entries.append(entry)


def absorb_collector_event(
    evt: dict[str, object],
    accumulated: dict[str, object],
    tool_outputs: dict[str, str],
) -> None:
    """Route a single tool-event-collector event into the right bucket.

    Used by both the live-streaming path (chat_service) and the queued executor
    path (executor_runner) to drain the per-stream collector into a tool_data
    list with associated outputs and subagent start/end pairs.
    """
    if "tool_data" in evt:
        # Our own SSE emitter guarantees these shapes; bridged, not assumed.
        _append_or_upsert_tool_data(
            cast(list[ToolDataEntry], accumulated["tool_data"]),
            cast(ToolDataEntry, evt["tool_data"]),
        )
    if "tool_output" in evt:
        out = evt["tool_output"]
        if isinstance(out, dict):
            tid = text_opt_bag(out, "tool_call_id")
            val = text_opt_bag(out, "output")
            if tid and val:
                tool_outputs[tid] = val
    if "reasoning" in evt:
        reasoning = evt["reasoning"]
        acc_td = accumulated["tool_data"]
        if isinstance(reasoning, dict) and isinstance(acc_td, list):
            _absorb_reasoning(reasoning, cast(list[ToolDataEntry], acc_td))
    if "subagent_start" in evt:
        start = evt["subagent_start"]
        if isinstance(start, dict):
            sid = text_bag(start, "subagent_id")
            starts = accumulated.get("subagent_starts")
            if not isinstance(starts, dict):
                starts = {}
                accumulated["subagent_starts"] = starts
            starts[sid] = start
    if "subagent_end" in evt:
        end = evt["subagent_end"]
        if isinstance(end, dict):
            sid = text_bag(end, "subagent_id")
            ends = accumulated.get("subagent_ends")
            if not isinstance(ends, dict):
                ends = {}
                accumulated["subagent_ends"] = ends
            ends[sid] = end


def _absorb_reasoning(reasoning: dict[str, object], tool_data: list[ToolDataEntry]) -> None:
    """Persist a streamed thinking delta into tool_data as a reasoning step.

    Mirrors the frontend (streamHandlers.handleReasoning): a reasoning step rides a
    ``tool_calls_data`` entry so it persists + renders alongside tool calls; the
    ``subagent_id`` tag lets reconstruct_subagent_groups nest subagent thinking.
    Consecutive deltas for the same scope merge into one block that breaks at each
    tool call (so thinking shows per-step, not as hundreds of fragments).
    """
    content = reasoning.get("content")
    if not isinstance(content, str) or not content:
        return
    subagent_id = text_opt_bag(reasoning, "subagent_id")
    # `data` is a SINGLE step dict (not a list): reconstruct_subagent_groups appends
    # a subagent entry's `data` straight into tool_calls, and bucketToolData wraps a
    # single dict on the frontend — a list here would nest a tool_call with no
    # tool_name and crash the renderer.
    last = tool_data[-1] if tool_data else None
    last_data = last.get("data") if last is not None else None
    if (
        last is not None
        and last.get("tool_name") == "tool_calls_data"
        and last.get("subagent_id") == subagent_id
        and isinstance(last_data, dict)
        and last_data.get("reasoning") is not None
    ):
        raw_reasoning = last_data.get("reasoning")
        last_data["reasoning"] = (raw_reasoning if isinstance(raw_reasoning, str) else "") + content
        return
    entry: ToolDataEntry = {
        "tool_name": "tool_calls_data",
        "tool_category": "reasoning",
        "data": {
            "tool_name": "reasoning",
            "tool_category": "reasoning",
            "message": "",
            "reasoning": content,
        },
    }
    if subagent_id:
        entry["subagent_id"] = subagent_id
    tool_data.append(entry)


def apply_outputs_to_tool_data(
    entries: list[ToolDataEntry],
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
        if isinstance(tc_id, str) and tc_id in tool_outputs:
            data["output"] = tool_outputs[tc_id]


def reconstruct_subagent_groups(accumulated: dict[str, object]) -> None:
    """Group flat tool_data entries tagged with subagent_id into subagent_group
    entries for MongoDB persistence. Mutates the accumulator in place.

    Uses subagent_starts/subagent_ends accumulated by process_data_chunk.
    """
    raw_starts = accumulated.pop("subagent_starts", {})
    raw_ends = accumulated.pop("subagent_ends", {})
    subagent_starts = raw_starts if isinstance(raw_starts, dict) else {}
    subagent_ends = raw_ends if isinstance(raw_ends, dict) else {}

    if not subagent_starts:
        return

    now = datetime.now(UTC).isoformat()

    # Build groups from start events
    groups: dict[str, SubagentGroup] = {}
    for subagent_id, start in subagent_starts.items():
        end = subagent_ends.get(subagent_id, {})
        groups[subagent_id] = SubagentGroup(
            subagent_id=subagent_id,
            subagent_name=text_bag(start, "subagent_name"),
            agent_type=text_bag(start, "agent_type", "spawned"),
            tool_calls=[],
            duration_ms=int_opt_bag(end, "duration_ms"),
            token_count=int_opt_bag(end, "token_count"),
            started_at=text_bag(start, "started_at", now),
            # Always set — this runs only at turn finalization, so a subagent
            # without an end event was cut short (cancelled / errored / timed
            # out), not still running. Leaving it null persists a "forever
            # spinning" card (the frontend keys its spinner on completed_at).
            completed_at=now,
            icon_url=text_opt_bag(start, "icon_url"),
            tool_category=text_opt_bag(start, "tool_category"),
            nested_subagents=[],
        )

    # Route subagent-tagged entries into their group
    raw_flat = accumulated.get("tool_data", [])
    flat_entries = cast(list[ToolDataEntry], raw_flat) if isinstance(raw_flat, list) else []
    top_level: list[ToolDataEntry] = []
    for entry in flat_entries:
        target_id: str | None = entry.get("subagent_id")
        if target_id and target_id in groups and entry.get("tool_name") == "tool_calls_data":
            groups[target_id]["tool_calls"].append(entry.get("data", {}))
        else:
            top_level.append(entry)

    # Nest child groups inside their parent
    root_groups: list[SubagentGroup] = []
    for subagent_id, group in groups.items():
        parent_start = subagent_starts[subagent_id]
        parent_id = (
            text_opt_bag(parent_start, "parent_subagent_id")
            if isinstance(parent_start, dict)
            else None
        )
        if parent_id and parent_id in groups:
            groups[parent_id]["nested_subagents"].append(group)
        else:
            root_groups.append(group)

    # Rebuild tool_data
    group_entries: list[ToolDataEntry] = [
        {
            "tool_name": "subagent_group",
            "data": cast(dict[str, object], group),
            "timestamp": group["started_at"],
        }
        for group in root_groups
    ]
    accumulated["tool_data"] = top_level + group_entries
