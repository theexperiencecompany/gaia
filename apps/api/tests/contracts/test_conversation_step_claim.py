"""StepClaimRepository on real Mongo: handing out epochs, releasing the step, and the comms phase it writes."""

from __future__ import annotations

from typing import Any

import pytest

from app.db.repositories.conversation_entries import EMPTY_LOG_STATE
from app.db.repositories.conversation_step_claim import StepClaimRepository, TakenFrom
from app.models.conversation_log_models import CommsPhase
from app.services.conversation.mongo_log import MongoConversationLog
from tests.unit.services.conversation.log_helpers import notice, user
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


async def _head(raw_collection: Any, conversation: str) -> dict[str, Any]:
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert head is not None
    return head


async def test_the_first_claim_takes_a_free_step_at_epoch_one(
    conversation: str, raw_collection: Any
) -> None:
    taken = await StepClaimRepository().take_runner(
        conversation, user_id=UID, runner_epoch=0, alive_key="alive-1"
    )

    assert taken == TakenFrom(holder=None)
    head = await _head(raw_collection, conversation)
    assert head["runner_epoch"] == 1
    assert head["runner"] == {"epoch": 1, "alive_key": "alive-1"}


async def test_a_claim_from_a_stale_epoch_or_another_user_takes_nothing(
    conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    assert await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")

    assert (
        await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="b")
        is None
    )
    assert (
        await repository.take_runner(
            conversation, user_id="someone-else", runner_epoch=1, alive_key="c"
        )
        is None
    )
    assert (
        await repository.take_runner("c-missing", user_id=UID, runner_epoch=0, alive_key="d")
        is None
    )

    head = await _head(raw_collection, conversation)
    assert (head["runner_epoch"], head["runner"]["alive_key"]) == (1, "a")


async def test_a_takeover_names_the_epoch_it_replaced(
    conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")

    taken = await repository.take_runner(conversation, user_id=UID, runner_epoch=1, alive_key="b")

    assert taken == TakenFrom(holder=1)
    head = await _head(raw_collection, conversation)
    assert head["runner"] == {"epoch": 2, "alive_key": "b"}


async def test_a_released_step_is_claimed_from_no_holder(conversation: str) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")
    assert await repository.release_runner(conversation, user_id=UID, epoch=1)

    taken = await repository.take_runner(conversation, user_id=UID, runner_epoch=1, alive_key="b")

    assert taken == TakenFrom(holder=None)


async def test_only_the_holding_epoch_of_its_own_user_releases_the_step(
    conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")

    assert not await repository.release_runner(conversation, user_id=UID, epoch=2)
    assert not await repository.release_runner(conversation, user_id="someone-else", epoch=1)
    assert (await _head(raw_collection, conversation))["runner"]["epoch"] == 1

    assert await repository.release_runner(conversation, user_id=UID, epoch=1)
    assert (await _head(raw_collection, conversation))["runner"] is None


async def test_the_step_is_not_released_while_a_waking_entry_is_unsettled(
    log: MongoConversationLog, conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")
    await log.append(conversation, UID, user("u1"))

    assert not await repository.release_runner(conversation, user_id=UID, epoch=1)
    assert (await _head(raw_collection, conversation))["runner"]["epoch"] == 1


async def test_the_step_is_released_with_a_state_that_has_nothing_waking(
    log: MongoConversationLog, conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")
    await log.append(conversation, UID, notice("n1"))
    assert (await _head(raw_collection, conversation))["state"]["unsettled_waking"] == []

    assert await repository.release_runner(conversation, user_id=UID, epoch=1)


async def test_the_comms_phase_is_written_only_by_the_holding_epoch(
    conversation: str, raw_collection: Any
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")

    assert (
        await repository.set_log_comms(
            conversation, user_id=UID, epoch=2, phase=CommsPhase.THINKING
        )
        is None
    )
    assert (
        await repository.set_log_comms("c-missing", user_id=UID, epoch=1, phase=CommsPhase.THINKING)
        is None
    )
    assert "state" not in await _head(raw_collection, conversation)

    state = await repository.set_log_comms(
        conversation, user_id=UID, epoch=1, phase=CommsPhase.THINKING
    )

    assert state == EMPTY_LOG_STATE.model_copy(update={"comms": CommsPhase.THINKING})
    assert (await _head(raw_collection, conversation))["state"]["comms"] == "thinking"


async def test_the_comms_phase_keeps_the_rest_of_the_stored_state(
    log: MongoConversationLog, conversation: str
) -> None:
    repository = StepClaimRepository()
    await repository.take_runner(conversation, user_id=UID, runner_epoch=0, alive_key="a")
    await log.append(conversation, UID, user("u1"))

    state = await repository.set_log_comms(
        conversation, user_id=UID, epoch=1, phase=CommsPhase.ANSWERING
    )

    assert state is not None
    assert (state.comms, state.head, state.unsettled_waking) == (CommsPhase.ANSWERING, 1, (1,))
