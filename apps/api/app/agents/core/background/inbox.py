"""In-process inbox queues for inter-agent communication.

Each active stream gets one queue per layer. The notify_* tools look up
the queue by stream_id (from configurable) and push messages.
Notifier loops or pre-model hooks drain the queue on the receiving side.

Module-level dicts are intentionally in-process (not Redis) because
asyncio.Queue cannot cross process boundaries. The executor:busy Redis
key handles cross-process safety for multi-worker deployments.
"""

import asyncio
from typing import Optional

# stream_id → asyncio.Queue
_comms_inboxes: dict[str, asyncio.Queue] = {}
_executor_inboxes: dict[str, asyncio.Queue] = {}


# ── Comms Inbox (executor pushes, comms notifier reads) ─────────────


def register_comms_inbox(stream_id: str) -> asyncio.Queue:
    """Create and register a comms inbox queue for this stream."""
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
