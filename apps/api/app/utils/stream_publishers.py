"""Shared SSE sub-chunk publishers for the chat stream.

Both the live chat dispatcher (app.services.chat.chunks) and the LangGraph
stream processor (app.utils.stream_utils) split a parsed data: chunk into
the same set of side-effecting publishes. These helpers are the single source of
truth for that behavior so the two call sites cannot drift.
"""

from collections.abc import Mapping
import json

from pydantic import BaseModel, ConfigDict, Field

from app.core.stream_manager import stream_manager
from app.models.chat_models import ToolDataEntry
from app.models.stream_events import FollowUpActionsFrame, ToolOutputPayload


class TodoProgressSnapshot(BaseModel):
    """A tool's todo list as of one ``todo_progress`` event, keyed by its ``source``.

    Accumulated per source for the turn and persisted as the ``todo_progress``
    tool_data entry; ``integration_name`` is present only when the emitting
    tool had a label, so it dumps with ``exclude_none``.
    """

    # ``extra="allow"``: the snapshot is persisted exactly as the tool emitted it;
    # only ``source`` is read here, so the rest must survive untouched.
    model_config = ConfigDict(extra="allow")

    todos: list[object] = Field(default_factory=list)
    source: str = "executor"
    integration_name: str | None = None


class _TodoProgressChunk(BaseModel):
    """A parsed ``data:`` chunk, read only for its ``todo_progress`` frame."""

    model_config = ConfigDict(extra="ignore")

    todo_progress: TodoProgressSnapshot | None = None


class ExtractedOtherData(BaseModel):
    """The non-tool fields ``extract_tool_data`` lifts out of a chunk."""

    model_config = ConfigDict(extra="forbid")

    follow_up_actions: list[str]


class ExtractedToolData(BaseModel):
    """What ``app.services.chat.chunks.extract_tool_data`` finds in one agent chunk.

    Empty (no entries, no other data, no output) when the chunk carried none.
    """

    model_config = ConfigDict(extra="forbid")

    tool_data: list[ToolDataEntry] = Field(default_factory=list)
    other_data: ExtractedOtherData | None = None
    tool_output: ToolOutputPayload | None = None

    def is_empty(self) -> bool:
        return not (self.tool_data or self.other_data or self.tool_output)


def accumulate_todo_progress(
    chunk_json: Mapping[str, object] | None,
    todo_progress_accumulated: dict[str, dict[str, object]],
) -> None:
    """Record the latest todo-progress snapshot keyed by its source."""
    if not chunk_json:
        return
    snapshot = _TodoProgressChunk.model_validate(chunk_json).todo_progress
    if snapshot is not None:
        # Stored as sent: an absent source or label stays absent on the persisted entry.
        todo_progress_accumulated[snapshot.source] = snapshot.model_dump(exclude_unset=True)


async def publish_other_data(
    stream_id: str, new_data: ExtractedToolData, follow_up_actions: list[str]
) -> list[str]:
    """Publish follow-up actions if present, returning the (possibly updated) list."""
    if new_data.other_data is not None:
        follow_up_actions = new_data.other_data.follow_up_actions
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps(FollowUpActionsFrame(follow_up_actions=follow_up_actions).model_dump())}\n\n",
        )
    return follow_up_actions


async def publish_tool_data(
    stream_id: str, new_data: ExtractedToolData, entries: list[ToolDataEntry]
) -> None:
    """Append each tool-data entry to entries and stream it to the frontend."""
    for tool_entry in new_data.tool_data:
        entries.append(tool_entry)
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
        )


async def publish_tool_output(
    stream_id: str, new_data: ExtractedToolData, tool_outputs: dict[str, str]
) -> None:
    """Capture a tool_output event for merging before save and stream it live."""
    output_data = new_data.tool_output
    if output_data is None:
        return
    if output_data.tool_call_id and output_data.output:
        tool_outputs[output_data.tool_call_id] = output_data.output
    await stream_manager.publish_chunk(
        stream_id,
        f"data: {json.dumps({'tool_output': output_data.model_dump(exclude_none=True)})}\n\n",
    )
