"""Shared SSE sub-chunk publishers for the chat stream.

Both the live chat dispatcher (``app.services.chat.chunks``) and the LangGraph
stream processor (``app.utils.stream_utils``) split a parsed ``data:`` chunk into
the same set of side-effecting publishes. These helpers are the single source of
truth for that behavior so the two call sites cannot drift.
"""

import json

from app.core.stream_manager import stream_manager
from app.models.stream_events import FollowUpActionsFrame
from app.utils.json_helpers import list_bag


def accumulate_todo_progress(
    chunk_json: dict[str, object] | None, todo_progress_accumulated: dict[str, object]
) -> None:
    """Record the latest todo-progress snapshot keyed by its source."""
    if chunk_json and "todo_progress" in chunk_json:
        snapshot = chunk_json["todo_progress"]
        if isinstance(snapshot, dict):
            source = snapshot.get("source", "executor")
            todo_progress_accumulated[source] = snapshot


async def publish_other_data(
    stream_id: str, new_data: dict[str, object], follow_up_actions: list[str]
) -> list[str]:
    """Publish follow-up actions if present, returning the (possibly updated) list."""
    other_data_dict = new_data.get("other_data")
    if isinstance(other_data_dict, dict) and "follow_up_actions" in other_data_dict:
        raw_actions = other_data_dict["follow_up_actions"]
        follow_up_actions = (
            [a for a in raw_actions if isinstance(a, str)] if isinstance(raw_actions, list) else []
        )
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps(FollowUpActionsFrame(follow_up_actions=follow_up_actions).model_dump())}\n\n",
        )
    return follow_up_actions


async def publish_tool_data(
    stream_id: str, new_data: dict[str, object], tool_data: dict[str, object]
) -> None:
    """Append each tool-data entry and stream it to the frontend."""
    for tool_entry in list_bag(new_data, "tool_data"):
        entries = tool_data.get("tool_data")
        if not isinstance(entries, list):
            entries = []
            tool_data["tool_data"] = entries
        entries.append(tool_entry)
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
        )


async def publish_tool_output(
    stream_id: str, new_data: dict[str, object], tool_outputs: dict[str, str]
) -> None:
    """Capture a tool_output event for merging before save and stream it live."""
    if "tool_output" not in new_data:
        return
    output_data = new_data["tool_output"]
    if not isinstance(output_data, dict):
        return
    tool_call_id = output_data.get("tool_call_id")
    output = output_data.get("output")
    if tool_call_id and output:
        tool_outputs[tool_call_id] = output
    await stream_manager.publish_chunk(
        stream_id,
        f"data: {json.dumps({'tool_output': output_data})}\n\n",
    )
