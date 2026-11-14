"""The ConversationLog port on Mongo (the head and conversation_entries) and Redis (liveness and the hint).

The head's conditional writes are the truth: seq order, the fold, and the epoch fence. Redis
holds what may lapse: an epoch's alive key proves its holder lives, and the hint is the
advisory preempt view, rebuilt from the head whenever it is missing.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import random

from redis.exceptions import RedisError

from app.constants.chat import CONVERSATION_APPEND_JITTER_SECONDS, CONVERSATION_APPEND_MAX_ATTEMPTS
from app.constants.conversation import (
    HINT_KEY_PREFIX,
    HINT_TTL_SECONDS,
    RUNNER_ALIVE_KEY_PREFIX,
    RUNNER_ALIVE_TTL_SECONDS,
    HintField,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.conversation_entries import stored_at
from app.db.repositories.conversation_log import (
    ConversationLogRepository,
    LogHead,
)
from app.models.conversation_log_models import (
    BargeIn,
    CommsPhase,
    ConversationState,
    Entry,
    KickStep,
    LoggedEntry,
    Notice,
    PreemptHint,
    Reaction,
    Rejected,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StepClaim,
    TodoWoke,
    UserMessage,
)
from app.services.conversation.ports import Appended, ClaimLost, EntryRejected, Unsettled
from app.services.conversation.reducer import reduce
from app.utils.errors import (
    ConversationEntryNotFoundError,
    ConversationNotFoundError,
    ConversationStoreError,
)
from shared.py.wide_events import log

_JITTER = random.SystemRandom()
# Raises the hint only past what it already holds, so a slower write of an older value never lands over a newer one.
_RAISE_HINT = """
local held = tonumber(redis.call('HGET', KEYS[1], ARGV[1]))
if held and held >= tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2], unpack(ARGV, 4))
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
_HINT_REQUIRED = (HintField.HEAD, HintField.STOP, HintField.EPOCH)


class MongoConversationLog:
    """The ConversationLog port over the conversation repository, stamping entries with clock."""

    def __init__(
        self, repository: ConversationLogRepository, clock: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        """Store entry at the next seq; the same id again returns the stored entry as a duplicate, with the current state and no effects."""
        return await self._append(conversation_id, user_id, entry, epoch=None)

    async def append_fenced(self, claim: StepClaim, entry: Entry) -> Appended:
        """Append only while claim holds the current epoch; raise ClaimLost otherwise."""
        return await self._append(claim.conversation_id, claim.user_id, entry, epoch=claim.epoch)

    async def amend(self, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        """Replace the stored entry with entry's id in place at its next revision, fenced; never a state change."""
        found = await self._repository.read_log(
            claim.conversation_id, user_id=claim.user_id, ids=[entry.id]
        )
        if found is None:
            raise _not_found(claim.conversation_id)
        stored = found[0] if found else None
        previous = None if stored is None else stored.entry
        if (
            stored is None
            or not isinstance(previous, Reply | UserMessage)
            or type(previous) is not type(entry)
        ):
            raise ConversationEntryNotFoundError(
                message=f"no {entry.kind} entry {entry.id} in conversation {claim.conversation_id}",
                meta={"conversation_id": claim.conversation_id, "entry_id": entry.id},
            )
        # A pin is the user's, set beside the step: a fill never takes it back.
        revised = entry.model_copy(
            update={"revision": previous.revision + 1, "pinned": previous.pinned}
        )
        amended = stored.model_copy(update={"entry": revised})
        if not await self._repository.stage_log_amend(
            claim.conversation_id, user_id=claim.user_id, epoch=claim.epoch, amended=amended
        ):
            raise ClaimLost
        return amended

    async def react_once(
        self, conversation_id: str, user_id: str, message_id: str, reaction: Reaction
    ) -> LoggedEntry | None:
        """Put reaction on the user message while it has none; None when it already had one or moved on."""
        found = await self._repository.read_log(conversation_id, user_id=user_id, ids=[message_id])
        if not found or not isinstance(message := found[0].entry, UserMessage):
            raise ConversationEntryNotFoundError(
                message=f"no user message {message_id} in conversation {conversation_id}",
                meta={"conversation_id": conversation_id, "entry_id": message_id},
            )
        if message.reaction is not None:
            return None
        revised = message.model_copy(
            update={"reaction": reaction, "revision": message.revision + 1}
        )
        amended = found[0].model_copy(update={"entry": revised})
        if not await self._repository.stage_unfenced_amend(
            conversation_id, user_id=user_id, amended=amended, after_revision=message.revision
        ):
            return None
        return amended

    async def read_after(
        self, conversation_id: str, user_id: str, seq: int
    ) -> Sequence[LoggedEntry]:
        """Return the entries after seq in order, with their current content."""
        entries = await self._repository.read_log(conversation_id, user_id=user_id, after_seq=seq)
        if entries is None:
            raise _not_found(conversation_id)
        return entries

    async def state(self, conversation_id: str, user_id: str) -> ConversationState:
        """Return the conversation's current state."""
        return (await self._head(conversation_id, user_id)).state

    async def unsettled(self, conversation_id: str, user_id: str) -> Unsettled:
        """Return the current state and the entries after max(settled_through, stopped_through), in one read of the head."""
        read = await self._repository.read_unsettled(conversation_id, user_id=user_id)
        if read is None:
            raise _not_found(conversation_id)
        state, entries = read
        return Unsettled(state=state, entries=entries)

    async def claim(self, conversation_id: str, user_id: str) -> StepClaim | None:
        """Take the step with a new epoch, or None while another holder is alive.

        The hint's epoch stands in for the head read when its holder's key is gone: take_runner
        is conditional on that epoch, so a stale hint only misses and falls back to the head.
        """
        client = redis_cache.client
        last: int | None = await self._hinted_free_epoch(conversation_id, user_id)
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            if last is None:
                head = await self._head(conversation_id, user_id)
                if head.holder is not None and await client.exists(
                    _alive_key(conversation_id, user_id, head.holder)
                ):
                    return None
                last = head.runner_epoch
            epoch = last + 1
            alive_key = _alive_key(conversation_id, user_id, epoch)
            # Taken before the head names it, so no reader sees a holder without its key; NX lets one claimer per epoch through.
            if not await client.set(alive_key, str(epoch), ex=RUNNER_ALIVE_TTL_SECONDS, nx=True):
                return None
            taken_from = await self._repository.take_runner(
                conversation_id, user_id=user_id, runner_epoch=last, alive_key=alive_key
            )
            if taken_from is not None:
                await _raise_hint(conversation_id, user_id, HintField.EPOCH, epoch, {})
                return StepClaim(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    epoch=epoch,
                    took_over=taken_from.holder is not None,
                )
            await client.delete(alive_key)
            last = None
        return None

    async def _hinted_free_epoch(self, conversation_id: str, user_id: str) -> int | None:
        """Return the hint's last epoch when its holder's key is gone; None when only the head can tell."""
        hinted = await redis_cache.client.hget(_hint_key(conversation_id, user_id), HintField.EPOCH)
        if hinted is None:
            return None
        epoch = int(hinted)
        # A live key is a refusal, and a refusal is confirmed on the head, never on the hint.
        if await redis_cache.client.exists(_alive_key(conversation_id, user_id, epoch)):
            return None
        return epoch

    async def release_if_caught_up(self, claim: StepClaim) -> bool:
        """Release when nothing waking is unsettled; atomic with append; ClaimLost on a stale epoch."""
        if await self._repository.release_runner(
            claim.conversation_id, user_id=claim.user_id, epoch=claim.epoch
        ):
            await redis_cache.client.delete(
                _alive_key(claim.conversation_id, claim.user_id, claim.epoch)
            )
            return True
        if (await self._head(claim.conversation_id, claim.user_id)).holder != claim.epoch:
            raise ClaimLost
        return False

    async def set_comms(self, claim: StepClaim, phase: CommsPhase) -> ConversationState:
        """Write the comms phase, fenced, and return the new state."""
        state = await self._repository.set_log_comms(
            claim.conversation_id, user_id=claim.user_id, epoch=claim.epoch, phase=phase
        )
        if state is None:
            raise ClaimLost
        return state

    async def hint(self, conversation_id: str, user_id: str) -> PreemptHint:
        """Return the preempt view; barge_reply_id is set only while that reply is open."""
        held = await redis_cache.client.hgetall(_hint_key(conversation_id, user_id))
        if not all(field in held for field in _HINT_REQUIRED):
            head = await self._head(conversation_id, user_id)
            return PreemptHint(
                head=head.log_head, stop_through=head.state.stopped_through, epoch=head.runner_epoch
            )
        barge = held.get(HintField.BARGE) or None
        return PreemptHint(
            head=int(held[HintField.HEAD]),
            stop_through=int(held[HintField.STOP]),
            barge_reply_id=barge if barge == held.get(HintField.OPEN) else None,
            epoch=int(held[HintField.EPOCH]),
        )

    async def beat(self, claim: StepClaim) -> bool:
        """Renew the claim's liveness; False once its key lapsed or was released, which nothing renews."""
        key = _alive_key(claim.conversation_id, claim.user_id, claim.epoch)
        return bool(await redis_cache.client.expire(key, RUNNER_ALIVE_TTL_SECONDS))

    async def _append(
        self, conversation_id: str, user_id: str, entry: Entry, *, epoch: int | None
    ) -> Appended:
        unread = await self._marks_unread(conversation_id, user_id, entry)
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            head = await self._head(conversation_id, user_id, entry.id)
            if epoch is not None and head.holder != epoch:
                raise ClaimLost
            seq = head.known.get(entry.id)
            if seq is not None:
                return await self._duplicate(head, seq)
            logged = LoggedEntry(seq=head.log_head + 1, at=stored_at(self._clock()), entry=entry)
            result = reduce(head.state, logged)
            if isinstance(result, Rejected):
                raise EntryRejected(result.reason)
            if await self._repository.commit_log_entry(
                head,
                logged,
                result.state,
                epoch=epoch,
                unread=unread,
                # The step an unfenced entry kicks carries it on its own commits, off the reply's path.
                flush=epoch is not None
                or not any(isinstance(effect, KickStep) for effect in result.effects),
            ):
                await _publish_hint(conversation_id, user_id, logged, result.state)
                return Appended(
                    logged=logged,
                    previous=head.state,
                    state=result.state,
                    effects=result.effects,
                    duplicate=False,
                )
            await asyncio.sleep(_JITTER.uniform(0, CONVERSATION_APPEND_JITTER_SECONDS))
        raise ConversationStoreError(
            message=f"append to conversation {conversation_id} lost every conditional write",
            why=f"the head moved under each of {CONVERSATION_APPEND_MAX_ATTEMPTS} attempts",
            meta={"conversation_id": conversation_id},
        )

    async def _marks_unread(self, conversation_id: str, user_id: str, entry: Entry) -> bool:
        """Return whether entry is news the user did not ask for here: a Notice, or a reply answering no message of theirs.

        A todo's write-up never is: its chat is reached from the todo, so it carries no unread dot.
        """
        match entry:
            case Notice():
                return True
            case ReplySettled(outcome=ReplyOutcome.ANSWERED, answers=answers) if answers:
                answered = await self._repository.read_log(
                    conversation_id, user_id=user_id, ids=list(answers)
                )
                return not any(
                    isinstance(logged.entry, UserMessage | TodoWoke) for logged in answered or ()
                )
            case _:
                return False

    async def _duplicate(self, head: LogHead, seq: int) -> Appended:
        """Return the entry already stored at seq: a duplicate changes nothing, so it carries the current state and no effects."""
        entries = await self._repository.read_log(
            head.conversation_id, user_id=head.user_id, after_seq=seq - 1, through_seq=seq
        )
        if not entries or entries[-1].seq != seq:
            raise ConversationStoreError(
                message=f"seq {seq} of conversation {head.conversation_id} holds a message, not a log entry",
                meta={"conversation_id": head.conversation_id, "seq": seq},
            )
        return Appended(
            logged=entries[-1], previous=head.state, state=head.state, effects=(), duplicate=True
        )

    async def _head(
        self, conversation_id: str, user_id: str, entry_id: str | None = None
    ) -> LogHead:
        head = await self._repository.read_log_head(
            conversation_id, user_id=user_id, entry_id=entry_id
        )
        if head is None:
            raise _not_found(conversation_id)
        return head


def _not_found(conversation_id: str) -> ConversationNotFoundError:
    return ConversationNotFoundError(
        message=f"conversation {conversation_id} does not exist for this user",
        meta={"conversation_id": conversation_id},
    )


def _alive_key(conversation_id: str, user_id: str, epoch: int) -> str:
    return f"{RUNNER_ALIVE_KEY_PREFIX}{user_id}:{conversation_id}:{epoch}"


def _hint_key(conversation_id: str, user_id: str) -> str:
    return f"{HINT_KEY_PREFIX}{user_id}:{conversation_id}"


async def _publish_hint(
    conversation_id: str, user_id: str, logged: LoggedEntry, state: ConversationState
) -> None:
    """Raise the hint to the committed head; when that write fails, drop the hint so readers rebuild it from the head.

    A stale hint is never left behind: a running step trusts it to learn of a Stop. If even the
    drop fails, the error propagates, as the step's own hint read would fail the same way.
    """
    fields: dict[str, object] = {
        HintField.STOP: state.stopped_through,
        HintField.OPEN: state.open_reply or "",
    }
    if isinstance(logged.entry, BargeIn):
        fields[HintField.BARGE] = logged.entry.reply_id
    try:
        await _raise_hint(conversation_id, user_id, HintField.HEAD, logged.seq, fields)
    except RedisError as exc:
        log.error(
            f"{LogTag.STORAGE} Could not raise a conversation's preempt hint; dropping it",
            conversation_id=conversation_id,
            seq=logged.seq,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        await redis_cache.client.delete(_hint_key(conversation_id, user_id))


async def _raise_hint(
    conversation_id: str, user_id: str, guard: HintField, value: int, fields: Mapping[str, object]
) -> None:
    pairs = [str(item) for pair in fields.items() for item in pair]
    await redis_cache.client.eval(
        _RAISE_HINT,
        1,
        _hint_key(conversation_id, user_id),
        guard,
        str(value),
        str(HINT_TTL_SECONDS),
        *pairs,
    )
