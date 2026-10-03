"""Per-conversation executor busy-lock mechanics and detached-run materialization.

One executor runs per conversation at a time, guarded by the
executor:busy:{conversation_id} Redis lock. Work that arrives while the lock is
held is not deferred — it goes to the conversation's inbox and the live run
absorbs it (see executor_channel). There is no queue of pending runs.

What remains here is the lock itself and prepare_run_from_item, which
materializes a DETACHED run that owns its own stream rather than sharing a comms
turn's. HIL approval resume and deliver_to_executor are its consumers.
Preparing is this module's job, spawning the runner's — the one-way dependency (runner -> queue) that keeps the import graph acyclic.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict, cast
from uuid import uuid4

from redis.exceptions import WatchError

from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    StreamSession,
    create_session,
    teardown_session,
)
from app.constants.cache import (
    EXECUTOR_ALIVE_PREFIX,
    EXECUTOR_ALIVE_TTL,
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.log_tags import LogTag
from app.constants.streaming import WS_EVENT_EXECUTOR_STREAM_STARTED, DetachedStreamKind
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.models.agent_models import (
    CONFIGURABLE_OWNED_KEYS,
    CONFIGURABLE_RUN_SCOPED_KEYS,
    AgentConfigurable,
)
from app.utils.general_utils import is_json_safe
from shared.py.wide_events import current_workflow_execution_id, log

# Cosmetic prefix for queued stream ids — kept for log greppability only.
# The run kind is carried explicitly on ExecutorRun, never parsed from the id.
QUEUED_STREAM_ID_PREFIX = "queued_"


class ExecutorRunItem(TypedDict, total=False):
    """The serialized run context stored between an executor turn and its re-dispatch.

    Written by build_run_item into the Redis queue and into
    HILApprovalRecord.resume_item; read back by prepare_run_from_item.

    total=False is the honest shape: the HIL resume path re-dispatches from
    record.resume_item or {}, so an absent or empty item is a real, handled
    input — every read below supplies a default.
    """

    task: str
    task_id: str | None
    configurable: AgentConfigurable
    conversation_id: str
    user_message_id: str | None
    # Original live turn's bot message id, set only by a HIL pause (_record_pause);
    # a plain queue enqueue never sets it. Read back into ExecutorRun.
    bot_message_id: str | None
    # Workflow execution the run belongs to. It lives only on the workflow task's
    # wide event, and a queue pop or HIL resume rebuilds the run elsewhere, so the
    # item is the only carrier across; read into ExecutorRun for attribution.
    workflow_execution_id: str | None


@dataclass(frozen=True)
class PreparedQueuedTask:
    """A queued task popped and fully prepared for spawning."""

    run: ExecutorRun
    task: str
    configurable: AgentConfigurable


# ── Busy lock ────────────────────────────────────────────────────────


class LockClaim(StrEnum):
    """How a new run takes the per-conversation busy lock.

    SEIZE   — take it from whoever holds it. Only a HIL approval resume, whose
              paused run deliberately holds the lock while it waits and whose
              process is long gone.
    ACQUIRE — start only on a conversation nobody holds, atomically (SET NX).
              Everything else: an unconditional SET let two detached runs start
              on one LangGraph thread, and the second one's write made the
              first's ownership-checked release a no-op, leaking the lock for
              its full TTL.
    """

    SEIZE = "seize"
    ACQUIRE = "acquire"


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


async def adopt_lock(conversation_id: str, reserved_value: str, lock_value: str) -> bool:
    """Take over a lock this run's own reservation holds; return whether it did.

    Compare-and-set under WATCH, not a plain SET: a reservation can lapse on TTL
    and be re-taken by a different run, and overwriting that would put two
    executors on one conversation. Falls back to True (allow execution) when
    Redis is unavailable, like try_acquire_lock.
    """
    if not redis_cache.client:
        return True
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    async with redis_cache.client.pipeline() as pipe:
        await pipe.watch(lock_key)
        if await pipe.get(lock_key) != reserved_value:
            return False
        pipe.multi()
        pipe.set(lock_key, lock_value, ex=EXECUTOR_BUSY_TTL)
        try:
            await pipe.execute()
        except WatchError:
            # Someone wrote the key between the read and the set; they own it now.
            return False
    return True


async def break_holder_lock(conversation_id: str, expected_value: str) -> bool:
    """Delete the busy lock only while it still carries expected_value.

    Compare-and-delete under WATCH: a live run that re-acquired between the read
    and the delete changes the value, so the delete aborts instead of stranding
    it. Returns whether the lock is gone; falls back to False when Redis is down.
    """
    if not redis_cache.client:
        return False
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    async with redis_cache.client.pipeline() as pipe:
        await pipe.watch(lock_key)
        if await pipe.get(lock_key) != expected_value:
            return False
        pipe.multi()
        pipe.delete(lock_key)
        try:
            await pipe.execute()
        except WatchError:
            return False
    return True


async def get_lock_state(conversation_id: str, stream_id: str, task_id: str | None) -> LockState:
    """Classify the busy lock relative to this run: OURS, FREE, or FOREIGN.

    OURS carries this run's value; FREE has no lock (reclaim only via NX);
    FOREIGN means a newer run owns it and a stale finalize must not touch it.
    Redis-unavailable degrades to OURS, the pre-ownership-check behavior.
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
    """Return the busy lock's current value, or None when no run holds it (or Redis is down)."""
    if not redis_cache.client:
        return None
    raw = await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    return None if raw is None else decode_raw_item(raw)


async def hold_run_alive(
    conversation_id: str, lock_value: str, ttl_seconds: int = EXECUTOR_ALIVE_TTL
) -> None:
    """Say the run holding lock_value lives, for ttl_seconds: what tells a busy lock from a dead one."""
    if redis_cache.client:
        await redis_cache.client.set(
            f"{EXECUTOR_ALIVE_PREFIX}{conversation_id}", lock_value, ex=ttl_seconds
        )


async def reclaim_dead_lock(conversation_id: str) -> bool:
    """Free a busy lock whose run died with its process; return whether no run holds the lock now.

    Dead takes evidence: the holder's liveness lapsed, and the lock is older than
    a run takes to start beating. Compare-and-delete, so a live re-acquire stands.
    """
    holder = await get_lock_holder(conversation_id)
    if holder is None:
        return True
    alive = await redis_cache.client.get(f"{EXECUTOR_ALIVE_PREFIX}{conversation_id}")
    if alive is not None and decode_raw_item(alive) == holder:
        return False
    remaining = await redis_cache.client.ttl(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    # Every lock this code takes expires: one without a TTL has no age to judge it by.
    if remaining < 0 or EXECUTOR_BUSY_TTL - remaining < EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS:
        return False
    log.warning(
        f"{LogTag.AGENT} Reclaimed the busy lock of an executor run that died",
        conversation_id=conversation_id,
        holder=holder,
    )
    return await break_holder_lock(conversation_id, holder)


async def is_executor_busy(conversation_id: str) -> bool:
    """Whether ANY executor run (running or parked) holds this conversation's lock.

    Redis-unavailable degrades to False, so deliver_to_executor attempts a run
    start, whose own claim then decides.
    """
    if not redis_cache.client:
        return False
    return await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}") is not None


async def release_lock_if_owned(conversation_id: str, stream_id: str, task_id: str | None) -> None:
    """Delete the busy lock only while this run still owns it.

    Unconditional deletion let a stale run's finalize free a lock a NEWER run
    had acquired, enabling concurrent executors in one conversation. The
    get-compare-delete here is not atomic but closes the deterministic case.
    """
    if await get_lock_state(conversation_id, stream_id, task_id) is LockState.OURS:
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")


async def extend_lock_if_owned(
    conversation_id: str, stream_id: str, task_id: str | None, ttl_seconds: int
) -> bool:
    """Re-arm the busy lock's TTL while this run still owns it; return whether it did.

    A run parked on a HIL approval may outlive its lock's TTL, and a lapse under
    a checkpointed interrupt lets a new run take the thread. Ownership-checked
    like release_lock_if_owned so a stale run never extends a newer one's lock.
    """
    if not redis_cache.client:
        return False
    if await get_lock_state(conversation_id, stream_id, task_id) is not LockState.OURS:
        return False
    return bool(
        await redis_cache.client.expire(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}", ttl_seconds)
    )


def decode_raw_item(raw: bytes | memoryview | str) -> str:
    """Decode a raw Redis list item to a string."""
    if isinstance(raw, str):
        return raw
    return bytes(raw).decode()


# ── Pop + prepare ────────────────────────────────────────────────────


def build_run_item(
    *,
    task: str,
    configurable: AgentConfigurable,
    identity: RunIdentity,
    workflow_execution_id: str | None = None,
) -> ExecutorRunItem:
    """Build the one serialized run-context shape the queue and HIL resume store write.

    Read back by prepare_run_from_item; add fields here, not at the write sites,
    or a resumed run silently drops what a queued run keeps. workflow_execution_id
    defaults to the execution in flight on the caller's wide event.
    """
    return {
        "task": task,
        "task_id": identity.task_id,
        "configurable": safe_configurable(configurable),
        "conversation_id": identity.conversation_id,
        "user_message_id": identity.user_message_id,
        "bot_message_id": identity.bot_message_id,
        "workflow_execution_id": workflow_execution_id or current_workflow_execution_id(),
    }


def safe_configurable(configurable: AgentConfigurable) -> AgentConfigurable:
    """Return the serializable subset of a configurable, safe to persist and rebuild from.

    The GAIA-owned keys minus the run-scoped ones. A declared key holding an
    unserializable value is dropped with a WARNING, never silently — silent
    dropping is how a queued run quietly stopped being the run the user started.
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


async def open_detached_stream(
    stream_id: str,
    *,
    conversation_id: str,
    user_id: str,
    task_id: str | None,
    bot_message_id: str | None,
    kind: DetachedStreamKind,
) -> StreamSession:
    """Mint a stream a detached run owns and announce it with executor.stream_started.

    The one way a run with no comms turn reaches the client: a session collects its
    frames for persistence, and the client folds the stream into bot_message_id's
    message when given, else into a placeholder keyed by task_id.
    """
    # Equivalent under mutation: session.kind is only read as `is RunKind.LIVE` (hil/bridge).
    session = create_session(stream_id, RunKind.QUEUED)  # pragma: no mutate
    await StreamManager.start_stream(
        stream_id=stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    if user_id:
        await websocket_manager.broadcast_to_user(
            user_id,
            {
                "type": WS_EVENT_EXECUTOR_STREAM_STARTED,
                "stream_id": stream_id,
                "conversation_id": conversation_id,
                "task_id": task_id,
                "bot_message_id": bot_message_id,
                "kind": kind.value,
            },
        )
    return session


async def close_detached_stream(stream_id: str, *, cancelled: bool) -> None:
    """Drop a detached run's session and end the stream it owns.

    A cancelled stream closes silently — the cancel already told the client — so
    no [DONE] and no complete_stream.
    """
    teardown_session(stream_id)
    if not cancelled:
        await StreamManager.publish_chunk(stream_id, "data: [DONE]\n\n")
        await StreamManager.complete_stream(stream_id)


async def prepare_run_from_item(
    conversation_id: str, item: ExecutorRunItem, *, claim: LockClaim
) -> PreparedQueuedTask | None:
    """Claim the busy lock and prepare a fresh run+stream from a stored item.

    Every detached run starts here, so this is the single place the conversation
    is claimed and the frontend's stream is minted. claim picks which claim
    applies (see LockClaim); None means the conversation is already taken.
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
    lock_value = build_lock_value(queued_stream_id, task_id or "")
    if claim is LockClaim.ACQUIRE:
        if not await try_acquire_lock(lock_key, lock_value):
            log.info(
                f"{LogTag.AGENT} Conversation already has a running executor; no run started",
                conversation_id=conversation_id,
            )
            return None
    else:
        # Seize with the RAW client: redis_cache.set() JSON-encodes (quotes) the
        # value, which get_lock_state's raw read never matches, so the resumed run
        # would see its own lock as FOREIGN and wedge it until TTL.
        await redis_cache.client.set(lock_key, lock_value, ex=EXECUTOR_BUSY_TTL)

    session = await open_detached_stream(
        queued_stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
        task_id=task_id,
        # A HIL resume continues the ORIGINAL turn's message: the client folds
        # this stream into it instead of opening a second placeholder (which
        # would render its own tool accordion).
        bot_message_id=queued_bot_message_id,
        kind=DetachedStreamKind.EXECUTOR,
    )
    session.executor_spawned = True

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
        workflow_execution_id=item.get("workflow_execution_id"),
    )
    return PreparedQueuedTask(run=run, task=task, configurable=configurable)
