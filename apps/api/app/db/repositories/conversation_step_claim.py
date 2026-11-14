"""The step's claim on a conversation head: who holds it (runner), the last epoch handed out, and the comms phase it writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pymongo import ReturnDocument

from app.db.repositories.conversation_entries import (
    EMPTY_LOG_STATE,
    RUNNER_EPOCH_FIELD,
    RUNNER_FIELD,
    STATE_FIELD,
    current_state,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import CommsPhase, ConversationState
from app.models.conversation_models import ConversationHead, StepHolder

_EMPTY_STATE: dict[str, object] = EMPTY_LOG_STATE.model_dump(mode="json")


@dataclass(frozen=True)
class TakenFrom:
    """What take_runner replaced: the epoch that held the step, None when it was free."""

    holder: int | None


class StepClaimRepository(ConversationRepository):
    """Epoch-fenced writes of the step's holder and of the comms phase it owns."""

    async def take_runner(
        self, conversation_id: str, *, user_id: str, runner_epoch: int, alive_key: str
    ) -> TakenFrom | None:
        """Hand the step to epoch runner_epoch + 1, only while runner_epoch is still the last one handed out; None when it is not."""
        last = runner_epoch if runner_epoch else {"$exists": False}
        epoch = runner_epoch + 1
        still_last = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            RUNNER_EPOCH_FIELD: last,
        }
        hand_over = {
            "$set": {
                RUNNER_EPOCH_FIELD: epoch,
                RUNNER_FIELD: {"epoch": epoch, "alive_key": alive_key},
            }
        }
        with store_errors("log claim"):  # pragma: no mutate — error label
            # pragma: no mutate start — only the holder is read back, the projection trims the rest
            before = await self._raw_collection().find_one_and_update(
                still_last, hand_over, projection={RUNNER_FIELD: 1}
            )
            # pragma: no mutate end
        if before is None:
            return None
        holder = before.get(RUNNER_FIELD)
        return TakenFrom(holder=None if holder is None else StepHolder.model_validate(holder).epoch)

    async def release_runner(self, conversation_id: str, *, user_id: str, epoch: int) -> bool:
        """Clear the step's holder, only while epoch holds it and nothing waking is unsettled."""
        with store_errors("log release"):  # pragma: no mutate — error label
            result = await self._raw_collection().update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                    "$or": [
                        {f"{STATE_FIELD}.unsettled_waking": []},
                        {STATE_FIELD: {"$exists": False}},
                    ],
                },
                {"$set": {RUNNER_FIELD: None}},
            )
        return bool(result.matched_count)

    async def set_log_comms(
        self, conversation_id: str, *, user_id: str, epoch: int, phase: CommsPhase
    ) -> ConversationState | None:
        """Write the comms phase while epoch holds the step, returning the state; None when it does not."""
        state = {"$mergeObjects": [{"$literal": _EMPTY_STATE}, f"${STATE_FIELD}", {"comms": phase}]}
        with store_errors("log comms"):  # pragma: no mutate — error label
            raw = await self._raw_collection().find_one_and_update(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    f"{RUNNER_FIELD}.epoch": epoch,
                },
                [{"$set": {STATE_FIELD: state}}],
                return_document=ReturnDocument.AFTER,
            )
        return None if raw is None else _state(raw)


def _state(raw: Mapping[str, object]) -> ConversationState:
    return current_state(ConversationHead.model_validate(raw))
