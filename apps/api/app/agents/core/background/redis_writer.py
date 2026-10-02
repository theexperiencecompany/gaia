"""Sync-callable Redis stream writer for background executor execution.

When executor runs as a background asyncio task (outside LangGraph's
graph context), get_stream_writer() is unavailable. This provides a
sync callable that schedules async Redis publishes via asyncio.create_task.

Usage:
    writer = make_redis_stream_writer(stream_id)
    result = await execute_subagent_stream(ctx=ctx, stream_writer=writer)
"""

from collections.abc import Callable
import json
import time
from typing import TypedDict, cast

from app.agents.core.background.session import StreamSession, get_session
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.utils.background_tasks import spawn_background_task

#: Task name for the fire-and-forget stream publishes. Tests drain by this name
#: to wait out exactly the XADDs a turn scheduled, rather than every background
#: task in the process (some of which outlive any single turn).
STREAM_PUBLISH_TASK_NAME = "stream-publish"
from shared.py.wide_events import log


class _ReasoningDelta(TypedDict, total=False):
    """One reasoning frame's payload; the frames come from many writers, so values are unchecked."""

    subagent_id: object
    content: object


class _ReasoningFrame(TypedDict, total=False):
    """A stream frame as _collect reads it; every other key passes through untouched."""

    reasoning: object


def _reasoning_of(frame: object) -> _ReasoningDelta | None:
    """Return a frame's reasoning payload, or None when it carries none."""
    if not isinstance(frame, dict):
        return None
    typed: _ReasoningFrame = cast(_ReasoningFrame, frame)
    reasoning = typed.get("reasoning")
    return cast(_ReasoningDelta, reasoning) if isinstance(reasoning, dict) else None


def _collect(session: StreamSession, data: dict[str, object]) -> None:
    """Append an event to the session collector, coalescing reasoning deltas.

    Reasoning arrives one event per token and persists verbatim, which once
    grew one conversation to ~22k reasoning entries. Keeps ONE entry per
    contiguous run of thinking (any other event closes the block); same
    subagent_id only, so concurrent subagents never merge.
    """
    reasoning: _ReasoningDelta | None = _reasoning_of(data)
    if reasoning is None:
        session.tool_events.append(data)
        return
    previous: _ReasoningDelta | None = (
        _reasoning_of(session.tool_events[-1]) if session.tool_events else None
    )
    if previous is not None and previous.get("subagent_id") == reasoning.get("subagent_id"):
        previous["content"] = f"{previous.get('content', '')}{reasoning.get('content', '')}"
        return
    # A copy: the published dict belongs to the caller, and the merge above
    # mutates whatever is stored here on every subsequent delta.
    session.tool_events.append({"reasoning": dict(reasoning)})


async def publish_to_stream(stream_id: str, data: dict[str, object]) -> None:
    """Publish one event to a stream and its collector, awaited, so a caller sending many keeps their order."""
    await stream_manager.publish_chunk(stream_id, f"data: {json.dumps(data)}\n\n")
    session = get_session(stream_id)
    if session is not None:
        _collect(session, data)


def make_redis_stream_writer(stream_id: str) -> Callable[[dict[str, object]], None]:
    """Return a sync callable that publishes tool events directly to Redis.

    Matches the stream_writer protocol expected by execute_subagent_stream().
    Also appends each event to the session's tool-event collector (if
    registered); the SSE publish itself is unbatched, only the save-path
    copy is coalesced by _collect.
    """

    def writer(data: dict[str, object]) -> None:
        chunk = f"data: {json.dumps(data)}\n\n"
        try:
            spawn_background_task(
                stream_manager.publish_chunk(stream_id, chunk),
                name=STREAM_PUBLISH_TASK_NAME,
            )
        except RuntimeError:
            log.error(f"{LogTag.AGENT} redis_writer: no event loop for stream", stream_id=stream_id)

        session = get_session(stream_id)
        if session is not None:
            if session.executor_first_frame_perf is None:
                session.executor_first_frame_perf = time.perf_counter()
            _collect(session, data)

    return writer
