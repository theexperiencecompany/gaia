"""The per-conversation lock every writer of a comms LangGraph thread takes.

A run reads the thread's checkpoint when it starts and writes its own on the way out,
so any write landing in between forks the checkpoint and the run's write buries it.
Writers queue here instead: the interactive turn, the silent runs, and every
out-of-band aupdate_state.
"""

from collections.abc import AsyncIterator
import contextlib

from app.constants.cache import (
    COMMS_THREAD_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    COMMS_THREAD_LOCK_LEASE_SECONDS,
    COMMS_THREAD_LOCK_MAX_HOLD_SECONDS,
    COMMS_THREAD_LOCK_PREFIX,
    COMMS_THREAD_LOCK_RENEW_SECONDS,
)
from app.constants.log_tags import LogTag
from app.utils.redis_lock import DistributedLock
from shared.py.wide_events import log


class CommsThreadLockTimeout(RuntimeError):
    """A writer could not take a conversation's comms-thread lock; it must not write unlocked."""


@contextlib.asynccontextmanager
async def comms_thread_lock(conversation_id: str) -> AsyncIterator[None]:
    """Hold the conversation's comms-thread lock for the block, or raise CommsThreadLockTimeout."""
    lock = DistributedLock(
        f"{COMMS_THREAD_LOCK_PREFIX}{conversation_id}",
        lease_seconds=COMMS_THREAD_LOCK_LEASE_SECONDS,
        acquire_timeout_seconds=COMMS_THREAD_LOCK_ACQUIRE_TIMEOUT_SECONDS,
        renew_seconds=COMMS_THREAD_LOCK_RENEW_SECONDS,
        max_hold_seconds=COMMS_THREAD_LOCK_MAX_HOLD_SECONDS,
    )
    async with lock.hold() as held:
        if not held:
            log.error(
                f"{LogTag.LOCK} Comms thread lock not acquired", conversation_id=conversation_id
            )
            raise CommsThreadLockTimeout(conversation_id)
        yield
