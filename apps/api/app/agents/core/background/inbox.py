"""In-process inbox queues for inter-agent communication.

Each active stream gets one queue per layer. The notify_* tools look up
the queue by stream_id (from configurable) and push messages.
Notifier loops or pre-model hooks drain the queue on the receiving side.

Module-level dicts are intentionally in-process (not Redis) because
asyncio.Queue cannot cross process boundaries. The executor:busy Redis
key handles cross-process safety for multi-worker deployments.
"""

import asyncio
import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

# stream_id → asyncio.Queue
_comms_inboxes: dict[str, asyncio.Queue] = {}
_executor_inboxes: dict[str, asyncio.Queue] = {}

# Streams for which call_executor successfully spawned a background task.
# Set synchronously in call_executor (before the asyncio.Task starts) so
# chat_service can reliably detect whether THIS stream needs a notifier —
# as opposed to checking the per-conversation Redis lock which stays set
# for the lifetime of the executor and would mislead concurrent streams.
_executor_spawned_streams: set[str] = set()


# ── Comms Inbox (executor pushes, comms notifier reads) ─────────────


def register_comms_inbox(stream_id: str) -> asyncio.Queue:
    """Create and register a comms inbox queue for this stream.

    If a stale queue exists for this stream_id (e.g. a retried request while
    a previous background task is still running), drain and discard it to
    prevent old messages from reaching the new notifier.
    """
    existing = _comms_inboxes.get(stream_id)
    if existing is not None and not existing.empty():
        _log.warning(
            "register_comms_inbox: stale non-empty queue for stream %s — draining",
            stream_id,
        )
        while True:
            try:
                existing.get_nowait()
            except asyncio.QueueEmpty:
                break
    queue: asyncio.Queue = asyncio.Queue()
    _comms_inboxes[stream_id] = queue
    return queue


def get_comms_inbox(stream_id: str) -> Optional[asyncio.Queue]:
    """Return the comms inbox for a stream, or None."""
    return _comms_inboxes.get(stream_id)


def deregister_comms_inbox(stream_id: str) -> None:
    """Remove the comms inbox. Safe to call multiple times."""
    _comms_inboxes.pop(stream_id, None)


# ── Executor Inbox (subagents push, executor pre_model_hook reads) ──


def register_executor_inbox(stream_id: str) -> asyncio.Queue:
    """Create and register an executor inbox queue for this stream."""
    queue: asyncio.Queue = asyncio.Queue()
    _executor_inboxes[stream_id] = queue
    return queue


def get_executor_inbox(stream_id: str) -> Optional[asyncio.Queue]:
    """Return the executor inbox for a stream, or None."""
    return _executor_inboxes.get(stream_id)


def deregister_executor_inbox(stream_id: str) -> None:
    """Remove the executor inbox. Safe to call multiple times."""
    _executor_inboxes.pop(stream_id, None)


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


# ── Per-stream executor-spawned flag ────────────────────────────────
# Distinguishes "executor running for THIS stream" from "executor running
# for some other stream in the same conversation" so concurrent streams
# don't erroneously start a notifier that will never receive messages.


def mark_executor_spawned(stream_id: str) -> None:
    """Record that call_executor spawned a background task for this stream."""
    _executor_spawned_streams.add(stream_id)


def was_executor_spawned(stream_id: str) -> bool:
    """Return True if call_executor successfully spawned for this stream."""
    return stream_id in _executor_spawned_streams


def deregister_executor_spawned(stream_id: str) -> None:
    """Remove the spawned flag. Safe to call multiple times."""
    _executor_spawned_streams.discard(stream_id)


# ── Executor tool event collector ────────────────────────────────────
# make_redis_stream_writer appends raw tool event dicts here so
# chat_service can capture executor tool_data / tool_output /
# todo_progress for MongoDB persistence after run_comms_notifier returns.
# The events are ALREADY published to the SSE stream by the writer —
# the collector only captures them for the save path, not re-publishing.

_executor_tool_event_collectors: dict[str, list[dict[str, Any]]] = {}


def register_tool_event_collector(stream_id: str) -> list[dict[str, Any]]:
    """Create and register a tool event collector list for this stream."""
    collector: list[dict[str, Any]] = []
    _executor_tool_event_collectors[stream_id] = collector
    return collector


def get_tool_event_collector(stream_id: str) -> Optional[list[dict[str, Any]]]:
    """Return the tool event collector for a stream, or None."""
    return _executor_tool_event_collectors.get(stream_id)


def deregister_tool_event_collector(stream_id: str) -> None:
    """Remove the tool event collector. Safe to call multiple times."""
    _executor_tool_event_collectors.pop(stream_id, None)
