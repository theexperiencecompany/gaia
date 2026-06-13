"""In-process orchestration state for background executor + subagents.

Despite the legacy filename, this module no longer holds inter-agent
inbox queues — those were removed when the internal messaging system
was ripped out (Claude Code-style: agents don't push messages into
each other's prompt context). What remains is per-stream orchestration
state needed to coordinate background tasks with the chat stream and
the SSE/WebSocket layer.

Module-level dicts are intentionally in-process (not Redis) because
asyncio primitives cannot cross process boundaries. The
executor:busy Redis key handles cross-process safety for multi-worker
deployments.
"""

import asyncio
from typing import Any

# ── Per-stream "executor was spawned" flag ─────────────────────────
# Distinguishes "executor running for THIS stream" from "executor running
# for some other stream in the same conversation" so concurrent streams
# don't erroneously wait for an executor that will never report to them.
_executor_spawned_streams: set[str] = set()


def mark_executor_spawned(stream_id: str) -> None:
    """Record that call_executor spawned a background task for this stream."""
    _executor_spawned_streams.add(stream_id)


def was_executor_spawned(stream_id: str) -> bool:
    """Return True if call_executor successfully spawned for this stream."""
    return stream_id in _executor_spawned_streams


def deregister_executor_spawned(stream_id: str) -> None:
    """Remove the spawned flag. Safe to call multiple times."""
    _executor_spawned_streams.discard(stream_id)


# ── Executor done events ────────────────────────────────────────────
# Live chat streams need to know when the background executor finishes
# so they can publish [DONE] and close the SSE connection. The executor
# sets this event in its finally block.

_executor_done_events: dict[str, asyncio.Event] = {}


def register_executor_done_event(stream_id: str) -> asyncio.Event:
    """Create and register the executor-done event for this stream."""
    event = asyncio.Event()
    _executor_done_events[stream_id] = event
    return event


def get_executor_done_event(stream_id: str) -> asyncio.Event | None:
    """Return the executor-done event, or None if not registered."""
    return _executor_done_events.get(stream_id)


def deregister_executor_done_event(stream_id: str) -> None:
    """Remove the executor-done event. Safe to call multiple times."""
    _executor_done_events.pop(stream_id, None)


# ── Pending background subagent counter ─────────────────────────────
# Incremented by handoff(background=True), decremented by run_subagent_background.
# wait_for_subagents uses this to know when all background subagents are done.

_pending_bg_subagents: dict[str, int] = {}


def increment_pending_subagents(stream_id: str) -> int:
    """Increment pending background subagent count. Returns new count."""
    _pending_bg_subagents[stream_id] = _pending_bg_subagents.get(stream_id, 0) + 1
    return _pending_bg_subagents[stream_id]


def decrement_pending_subagents(stream_id: str) -> int:
    """Decrement pending background subagent count. Returns new count (min 0)."""
    count = max(0, _pending_bg_subagents.get(stream_id, 0) - 1)
    _pending_bg_subagents[stream_id] = count
    return count


def get_pending_subagents(stream_id: str) -> int:
    """Return number of pending background subagents for a stream."""
    return _pending_bg_subagents.get(stream_id, 0)


def deregister_pending_subagents(stream_id: str) -> None:
    """Remove pending counter. Safe to call multiple times."""
    _pending_bg_subagents.pop(stream_id, None)


# ── Background subagent results ─────────────────────────────────────
# Background subagents (handoff with background=True) run independently
# and write their final result text here, keyed by stream_id. The
# wait_for_subagents tool drains this dict to return collected results
# to the executor. Replaces the previous executor-inbox push pattern.

_bg_subagent_results: dict[str, list[dict[str, str]]] = {}


def append_bg_subagent_result(stream_id: str, agent: str, result: str) -> None:
    """Append a background subagent's final result for this stream."""
    _bg_subagent_results.setdefault(stream_id, []).append({"agent": agent, "message": result})


def drain_bg_subagent_results(stream_id: str) -> list[dict[str, str]]:
    """Return and clear all collected background subagent results for this stream."""
    return _bg_subagent_results.pop(stream_id, [])


def deregister_bg_subagent_results(stream_id: str) -> None:
    """Drop any uncollected background subagent results. Safe to call multiple times."""
    _bg_subagent_results.pop(stream_id, None)


# ── Executor tool event collector ────────────────────────────────────
# make_redis_stream_writer appends raw tool event dicts here so the
# executor's finalize step can persist accumulated tool_data on the
# bot message it saves. Events are ALREADY published to the SSE stream
# by the writer — the collector only captures them for the save path.

_executor_tool_event_collectors: dict[str, list[dict[str, Any]]] = {}


def register_tool_event_collector(stream_id: str) -> list[dict[str, Any]]:
    """Create and register a tool event collector list for this stream."""
    collector: list[dict[str, Any]] = []
    _executor_tool_event_collectors[stream_id] = collector
    return collector


def get_tool_event_collector(stream_id: str) -> list[dict[str, Any]] | None:
    """Return the tool event collector for a stream, or None."""
    return _executor_tool_event_collectors.get(stream_id)


def deregister_tool_event_collector(stream_id: str) -> None:
    """Remove the tool event collector. Safe to call multiple times."""
    _executor_tool_event_collectors.pop(stream_id, None)
