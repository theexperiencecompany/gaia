"""The step's claim on real Mongo and Redis: one holder per epoch, alive while its key lives, fenced on the head."""

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.conversation import (
    RUNNER_ALIVE_KEY_PREFIX,
    RUNNER_ALIVE_TTL_SECONDS,
    HintField,
)
from app.db.redis import AsyncRedisCommands
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversation_log_append import LogHead
from app.db.repositories.conversation_step_claim import TakenFrom
from app.models.conversation_log_models import CommsPhase, StepClaim
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_claim import StepClaims, alive_key
from app.services.conversation.mongo_log_hint import hint_key
from app.services.conversation.ports import ClaimLost
from app.utils.errors import ConversationNotFoundError
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


class CountingRepository(ConversationLogRepository):
    """The real repository, counting its head reads and takes."""

    def __init__(self) -> None:
        self.head_reads = 0
        self.takes: list[int] = []

    async def read_log_head(
        self, conversation_id: str, *, user_id: str, entry_id: str | None = None
    ) -> LogHead | None:
        self.head_reads += 1
        return await super().read_log_head(conversation_id, user_id=user_id, entry_id=entry_id)

    async def take_runner(
        self, conversation_id: str, *, user_id: str, runner_epoch: int, alive_key: str
    ) -> TakenFrom | None:
        self.takes.append(runner_epoch)
        return await super().take_runner(
            conversation_id, user_id=user_id, runner_epoch=runner_epoch, alive_key=alive_key
        )


@pytest.fixture
def repository() -> CountingRepository:
    return CountingRepository()


@pytest.fixture
def claims(repository: CountingRepository) -> StepClaims:
    return StepClaims(repository, FakeClock())


def test_the_alive_key_names_the_user_conversation_and_epoch() -> None:
    assert alive_key("c-1", "u-1", 4) == f"{RUNNER_ALIVE_KEY_PREFIX}u-1:c-1:4"


async def test_a_fresh_conversation_is_claimed_at_epoch_one_with_a_live_key_and_a_hinted_epoch(
    claims: StepClaims,
    conversation: str,
    redis: AsyncRedisCommands,
    raw_collection: AsyncIOMotorCollection,
) -> None:
    claim = await claims.claim(conversation, UID)

    assert claim == StepClaim(conversation_id=conversation, user_id=UID, epoch=1, took_over=False)
    key = alive_key(conversation, UID, 1)
    assert await redis.get(key) == "1"
    assert RUNNER_ALIVE_TTL_SECONDS - 2 < await redis.ttl(key) <= RUNNER_ALIVE_TTL_SECONDS
    assert await redis.hgetall(hint_key(conversation, UID)) == {HintField.EPOCH: "1"}
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert head["runner"]["alive_key"] == key


async def test_a_live_holder_refuses_every_other_claim(
    claims: StepClaims, conversation: str
) -> None:
    assert await claims.claim(conversation, UID) is not None

    assert await claims.claim(conversation, UID) is None


async def test_a_live_holder_refuses_a_claim_even_with_no_hint(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    assert await claims.claim(conversation, UID) is not None
    await redis.delete(hint_key(conversation, UID))

    assert await claims.claim(conversation, UID) is None


async def test_a_lapsed_holder_is_taken_over_at_the_next_epoch(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    assert await claims.claim(conversation, UID) is not None
    await redis.delete(alive_key(conversation, UID, 1))

    claim = await claims.claim(conversation, UID)

    assert claim is not None
    assert (claim.epoch, claim.took_over) == (2, True)


async def test_a_released_step_is_claimed_from_the_hint_with_no_head_read(
    claims: StepClaims, repository: CountingRepository, conversation: str
) -> None:
    first = await claims.claim(conversation, UID)
    assert first is not None
    assert await claims.release_if_caught_up(first)
    repository.head_reads = 0

    claim = await claims.claim(conversation, UID)

    assert claim is not None
    assert (claim.epoch, claim.took_over) == (2, False)
    assert repository.head_reads == 0
    assert repository.takes[-1] == 1


async def test_a_stale_hinted_epoch_misses_drops_its_key_and_claims_from_the_head(
    claims: StepClaims, repository: CountingRepository, conversation: str, redis: AsyncRedisCommands
) -> None:
    await redis.hset(hint_key(conversation, UID), mapping={HintField.EPOCH: "3"})

    claim = await claims.claim(conversation, UID)

    assert claim is not None
    assert claim.epoch == 1
    assert repository.takes == [3, 0]
    assert not await redis.exists(alive_key(conversation, UID, 4))
    assert await redis.exists(alive_key(conversation, UID, 1))


async def test_a_hinted_epoch_whose_key_lives_is_confirmed_on_the_head(
    claims: StepClaims, repository: CountingRepository, conversation: str, redis: AsyncRedisCommands
) -> None:
    await redis.hset(hint_key(conversation, UID), mapping={HintField.EPOCH: "0"})
    await redis.set(alive_key(conversation, UID, 0), "0")

    claim = await claims.claim(conversation, UID)

    assert claim is not None
    assert claim.epoch == 1
    assert repository.head_reads == 1


async def test_a_claimer_beaten_to_the_epochs_key_gets_nothing(
    claims: StepClaims,
    conversation: str,
    redis: AsyncRedisCommands,
    raw_collection: AsyncIOMotorCollection,
) -> None:
    await redis.set(alive_key(conversation, UID, 1), "other")

    assert await claims.claim(conversation, UID) is None
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert not head.get("runner")
    assert await redis.get(alive_key(conversation, UID, 1)) == "other"


async def test_a_head_with_no_holder_consults_no_holders_key(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    await redis.set(f"{RUNNER_ALIVE_KEY_PREFIX}{UID}:{conversation}:None", "stray")

    claim = await claims.claim(conversation, UID)

    assert claim is not None
    assert claim.epoch == 1


async def test_claiming_a_conversation_the_user_lacks_is_not_found(claims: StepClaims) -> None:
    with pytest.raises(ConversationNotFoundError):
        await claims.claim("c-missing", UID)


async def test_releasing_with_nothing_unsettled_drops_the_live_key(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await claims.claim(conversation, UID)
    assert claim is not None

    assert await claims.release_if_caught_up(claim) is True
    assert not await redis.exists(alive_key(conversation, UID, 1))


async def test_a_waking_entry_unsettled_keeps_the_claim_and_its_key(
    claims: StepClaims, log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await claims.claim(conversation, UID)
    assert claim is not None
    await log.append(conversation, UID, user("m1"))

    assert await claims.release_if_caught_up(claim) is False
    assert await redis.exists(alive_key(conversation, UID, 1))


async def test_releasing_a_lost_claim_raises(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await claims.claim(conversation, UID)
    assert claim is not None
    await redis.delete(alive_key(conversation, UID, 1))
    assert await claims.claim(conversation, UID) is not None

    with pytest.raises(ClaimLost):
        await claims.release_if_caught_up(claim)
    assert await redis.exists(alive_key(conversation, UID, 2))


async def test_the_comms_phase_is_written_for_the_holder_and_refused_to_a_lost_one(
    claims: StepClaims, log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await claims.claim(conversation, UID)
    assert claim is not None
    phase = CommsPhase.THINKING

    assert (await claims.set_comms(claim, phase)).comms == phase
    assert (await log.state(conversation, UID)).comms == phase

    await redis.delete(alive_key(conversation, UID, 1))
    assert await claims.claim(conversation, UID) is not None
    with pytest.raises(ClaimLost):
        await claims.set_comms(claim, phase)


async def test_a_beat_renews_a_live_key_and_fails_once_it_lapsed(
    claims: StepClaims, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await claims.claim(conversation, UID)
    assert claim is not None
    key = alive_key(conversation, UID, 1)
    await redis.expire(key, 3)

    assert await claims.beat(claim) is True
    assert await redis.ttl(key) > RUNNER_ALIVE_TTL_SECONDS - 2

    await redis.delete(key)
    assert await claims.beat(claim) is False
