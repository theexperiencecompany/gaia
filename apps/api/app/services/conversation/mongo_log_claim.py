"""The step's claim: an epoch on the head, fenced by conditional writes, kept alive by a lapsing Redis key."""

from app.constants.chat import CONVERSATION_APPEND_MAX_ATTEMPTS
from app.constants.conversation import (
    RUNNER_ALIVE_KEY_PREFIX,
    RUNNER_ALIVE_TTL_SECONDS,
    HintField,
)
from app.db.redis import redis_cache
from app.models.conversation_log_models import CommsPhase, ConversationState, StepClaim
from app.services.conversation.mongo_log_base import MongoLogBase
from app.services.conversation.mongo_log_hint import hint_key, raise_hint
from app.services.conversation.ports import ClaimLost


class StepClaims(MongoLogBase):
    """Take, renew, fence and release the conversation's step."""

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
                    alive_key(conversation_id, user_id, head.holder)
                ):
                    return None
                last = head.runner_epoch
            epoch = last + 1
            key = alive_key(conversation_id, user_id, epoch)
            # Taken before the head names it, so no reader sees a holder without its key; NX lets one claimer per epoch through.
            if not await client.set(key, str(epoch), ex=RUNNER_ALIVE_TTL_SECONDS, nx=True):
                return None
            taken_from = await self._repository.take_runner(
                conversation_id, user_id=user_id, runner_epoch=last, alive_key=key
            )
            if taken_from is not None:
                await raise_hint(conversation_id, user_id, HintField.EPOCH, epoch, {})
                return StepClaim(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    epoch=epoch,
                    took_over=taken_from.holder is not None,
                )
            await client.delete(key)
            last = None
        return None

    async def _hinted_free_epoch(self, conversation_id: str, user_id: str) -> int | None:
        """Return the hint's last epoch when its holder's key is gone; None when only the head can tell."""
        hinted = await redis_cache.client.hget(hint_key(conversation_id, user_id), HintField.EPOCH)
        if hinted is None:
            return None
        epoch = int(hinted)
        # A live key is a refusal, and a refusal is confirmed on the head, never on the hint.
        if await redis_cache.client.exists(alive_key(conversation_id, user_id, epoch)):
            return None
        return epoch

    async def release_if_caught_up(self, claim: StepClaim) -> bool:
        """Release when nothing waking is unsettled; atomic with append; ClaimLost on a stale epoch."""
        if await self._repository.release_runner(
            claim.conversation_id, user_id=claim.user_id, epoch=claim.epoch
        ):
            await redis_cache.client.delete(
                alive_key(claim.conversation_id, claim.user_id, claim.epoch)
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

    async def beat(self, claim: StepClaim) -> bool:
        """Renew the claim's liveness; False once its key lapsed or was released, which nothing renews."""
        key = alive_key(claim.conversation_id, claim.user_id, claim.epoch)
        return bool(await redis_cache.client.expire(key, RUNNER_ALIVE_TTL_SECONDS))


def alive_key(conversation_id: str, user_id: str, epoch: int) -> str:
    """Return the Redis key whose presence proves epoch's holder is alive."""
    return f"{RUNNER_ALIVE_KEY_PREFIX}{user_id}:{conversation_id}:{epoch}"
