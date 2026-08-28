"""Per-conversation executor queue and busy-lock mechanics.

One executor runs per conversation at a time, guarded by the
``executor:busy:{conversation_id}`` Redis lock. While the lock is held,
``call_executor`` enqueues additional tasks onto
``executor:queue:{conversation_id}``; when a run finishes, its finalize step
pops the next task here and spawns it.

This module owns the Redis mechanics only — enqueue, pop/prepare, and lock
value handling. ``pop_next_queued_run`` PREPARES the next run (lock overwrite,
session registration, stream start, ``executor.stream_started`` WS event) and
returns it; the runner spawns it. That one-way dependency (runner → queue)
keeps the import graph acyclic.
"""

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, TypedDict, cast
from uuid import uuid4

from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    create_session,
)
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_QUEUE_PREFIX,
    EXECUTOR_QUEUE_TTL,
)
from app.constants.executor import (
    CONFIGURABLE_OWNED_KEYS,
    CONFIGURABLE_RUN_SCOPED_KEYS,
    EXECUTOR_COLLECT_MARKER_PREFIX,
    EXECUTOR_COLLECT_MARKER_TTL,
    EXECUTOR_COLLECTION_TASK,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable
from app.utils.general_utils import is_json_safe
from shared.py.wide_events import log

# Cosmetic prefix for queued stream ids — kept for log greppability only.
# The run kind is carried explicitly on ExecutorRun, never parsed from the id.
QUEUED_STREAM_ID_PREFIX = "queued_"


class ExecutorRunItem(TypedDict, total=False):
    """The serialized run context stored between an executor turn and its re-dispatch.

    Written by :func:`build_run_item` into the Redis queue and into
    ``HILApprovalRecord.resume_item``; read back by :func:`prepare_run_from_item`.

    ``total=False`` is the honest shape, not a shortcut: the HIL resume path
    re-dispatches from ``record.resume_item or {}``, so an absent or empty item
    is a real, handled input — every read below supplies a default.
    """

    task: str
    task_id: str | None
    configurable: AgentConfigurable
    conversation_id: str
    user_message_id: str | None
    #: The original live turn's bot message id, set only when this item was
    #: written by a HIL pause (``_record_pause``) — a plain queue enqueue never
    #: sets it. Read back by ``prepare_run_from_item`` into ``ExecutorRun``.
    bot_message_id: str | None


@dataclass(frozen=True)
class PreparedQueuedTask:
    """A queued task popped and fully prepared for spawning."""

    run: ExecutorRun
    task: str
    configurable: AgentConfigurable


# ── Busy lock ────────────────────────────────────────────────────────


class LockState(StrEnum):
    """Who currently holds the per-conversation executor busy lock."""

    OURS = "ours"
    FREE = "free"
    FOREIGN = "foreign"


def build_lock_value(stream_id: str | None, task_id: str) -> str:
    """Build 'stream_id:task_id' lock value for the executor busy key."""
    return f"{stream_id or ''}:{task_id}"


def parse_lock_value(lock_value: str) -> tuple[str, str]:
    """Parse 'stream_id:task_id' from the executor busy lock value."""
    if ":" in lock_value:
        stream_id, task_id = lock_value.split(":", 1)
        return stream_id, task_id
    return lock_value, ""


async def try_acquire_lock(lock_key: str, lock_value: str) -> bool:
    """Atomically acquire the executor lock via SET NX.

    Returns True if the lock was acquired, False if already held.
    Falls back to True (allow execution) if Redis is unavailable.
    """
    if not redis_cache.client:
        return True
    return bool(
        await redis_cache.client.set(
            lock_key,
            lock_value,
            ex=EXECUTOR_BUSY_TTL,
            nx=True,
        ),
    )


async def get_lock_state(conversation_id: str, stream_id: str, task_id: str | None) -> LockState:
    """Classify the busy lock relative to this run.

    OURS    — the lock still carries this run's value; we may pop/release.
    FREE    — no lock (TTL expiry, or cancel_executor released it); a stranded
              queue may need reclaiming, but only via NX so we never trample a
              concurrent acquirer.
    FOREIGN — a newer run owns it; a stale finalize must not touch the lock or
              the queue (the owner's own finalize drains it).

    Redis-unavailable degrades to OURS — the pre-ownership-check behavior.
    """
    if not redis_cache.client:
        return LockState.OURS
    holder = await get_lock_holder(conversation_id)
    if holder is None:
        return LockState.FREE
    if holder == build_lock_value(stream_id, task_id or ""):
        return LockState.OURS
    return LockState.FOREIGN


async def get_lock_holder(conversation_id: str) -> str | None:
    """The busy lock's current value, or None when no run holds it (or Redis is down)."""
    if not redis_cache.client:
        return None
    raw = await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    return None if raw is None else decode_raw_item(raw)


async def is_executor_busy(conversation_id: str) -> bool:
    """Whether ANY executor run (running or parked) holds this conversation's lock.

    Redis-unavailable degrades to ``False``: the caller (HIL early-decision) must
    treat "cannot tell" as "no collector is alive" and fail closed — recording a
    decision nobody will act on is a false promise to the user.
    """
    if not redis_cache.client:
        return False
    return await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}") is not None


async def release_lock_if_owned(conversation_id: str, stream_id: str, task_id: str | None) -> None:
    """Delete the busy lock only while this run still owns it.

    Unconditional deletion let a stale (e.g. cancelled-then-replaced) run's
    finalize free a lock a NEWER run had acquired, enabling concurrent
    executors in one conversation. The get→compare→delete here is not atomic,
    but it closes the deterministic case; the residual window is the
    microseconds between compare and delete.
    """
    if await get_lock_state(conversation_id, stream_id, task_id) is LockState.OURS:
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")


async def extend_lock_if_owned(
    conversation_id: str, stream_id: str, task_id: str | None, ttl_seconds: int
) -> bool:
    """Re-arm the busy lock's TTL while this run still owns it.

    For a run that parks on a HIL approval: its lock's TTL has been counting down
    since the run *started*, but the pause may outlive it, and a lock that lapses
    under a checkpointed interrupt lets a new run take the thread and discard it.
    Ownership-checked like ``release_lock_if_owned`` — a stale run must never
    extend a lock a newer one now holds. Returns whether the TTL was re-armed.
    """
    if not redis_cache.client:
        return False
    if await get_lock_state(conversation_id, stream_id, task_id) is not LockState.OURS:
        return False
    return bool(
        await redis_cache.client.expire(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}", ttl_seconds)
    )


async def reclaim_stranded_task(conversation_id: str) -> PreparedQueuedTask | None:
    """Claim a free lock and pop a task that would otherwise strand.

    Two ways a queued task ends up with no lock holder to drain it:
      - a call_executor enqueued in the race window between finalize's empty
        pop and its lock release;
      - cancel_executor freed the lock while tasks remained queued.
    Without a reclaim pass the task sits in Redis until the next executor run
    for that conversation — or silently expires with the queue TTL.

    NX-claims the lock with a sentinel first, so a concurrent call_executor
    acquirer always wins cleanly (their finalize will drain the queue instead).
    The sentinel parses as a harmless no-op for cancel_executor. A task
    enqueued after this pass's empty pop re-enters the same (vanishingly
    rare) race; the next executor run drains it.
    """
    if not redis_cache.client:
        return None
    if await redis_cache.client.llen(f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}") == 0:
        return None
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    if not await try_acquire_lock(lock_key, build_lock_value("reclaim", str(uuid4()))):
        return None
    prepared = await pop_next_queued_run(conversation_id)
    if prepared is None:
        # We hold only the sentinel — free it so call_executor isn't blocked.
        await redis_cache.delete(lock_key)
    return prepared


# ── Enqueue ──────────────────────────────────────────────────────────


async def enqueue_task(
    queue_key: str,
    task: str,
    task_id: str,
    configurable: AgentConfigurable,
    conversation_id: str,
    user_message_id: str | None,
) -> None:
    """Push a task to the executor queue for deferred execution."""
    queue_item = json.dumps(
        build_run_item(
            task=task,
            task_id=task_id,
            configurable=configurable,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
        )
    )
    if redis_cache.client:
        await redis_cache.client.rpush(queue_key, queue_item)
        await redis_cache.client.expire(queue_key, EXECUTOR_QUEUE_TTL)


async def enqueue_collection_run(
    conversation_id: str, base_configurable: AgentConfigurable
) -> bool:
    """Queue a wake-up turn to collect landed background-subagent work.

    The "rest" contract: an executor may end its turn while background subagents
    are still running; when their work lands (result or HIL park) with no
    executor alive to collect it, this queues a fresh turn whose task is to join
    and report. The SETNX marker keeps it to one queued collection at a time —
    the join clears it when it actually runs. Returns whether a run was queued.

    ``thread_id`` is forced back to the conversation id: a subagent's
    configurable carries the SUBAGENT thread, and the collection turn must run
    on the executor's own thread.
    """
    if not redis_cache.client:
        return False
    marker = f"{EXECUTOR_COLLECT_MARKER_PREFIX}{conversation_id}"
    claimed = await redis_cache.client.set(marker, "1", nx=True, ex=EXECUTOR_COLLECT_MARKER_TTL)
    if not claimed:
        return False
    configurable: AgentConfigurable = {
        **safe_configurable(base_configurable),
        "thread_id": conversation_id,
        "execution_mode": "interactive",
    }
    configurable.pop("subagent_id", None)
    await enqueue_task(
        queue_key=f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}",
        task=EXECUTOR_COLLECTION_TASK,
        task_id=str(uuid4()),
        configurable=configurable,
        conversation_id=conversation_id,
        user_message_id=None,
    )
    log.info(
        f"{LogTag.AGENT} Queued background-subagent collection turn",
        conversation_id=conversation_id,
    )
    return True


async def clear_collection_marker(conversation_id: str) -> None:
    """A join is running — future landings may queue a fresh collection turn."""
    if redis_cache.client:
        await redis_cache.client.delete(f"{EXECUTOR_COLLECT_MARKER_PREFIX}{conversation_id}")


def decode_raw_item(raw: bytes | memoryview | str) -> str:
    """Decode a raw Redis list item to a string."""
    if isinstance(raw, str):
        return raw
    return bytes(raw).decode()


# ── Pop + prepare ────────────────────────────────────────────────────


async def pop_next_queued_run(conversation_id: str) -> PreparedQueuedTask | None:
    """Pop the next queued task for this conversation and prepare it for spawning.

    Called from the runner's finalize step. Overwrites the executor busy lock
    with the next task's value (no intervening delete) before returning, so the
    queued run inherits the lock atomically and a concurrent call_executor
    cannot acquire it via SET NX in a delete→re-set gap.

    Registers the QUEUED session (with the executor pre-marked spawned — queued
    runs have no chat_service to register for them), starts stream progress
    tracking, and broadcasts ``executor.stream_started`` so the frontend opens a
    live SSE subscription. Spawning is the caller's job.

    Returns None if the queue was empty or unparseable (caller releases the lock).
    """
    if not redis_cache.client:
        return None

    queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
    raw = await redis_cache.client.lpop(queue_key)
    if not raw:
        return None

    try:
        item: ExecutorRunItem = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(
            f"{LogTag.AGENT} Failed to parse queued executor task",
            conversation_id=conversation_id,
            error=str(e),
        )
        return None

    return await prepare_run_from_item(conversation_id, item)


def build_run_item(
    *,
    task: str,
    task_id: str | None,
    configurable: AgentConfigurable,
    conversation_id: str,
    user_message_id: str | None,
    bot_message_id: str | None = None,
) -> ExecutorRunItem:
    """The one serialized run-context shape: written by the queue and the HIL
    resume store, read back by ``prepare_run_from_item``. Add fields here, not
    at the write sites, or a resumed run silently drops what a queued run keeps."""
    return {
        "task": task,
        "task_id": task_id,
        "configurable": safe_configurable(configurable),
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "bot_message_id": bot_message_id,
    }


def safe_configurable(configurable: AgentConfigurable) -> AgentConfigurable:
    """The serializable subset of a ``configurable``, safe to persist and rebuild
    a run from — the GAIA-owned keys minus the run-scoped ones.

    Every surviving key is an ``AgentConfigurable`` key by construction (Type
    Safety item 12). A declared key holding an unserializable value is dropped
    with a WARNING rather than in silence: silent dropping is how a queued run
    quietly stopped being the run the user started.
    """
    kept: dict[str, Any] = {}
    for key, value in configurable.items():
        if key not in CONFIGURABLE_OWNED_KEYS or key in CONFIGURABLE_RUN_SCOPED_KEYS:
            continue
        if not is_json_safe(value):
            log.warning(
                f"{LogTag.AGENT} Dropping unserializable configurable key from a queued run",
                configurable_key=key,
                value_type=type(value).__name__,
            )
            continue
        kept[key] = value
    return cast(AgentConfigurable, kept)


async def prepare_run_from_item(
    conversation_id: str, item: ExecutorRunItem
) -> PreparedQueuedTask | None:
    """Take over the busy lock and prepare a fresh run+stream from a stored item.

    Shared by the queue pop and the HIL approval resume: both re-dispatch a run
    whose original owner is gone, so both must seize the lock rather than acquire
    it, and both need their own stream for the frontend to subscribe to.
    """
    if not redis_cache.client:
        return None

    task = item.get("task", "")
    task_id = item.get("task_id")
    queued_user_message_id = item.get("user_message_id")
    queued_bot_message_id = item.get("bot_message_id")
    configurable: AgentConfigurable = item.get("configurable") or {}

    queued_stream_id = f"{QUEUED_STREAM_ID_PREFIX}{uuid4()}"
    user_id: str = configurable.get("user_id", "")

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    # Overwrite the busy lock with this queued run's value using the RAW client,
    # matching try_acquire_lock / get_lock_state. redis_cache.set() JSON-encodes
    # the string (wrapping it in quotes), which get_lock_state's raw read would
    # never match — so the queued run would see its own lock as FOREIGN, strand
    # the queue, and leave the lock wedged until its TTL.
    await redis_cache.client.set(
        lock_key,
        build_lock_value(queued_stream_id, task_id or ""),
        ex=EXECUTOR_BUSY_TTL,
    )

    session = create_session(queued_stream_id, RunKind.QUEUED)
    session.executor_spawned = True

    await StreamManager.start_stream(
        stream_id=queued_stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    if user_id:
        await websocket_manager.broadcast_to_user(
            user_id,
            {
                "type": "executor.stream_started",
                "stream_id": queued_stream_id,
                "conversation_id": conversation_id,
                "task_id": task_id,
                # A HIL resume continues the ORIGINAL turn's message: the client
                # folds this stream into it instead of opening a second
                # placeholder (which would render its own tool accordion).
                "bot_message_id": item.get("bot_message_id"),
            },
        )

    configurable = {**configurable, "stream_id": queued_stream_id}
    run = ExecutorRun.from_configurable(
        configurable,
        identity=RunIdentity(
            stream_id=queued_stream_id,
            conversation_id=conversation_id,
            kind=RunKind.QUEUED,
            task_id=task_id,
            user_message_id=queued_user_message_id,
            bot_message_id=queued_bot_message_id,
        ),
    )
    return PreparedQueuedTask(run=run, task=task, configurable=configurable)
