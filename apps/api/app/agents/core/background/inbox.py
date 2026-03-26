"""In-process inbox queues for inter-agent communication.

Each active stream gets one queue per layer. The notify_* tools look up
the queue by stream_id (from configurable) and push messages.
Notifier loops or pre-model hooks drain the queue on the receiving side.

Module-level dicts are intentionally in-process (not Redis) because
asyncio.Queue cannot cross process boundaries. The executor:busy Redis
key handles cross-process safety for multi-worker deployments.
"""

import asyncio
from typing import Any, Optional

# stream_id → asyncio.Queue
_comms_inboxes: dict[str, asyncio.Queue[Any]] = {}
_executor_inboxes: dict[str, asyncio.Queue[Any]] = {}


# ── Comms Inbox (executor pushes, comms notifier reads) ─────────────


def register_comms_inbox(stream_id: str) -> asyncio.Queue[Any]:
    """Create and register a comms inbox queue for this stream."""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    _comms_inboxes[stream_id] = queue
    return queue


def get_comms_inbox(stream_id: str) -> Optional[asyncio.Queue[Any]]:
    """Return the comms inbox for a stream, or None."""
    return _comms_inboxes.get(stream_id)


def deregister_comms_inbox(stream_id: str) -> None:
    """Remove the comms inbox. Safe to call multiple times."""
    _comms_inboxes.pop(stream_id, None)


# ── Executor Inbox (subagents push, executor pre_model_hook reads) ──


def register_executor_inbox(stream_id: str) -> asyncio.Queue[Any]:
    """Create and register an executor inbox queue for this stream."""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    _executor_inboxes[stream_id] = queue
    return queue


def get_executor_inbox(stream_id: str) -> Optional[asyncio.Queue[Any]]:
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
