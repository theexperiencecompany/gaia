"""Shared helpers for processing LangGraph stream events and tool call data.

Used by the subagent runner, the workflow subagent, the background executor
collector, and the chat-stream orchestrator's turn finalization.

Every entry these helpers move around is a :class:`ToolDataEntry` — that shape
is closed and is what reaches MongoDB, so an emitted key it does not declare is
dropped on persist (see the type's own docstring).

The accumulator ENVELOPE around it (``{"tool_data": [...], "subagent_starts":
{...}, "subagent_ends": {...}}``) stays ``dict[str, Any]`` deliberately: the
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
    approval_id: str | None = data.get("approval_id")
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
        _append_or_upsert_tool_data(accumulated["tool_data"], evt["tool_data"])
    if "tool_output" in evt:
        out = evt["tool_output"]
        tid, val = out.get("tool_call_id"), out.get("output")
        if tid and val:
            tool_outputs[tid] = val
    if "reasoning" in evt:
        _absorb_reasoning(evt["reasoning"], accumulated["tool_data"])
    if "subagent_start" in evt:
        sid = evt["subagent_start"]["subagent_id"]
        accumulated.setdefault("subagent_starts", {})[sid] = evt["subagent_start"]
    if "subagent_end" in evt:
        sid = evt["subagent_end"]["subagent_id"]
        accumulated.setdefault("subagent_ends", {})[sid] = evt["subagent_end"]


def _absorb_reasoning(reasoning: dict[str, Any], tool_data: list[ToolDataEntry]) -> None:
    """Persist a streamed thinking block into tool_data as a reasoning step.

    Mirrors the frontend (streamHandlers.handleReasoning): a reasoning step rides a
    ``tool_calls_data`` entry so it persists + renders alongside tool calls; the
    ``subagent_id`` tag lets reconstruct_subagent_groups nest subagent thinking.

    One event is already one step's worth of thinking — ``_ReasoningBuffer`` in the
    subagent runner accumulates the deltas and flushes at each tool boundary — so
    this appends. Merging here was what kept an event-per-token stream readable;
    it never bounded what got persisted, and the entries are the cost.
    """
    content = reasoning.get("content")
    if not content:
        return
    subagent_id = reasoning.get("subagent_id")
    # `data` is a SINGLE step dict (not a list): reconstruct_subagent_groups appends
    # a subagent entry's `data` straight into tool_calls, and bucketToolData wraps a
    # single dict on the frontend — a list here would nest a tool_call with no
    # tool_name and crash the renderer.
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
        if tc_id and tc_id in tool_outputs:
            data["output"] = tool_outputs[tc_id]


def reconstruct_subagent_groups(accumulated: dict[str, Any]) -> None:
    """Group flat tool_data entries tagged with subagent_id into subagent_group
    entries for MongoDB persistence. Mutates the accumulator in place.

    Uses subagent_starts/subagent_ends accumulated by process_data_chunk.
    """
    subagent_starts: dict[str, Any] = accumulated.pop("subagent_starts", {})
    subagent_ends: dict[str, Any] = accumulated.pop("subagent_ends", {})

    if not subagent_starts:
        return

    now = datetime.now(UTC).isoformat()

    # Build groups from start events
    groups: dict[str, SubagentGroup] = {}
    for subagent_id, start in subagent_starts.items():
        end = subagent_ends.get(subagent_id, {})
        groups[subagent_id] = SubagentGroup(
            subagent_id=subagent_id,
            subagent_name=start.get("subagent_name", ""),
            agent_type=start.get("agent_type", "spawned"),
            tool_calls=[],
            duration_ms=end.get("duration_ms"),
            token_count=end.get("token_count"),
            started_at=start.get("started_at", now),
            # Always set — this runs only at turn finalization, so a subagent
            # without an end event was cut short (cancelled / errored / timed
            # out), not still running. Leaving it null persists a "forever
            # spinning" card (the frontend keys its spinner on completed_at).
            completed_at=now,
            icon_url=start.get("icon_url"),
            tool_category=start.get("tool_category"),
            nested_subagents=[],
        )

    # Route subagent-tagged entries into their group
    flat_entries: list[ToolDataEntry] = accumulated.get("tool_data", [])
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
        parent_id: str | None = subagent_starts[subagent_id].get("parent_subagent_id")
        if parent_id and parent_id in groups:
            groups[parent_id]["nested_subagents"].append(group)
        else:
            root_groups.append(group)

    # Rebuild tool_data
    group_entries: list[ToolDataEntry] = [
        {
            "tool_name": "subagent_group",
            "data": cast(dict[str, Any], group),
            "timestamp": group["started_at"],
        }
        for group in root_groups
    ]
    accumulated["tool_data"] = top_level + group_entries
