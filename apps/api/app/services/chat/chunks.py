"""SSE chunk parsing and dispatch for the chat stream.

The agent emits two flavors of chunk: plain data: {...} SSE frames (forwarded
to the client) and nostream: {...} markers (consumed by the orchestrator and
never sent on). process_data_chunk is the per-chunk dispatcher;
extract_tool_data, normalize_custom_event, and extract_response_text are
pure parsers reused by the dispatcher, the LangGraph stream processor, and
the legacy call_agent_silent path.

The chunk payload stays an open JSON object on purpose (arbitrary JSON,
passed through when unrecognised); the keys this module acts on are read
through the private models below.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import json

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry, tool_fields
from app.models.stream_events import TodoProgressFrame, ToolOutputPayload
from app.utils.stream_publishers import (
    ExtractedOtherData,
    ExtractedToolData,
    accumulate_todo_progress,
    publish_other_data,
    publish_tool_data,
    publish_tool_output,
)

_JSON_OBJECT: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])


class _MessageBoundary(BaseModel):
    """A ``message_boundary`` frame, read only for its verdict."""

    model_config = ConfigDict(extra="ignore")

    discarded: bool = False


class _SubagentFrameId(BaseModel):
    """A ``subagent_start``/``subagent_end`` frame, read only for its subagent id."""

    model_config = ConfigDict(extra="ignore")

    subagent_id: str


class _ChunkFrames(BaseModel):
    """The frames of a ``data:`` chunk the dispatcher acts on besides its tool data.

    Held as the JSON the emitter wrote: the lifecycle and todo frames are forwarded
    and accumulated verbatim.
    """

    model_config = ConfigDict(extra="ignore")

    message_boundary: _MessageBoundary | None = None
    subagent_start: dict[str, object] | None = None
    subagent_end: dict[str, object] | None = None
    todo_progress: dict[str, object] | None = None


class _ChunkToolFields(BaseModel):
    """The non-tool-field keys :func:`extract_tool_data` lifts out of a chunk."""

    model_config = ConfigDict(extra="ignore")

    follow_up_actions: list[str] | None = None
    tool_output: ToolOutputPayload | None = None


class _NormalizedToolData(BaseModel):
    """A normalized event's ``tool_data``: a lone entry or several (see ``normalize_custom_event``)."""

    model_config = ConfigDict(extra="ignore")

    tool_data: ToolDataEntry | list[ToolDataEntry] | None = None


class _ResponseChunk(BaseModel):
    """A ``data:`` chunk, read only for its streamed ``response`` text."""

    model_config = ConfigDict(extra="ignore")

    response: str = ""


@dataclass(slots=True)
class ChunkAccumulators:
    """Per-turn accumulators that :func:process_data_chunk mutates in place."""

    tool_entries: list[ToolDataEntry]
    subagent_starts: dict[str, dict[str, object]]
    subagent_ends: dict[str, dict[str, object]]
    tool_outputs: dict[str, str]
    todo_progress: dict[str, dict[str, object]]
    follow_up_actions: list[str]


async def process_data_chunk(
    stream_id: str,
    chunk: str,
    acc: ChunkAccumulators,
    *,
    forward_subagents: bool = False,
) -> tuple[list[str], bool]:
    """Process a data:-prefixed agent chunk.

    Extracts tool data, follow-up actions, todo progress and tool outputs
    and publishes them to Redis; forwards subagent_start/end markers to the
    client when forward_subagents is set. published means the chunk was
    already sent.
    """
    chunk_payload = chunk[6:]

    chunk_json = _parse_chunk_json(chunk_payload)
    frames = _ChunkFrames.model_validate(chunk_json) if chunk_json is not None else None
    lifecycle_forwarded = False
    if forward_subagents and chunk_json and frames is not None:
        lifecycle_forwarded = await _forward_subagent_lifecycle(stream_id, frames, acc)
    accumulate_todo_progress(chunk_json, acc.todo_progress)
    await _settle_boundary(stream_id, frames)

    new_data = extract_tool_data(chunk_payload)
    if new_data.is_empty():
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
    await publish_tool_data(stream_id, new_data, acc.tool_entries)
    await publish_tool_output(stream_id, new_data, acc.tool_outputs)

    if frames is not None and frames.todo_progress is not None:
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps(TodoProgressFrame(todo_progress=frames.todo_progress).model_dump())}\n\n",
        )

    response_text = extract_response_text(chunk)
    await stream_manager.update_progress(
        stream_id,
        message_chunk=response_text,
        tool_data=new_data.model_dump(exclude_defaults=True),
    )
    return acc.follow_up_actions, True


async def _settle_boundary(stream_id: str, frames: _ChunkFrames | None) -> None:
    """Apply a message_boundary frame to the Redis progress record.

    The frame is the turn's own verdict on the message that just ended — kept,
    or a discarded preamble to a tool call. The live client acts on it; the
    progress record used for recovery has to act on it too, or a recovered turn
    resurrects text the user was explicitly told to drop.
    """
    if frames is None or frames.message_boundary is None:
        return
    await stream_manager.settle_message_progress(
        stream_id, discarded=frames.message_boundary.discarded
    )


async def _forward_subagent_lifecycle(
    stream_id: str, frames: _ChunkFrames, acc: ChunkAccumulators
) -> bool:
    """Forward subagent start/end events to the client and accumulate them.

    Returns True when a lifecycle frame was published, so the caller skips
    the generic passthrough that would republish the same event.
    """
    forwarded = False
    if frames.subagent_start is not None:
        start = frames.subagent_start
        acc.subagent_starts[_SubagentFrameId.model_validate(start).subagent_id] = start
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_start': start})}\n\n",
        )
        forwarded = True
    if frames.subagent_end is not None:
        end = frames.subagent_end
        acc.subagent_ends[_SubagentFrameId.model_validate(end).subagent_id] = end
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'subagent_end': end})}\n\n",
        )
        forwarded = True
    return forwarded


def _parse_chunk_json(chunk_payload: str) -> dict[str, object] | None:
    """Parse a chunk payload as a JSON object, returning None for anything else."""
    try:
        return _JSON_OBJECT.validate_json(chunk_payload)
    except ValidationError:
        return None


def extract_response_text(chunk: str) -> str:
    """Extract the response field from a data: chunk, or empty string."""
    try:
        return _ResponseChunk.model_validate_json(chunk.removeprefix("data: ")).response
    except ValidationError:
        return ""


def normalize_custom_event(payload: dict[str, object]) -> dict[str, object]:
    """Normalize a raw tool payload dict into the unified tool_data format.

    The single conversion point reused by the executor streaming path, the
    comms loop, and the background collector. Already-normalized or non-tool
    payloads pass through unchanged; recognized fields wrap into tool_data
    (a list when several match).
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


def extract_tool_data(json_str: str) -> ExtractedToolData:
    """Parse an agent JSON chunk into tool_data/other_data/tool_output.

    Converts tool fields (e.g. calendar_options) via normalize_custom_event
    so the tool-field registry lives in one place. Malformed JSON or no
    recognized keys yields an empty result.
    """
    data = _parse_chunk_json(json_str)
    if data is None:
        return ExtractedToolData()

    fields = _ChunkToolFields.model_validate(data)
    normalized = _NormalizedToolData.model_validate(normalize_custom_event(data)).tool_data
    if normalized is None:
        tool_data_entries: list[ToolDataEntry] = []
    elif isinstance(normalized, list):
        tool_data_entries = normalized
    else:
        tool_data_entries = [normalized]

    return ExtractedToolData(
        tool_data=tool_data_entries,
        other_data=(
            ExtractedOtherData(follow_up_actions=fields.follow_up_actions)
            if fields.follow_up_actions is not None
            else None
        ),
        tool_output=fields.tool_output,
    )
