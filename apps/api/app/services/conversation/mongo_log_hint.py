"""The preempt hint in Redis: raised only forward on every commit, and rebuilt from the head whenever it is missing."""

from collections.abc import Mapping

from redis.exceptions import RedisError

from app.constants.conversation import HINT_KEY_PREFIX, HINT_TTL_SECONDS, HintField
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.conversation_log_models import (
    BargeIn,
    ConversationState,
    LoggedEntry,
    PreemptHint,
)
from app.services.conversation.mongo_log_base import MongoLogBase
from shared.py.wide_events import log

# Raises the hint only past what it already holds, so a slower write of an older value never lands over a newer one.
_RAISE_HINT = """
local held = tonumber(redis.call('HGET', KEYS[1], ARGV[1]))
if held and held >= tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2], unpack(ARGV, 4))
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
_HINT_REQUIRED = (HintField.HEAD, HintField.STOP, HintField.EPOCH)


class LogHint(MongoLogBase):
    """The log's preempt view, read from the hint and from the head when the hint lapsed."""

    async def hint(self, conversation_id: str, user_id: str) -> PreemptHint:
        """Return the preempt view; barge_reply_id is set only while that reply is open."""
        held = await redis_cache.client.hgetall(hint_key(conversation_id, user_id))
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


def hint_key(conversation_id: str, user_id: str) -> str:
    """Return the Redis key of the conversation's preempt hint."""
    return f"{HINT_KEY_PREFIX}{user_id}:{conversation_id}"


async def publish_hint(
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
        await raise_hint(conversation_id, user_id, HintField.HEAD, logged.seq, fields)
    except RedisError as exc:
        log.error(
            f"{LogTag.STORAGE} Could not raise a conversation's preempt hint; dropping it",
            conversation_id=conversation_id,
            seq=logged.seq,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        await redis_cache.client.delete(hint_key(conversation_id, user_id))


async def raise_hint(
    conversation_id: str, user_id: str, guard: HintField, value: int, fields: Mapping[str, object]
) -> None:
    """Set guard to value on the hint, with fields, only when value is past what the guard holds."""
    pairs = [str(item) for pair in fields.items() for item in pair]
    await redis_cache.client.eval(
        _RAISE_HINT,
        1,
        hint_key(conversation_id, user_id),
        guard,
        str(value),
        str(HINT_TTL_SECONDS),
        *pairs,
    )
