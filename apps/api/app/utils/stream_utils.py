"""Shared helpers for processing LangGraph stream events and tool call data.

Used by the subagent runner, the workflow subagent, the background executor
collector, and the chat-stream orchestrator's turn finalization.

Every entry these helpers move around is a :class:ToolDataEntry — that shape
is closed and is what reaches MongoDB, so an emitted key it does not declare is
dropped on persist (see the type's own docstring).

The accumulator ENVELOPE around it ({"tool_data": [...], "subagent_starts":
{...}, "subagent_ends": {...}}) stays an open MutableMapping deliberately: the
chat and silent paths also merge whatever non-tool_data keys a custom event
produced (follow_up_actions, …) into the same dict, and
services/chat/persistence then setattrs each of them onto the message.
It is an open bag by design, so a TypedDict would misdescribe it.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.chat_models import ToolDataEntry
from app.utils.agent_utils import (
    IntegrationMetadata,
    NodeMessagesUpdate,
    ToolCallView,
    format_tool_call_entry,
)

#: The accumulator's entries, taken as the caller's own list object: every
#: helper here mutates it in place, so it is never copied by validation — its
#: entries are ToolDataEntry by construction (Type Safety item 12).
_EntryList = Annotated[list[ToolDataEntry], SkipValidation]


class _ToolDataEnvelope(BaseModel):
    """The accumulator envelope's ``tool_data`` list (see the module docstring)."""

    model_config = ConfigDict(extra="ignore")

    tool_data: _EntryList = Field(default_factory=list)


class _SubagentStartEvent(BaseModel):
    """A ``subagent_start`` frame as stored in the accumulator (see ``SubagentStartPayload``)."""

    model_config = ConfigDict(extra="ignore")

    subagent: str | None = None
    subagent_name: str = ""
    agent_type: str = "spawned"
    started_at: str | None = None
    icon_url: str | None = None
    tool_category: str | None = None
    parent_subagent_id: str | None = None


class _SubagentEndEvent(BaseModel):
    """A ``subagent_end`` frame as stored in the accumulator (see ``SubagentEndPayload``)."""

    model_config = ConfigDict(extra="ignore")

    duration_ms: int | None = None
    token_count: int | None = None


class _SubagentLifecycle(BaseModel):
    """The start/end frames a turn accumulated, keyed by subagent id."""

    model_config = ConfigDict(extra="ignore")

    subagent_starts: dict[str, _SubagentStartEvent] = Field(default_factory=dict)
    subagent_ends: dict[str, _SubagentEndEvent] = Field(default_factory=dict)


class _ToolOutputEvent(BaseModel):
    """A collector ``tool_output`` frame (see ``ToolOutputPayload``)."""

    model_config = ConfigDict(extra="ignore")

    tool_call_id: str | None = None
    output: str | None = None


class _ReasoningEvent(BaseModel):
    """A collector ``reasoning`` frame: one flushed step of thinking."""

    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    subagent_id: str | None = None


class _CollectorEvent(BaseModel):
    """One tool-event-collector event, after ``normalize_custom_event``.

    ``tool_data`` is a lone entry, or a list when several tool fields rode one
    event; ``subagent_start``/``subagent_end`` are validated for their id and
    stored as sent.
    """

    model_config = ConfigDict(extra="ignore")

    tool_data: Annotated[ToolDataEntry | list[ToolDataEntry] | None, SkipValidation] = None
    tool_output: _ToolOutputEvent | None = None
    reasoning: _ReasoningEvent | None = None
    subagent_start: Annotated[dict[str, object] | None, SkipValidation] = None
    subagent_end: Annotated[dict[str, object] | None, SkipValidation] = None


class _SubagentFrameId(BaseModel):
    """A start/end frame's subagent id — the key it is filed under."""

    model_config = ConfigDict(extra="ignore")

    subagent_id: str


class _EntryHead(BaseModel):
    """A tool_data entry's discriminating fields; ``data`` is read, never copied."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str = ""
    subagent_id: str | None = None
    data: Annotated[object, SkipValidation] = None


class _EntryDataRefs(BaseModel):
    """The ids an entry's ``data`` may carry: its tool call, or its HIL approval."""

    model_config = ConfigDict(extra="ignore")

    tool_call_id: str | None = None
    approval_id: str | None = None


@dataclass(slots=True)
class SubagentGroup:
    """One delegated subagent's rolled-up record, persisted as the data of a subagent_group entry.

    Built by reconstruct_subagent_groups from the turn's start/end events.
    """

    subagent_id: str
    #: The subagent's stable id, from the start event; ``None`` for a spawned
    #: subagent that has none.
    subagent: str | None
    subagent_name: str
    agent_type: str
    tool_calls: list[object]
    duration_ms: int | None
    token_count: int | None
    started_at: str
    completed_at: str
    icon_url: str | None
    tool_category: str | None
    nested_subagents: list[SubagentGroup]


async def extract_tool_entries_from_update(
    state_update: object,
    emitted_tool_calls: set[str],
    integration_metadata: IntegrationMetadata | None = None,
) -> list[tuple[str, ToolDataEntry]]:
    """Extract new tool_data entries from a LangGraph state update.

    Deduplicates against emitted_tool_calls (mutated in place). state_update
    is typed object since callers pass whatever a node yielded, which is
    not always a mapping — the isinstance guard below is load-bearing.
    """
    entries: list[tuple[str, ToolDataEntry]] = []

    if not isinstance(state_update, dict):
        return entries

    metadata = integration_metadata or IntegrationMetadata()
    for msg in NodeMessagesUpdate.model_validate(state_update).messages:
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            tc_id = ToolCallView.model_validate(tc).id
            if not tc_id or tc_id in emitted_tool_calls:
                continue

            # Format tool call as tool_data entry
            tool_entry = await format_tool_call_entry(
                tc,
                icon_url=metadata.icon_url,
                integration_id=metadata.integration_id,
                integration_name=metadata.name,
            )

            if tool_entry:
                entries.append((tc_id, tool_entry))
                emitted_tool_calls.add(tc_id)

    return entries


def _approval_id_of(entry: ToolDataEntry) -> str | None:
    """Return the approval_id of a HIL approval_request tool_data entry, or None."""
    head = _EntryHead.model_validate(entry)
    if head.tool_name != APPROVAL_REQUEST_TOOL_NAME:
        return None
    if not isinstance(head.data, dict):
        return None
    return _EntryDataRefs.model_validate(head.data).approval_id


def _append_or_upsert_tool_data(entries: list[ToolDataEntry], entry: ToolDataEntry) -> None:
    """Append entry, except a HIL approval frame replaces the prior frame in place.

    So the persisted turn carries exactly one entry per approval_id, in its
    final (resolved) status rather than a stuck one.
    """
    approval_id = _approval_id_of(entry)
    if approval_id is not None:
        for index, existing in enumerate(entries):
            if _approval_id_of(existing) == approval_id:
                entries[index] = entry
                return
    entries.append(entry)


def absorb_collector_event(
    evt: Mapping[str, object],
    accumulated: MutableMapping[str, object],
    tool_outputs: dict[str, str],
) -> None:
    """Route a single tool-event-collector event into the right bucket.

    Used by both the live-streaming path (chat_service) and the queued executor
    path (executor_runner) to drain the per-stream collector into a tool_data
    list with associated outputs and subagent start/end pairs.
    """
    event = _CollectorEvent.model_validate(evt)
    entries = _ToolDataEnvelope.model_validate(accumulated).tool_data
    accumulated["tool_data"] = entries
    if event.tool_data is not None:
        for entry in event.tool_data if isinstance(event.tool_data, list) else [event.tool_data]:
            _append_or_upsert_tool_data(entries, entry)
    if event.tool_output is not None:
        tid, val = event.tool_output.tool_call_id, event.tool_output.output
        if tid and val:
            tool_outputs[tid] = val
    if event.reasoning is not None:
        _absorb_reasoning(event.reasoning, entries)
    if event.subagent_start is not None:
        start_id = _SubagentFrameId.model_validate(event.subagent_start).subagent_id
        _lifecycle_bucket(accumulated, "subagent_starts")[start_id] = event.subagent_start
    if event.subagent_end is not None:
        end_id = _SubagentFrameId.model_validate(event.subagent_end).subagent_id
        _lifecycle_bucket(accumulated, "subagent_ends")[end_id] = event.subagent_end


def _lifecycle_bucket(accumulated: MutableMapping[str, object], bucket: str) -> dict[str, object]:
    """Return the accumulator's start (or end) frames by subagent id, created on first use."""
    frames = accumulated.setdefault(bucket, {})
    if not isinstance(frames, dict):
        raise TypeError(f"accumulator bucket {bucket!r} is {type(frames).__name__}, not a dict")
    return frames


def _absorb_reasoning(reasoning: _ReasoningEvent, tool_data: list[ToolDataEntry]) -> None:
    """Persist a streamed thinking block into tool_data as a reasoning step.

    A reasoning step rides a tool_calls_data entry so it persists and
    renders alongside tool calls. One event is already one step's worth of
    thinking — _ReasoningBuffer flushes at each tool boundary — so this appends.
    """
    content = reasoning.content
    if not content:
        return
    subagent_id = reasoning.subagent_id
    # `data` is a SINGLE step dict, not a list — a list here would nest a
    # tool_call with no tool_name and crash the frontend renderer.
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
    """Backfill each tool_data entry's data.output from the collected outputs map.

    Pass only_tool_name to restrict the update to entries with that
    tool_name (e.g. "tool_calls_data" for the chat_service path, which only
    enriches tool_calls_data entries; the executor_runner path applies to all).
    """
    for entry in entries:
        head = _EntryHead.model_validate(entry)
        if only_tool_name is not None and head.tool_name != only_tool_name:
            continue
        data = head.data
        if not isinstance(data, dict):
            continue
        tc_id = _EntryDataRefs.model_validate(data).tool_call_id
        if tc_id and tc_id in tool_outputs:
            data["output"] = tool_outputs[tc_id]


def reconstruct_subagent_groups(accumulated: MutableMapping[str, object]) -> None:
    """Group flat tool_data entries tagged with subagent_id into subagent_group entries.

    For MongoDB persistence; mutates the accumulator in place, using
    subagent_starts/subagent_ends accumulated by process_data_chunk.
    """
    lifecycle = _SubagentLifecycle.model_validate(accumulated)
    accumulated.pop("subagent_starts", None)
    accumulated.pop("subagent_ends", None)
    subagent_starts = lifecycle.subagent_starts
    subagent_ends = lifecycle.subagent_ends

    if not subagent_starts:
        return

    now = datetime.now(UTC).isoformat()

    # Build groups from start events
    groups: dict[str, SubagentGroup] = {}
    for subagent_id, start in subagent_starts.items():
        end = subagent_ends.get(subagent_id)
        groups[subagent_id] = SubagentGroup(
            subagent_id=subagent_id,
            subagent=start.subagent,
            subagent_name=start.subagent_name,
            agent_type=start.agent_type,
            tool_calls=[],
            duration_ms=end.duration_ms if end else None,
            token_count=end.token_count if end else None,
            started_at=start.started_at or now,
            # Always set: a subagent without an end event was cut short, not
            # still running — null here persists a "forever spinning" card.
            completed_at=now,
            icon_url=start.icon_url,
            tool_category=start.tool_category,
            nested_subagents=[],
        )

    # Route subagent-tagged entries into their group
    flat_entries = _ToolDataEnvelope.model_validate(accumulated).tool_data
    top_level: list[ToolDataEntry] = []
    for entry in flat_entries:
        head = _EntryHead.model_validate(entry)
        target_id = head.subagent_id
        if target_id and target_id in groups and head.tool_name == "tool_calls_data":
            groups[target_id].tool_calls.append(head.data if head.data is not None else {})
        else:
            top_level.append(entry)

    # Nest child groups inside their parent
    root_groups: list[SubagentGroup] = []
    for subagent_id, group in groups.items():
        parent_id = subagent_starts[subagent_id].parent_subagent_id
        if parent_id and parent_id in groups:
            groups[parent_id].nested_subagents.append(group)
        else:
            root_groups.append(group)

    # Rebuild tool_data
    group_entries: list[ToolDataEntry] = [
        {
            "tool_name": "subagent_group",
            "data": asdict(group),
            "timestamp": group.started_at,
        }
        for group in root_groups
    ]
    accumulated["tool_data"] = top_level + group_entries
