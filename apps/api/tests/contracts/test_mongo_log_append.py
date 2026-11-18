"""Appending to the conversation log on real Mongo and Redis: seq order, the fold, duplicates, the fence and the unread dot."""

from collections.abc import Sequence
import time

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.conversation import HintField
from app.db.redis import AsyncRedisCommands
from app.db.repositories.conversation_entries import stored_at
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversation_log_append import LogHead
from app.models.conversation_log_models import (
    ConversationState,
    Entry,
    KickStep,
    LoggedEntry,
    RejectReason,
)
from app.services.conversation import mongo_log_append
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.mongo_log_append import LogAppends
from app.services.conversation.mongo_log_claim import alive_key
from app.services.conversation.mongo_log_hint import hint_key
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.utils.errors import ConversationNotFoundError, ConversationStoreError
from shared.py.conversation_wire import ReplyOutcome
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import (
    EMPTY,
    asked,
    notice,
    opened,
    settled,
    started,
    stop,
    todo_woke,
    user,
)
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


class LosingRepository(ConversationLogRepository):
    """The real repository, whose first lose_first commits lose their conditional write."""

    def __init__(self, lose_first: int) -> None:
        self.lose_first = lose_first
        self.commits = 0

    async def commit_log_entry(
        self,
        head: LogHead,
        logged: LoggedEntry,
        state: ConversationState,
        *,
        epoch: int | None,
        unread: bool = False,
        flush: bool = True,
    ) -> bool:
        self.commits += 1
        if self.commits <= self.lose_first:
            return False
        return await super().commit_log_entry(
            head, logged, state, epoch=epoch, unread=unread, flush=flush
        )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def appends(clock: FakeClock) -> LogAppends:
    return LogAppends(ConversationLogRepository(), clock)


async def _unread(raw_collection: AsyncIOMotorCollection, conversation: str) -> bool:
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert head is not None
    return bool(head.get("is_unread"))


def _flushes(held: HeldFlushes) -> int:
    return sum(operation == "conversation_flush" for operation, _ in held.spawned)


async def _append_all(
    log: MongoConversationLog, conversation: str, entries: Sequence[Entry]
) -> None:
    for entry in entries:
        await log.append(conversation, UID, entry)


async def test_an_entry_is_stored_at_the_next_seq_stamped_with_the_clock(
    appends: LogAppends, clock: FakeClock, conversation: str, redis: AsyncRedisCommands
) -> None:
    first = await appends.append(conversation, UID, user("m1"))
    clock.advance(5)

    second = await appends.append(conversation, UID, user("m2"))

    assert (first.logged.seq, second.logged.seq) == (1, 2)
    assert second.logged.at == stored_at(clock())
    assert second.logged.entry == user("m2")
    assert first.previous == EMPTY
    assert second.previous == first.state
    assert second.duplicate is False
    assert KickStep() in second.effects
    assert (await redis.hgetall(hint_key(conversation, UID)))[HintField.HEAD] == "2"


async def test_each_approval_request_is_stored_under_the_next_number_the_user_sees(
    appends: LogAppends, conversation: str
) -> None:
    await appends.append(conversation, UID, user("u1"))
    await appends.append(conversation, UID, started("w", "t1", 1))

    first = await appends.append(conversation, UID, asked("a1", "t1", "ap1"))
    second = await appends.append(conversation, UID, asked("a2", "t1", "ap2"))

    assert (first.logged.entry, second.logged.entry) == (
        asked("a1", "t1", "ap1").model_copy(update={"number": 1}),
        asked("a2", "t1", "ap2").model_copy(update={"number": 2}),
    )


async def test_the_same_id_again_is_the_stored_entry_with_the_current_state_and_no_effects(
    appends: LogAppends, clock: FakeClock, conversation: str
) -> None:
    stored = await appends.append(conversation, UID, user("m1"))
    after = await appends.append(conversation, UID, user("m2"))
    clock.advance(30)

    again = await appends.append(conversation, UID, user("m1"))

    assert again.duplicate is True
    assert again.logged == stored.logged
    assert again.previous == after.state
    assert again.state == after.state
    assert again.effects == ()


async def test_a_duplicate_of_a_flushed_entry_is_read_back_from_the_entries(
    appends: LogAppends, conversation: str, held: HeldFlushes
) -> None:
    stored = await appends.append(conversation, UID, notice("n1"))
    await appends.append(conversation, UID, notice("n2"))
    await held.run_all()

    again = await appends.append(conversation, UID, notice("n1"))

    assert (again.duplicate, again.logged) == (True, stored.logged)


async def test_an_entry_the_fold_refuses_is_rejected_and_not_stored(
    appends: LogAppends, log: MongoConversationLog, conversation: str
) -> None:
    await appends.append(conversation, UID, user("m1"))

    with pytest.raises(EntryRejected) as raised:
        await appends.append(conversation, UID, stop("s1", covers_through=9))

    assert raised.value.reason is RejectReason.STOP_COVERS_FUTURE
    assert [e.seq for e in await log.read_after(conversation, UID, 0)] == [1]


async def test_appending_to_a_conversation_the_user_lacks_is_not_found(
    appends: LogAppends,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        await appends.append("c-missing", UID, user("m1"))


async def test_a_fenced_append_lands_for_the_holder_and_is_refused_once_the_claim_moved(
    appends: LogAppends, log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await log.claim(conversation, UID)
    assert claim is not None

    landed = await appends.append_fenced(claim, opened("o1"))
    assert (landed.logged.seq, landed.state.open_reply) == (1, "r1")

    await redis.delete(alive_key(conversation, UID, 1))
    assert await log.claim(conversation, UID) is not None
    with pytest.raises(ClaimLost):
        await appends.append_fenced(claim, notice("n1"))
    assert [e.seq for e in await log.read_after(conversation, UID, 0)] == [1]


async def test_an_unfenced_entry_that_kicks_the_step_leaves_its_flush_to_the_step(
    appends: LogAppends, held: HeldFlushes, conversation: str
) -> None:
    await appends.append(conversation, UID, user("m1"))

    assert _flushes(held) == 0


async def test_an_unfenced_entry_that_kicks_nothing_is_flushed_with_its_commit(
    appends: LogAppends, held: HeldFlushes, conversation: str
) -> None:
    await appends.append(conversation, UID, notice("n1"))

    assert _flushes(held) == 1


async def test_a_fenced_entry_that_kicks_the_step_is_flushed_with_its_commit(
    appends: LogAppends, log: MongoConversationLog, held: HeldFlushes, conversation: str
) -> None:
    claim = await log.claim(conversation, UID)
    assert claim is not None

    assert KickStep() in (await appends.append_fenced(claim, user("m1"))).effects
    assert _flushes(held) == 1


async def test_a_commit_that_lost_its_write_is_retried_on_a_fresh_head(
    clock: FakeClock, log: MongoConversationLog, conversation: str
) -> None:
    repository = LosingRepository(lose_first=2)

    appended = await LogAppends(repository, clock).append(conversation, UID, user("m1"))

    assert repository.commits == 3
    assert appended.logged.seq == 1
    assert [e.entry.id for e in await log.read_after(conversation, UID, 0)] == ["m1"]


async def test_a_lost_write_is_retried_after_only_a_few_milliseconds_of_jitter(
    clock: FakeClock, conversation: str
) -> None:
    repository = LosingRepository(lose_first=8)
    started = time.monotonic()

    await LogAppends(repository, clock).append(conversation, UID, user("m1"))

    # Eight jitters at most CONVERSATION_APPEND_JITTER_SECONDS each, far under a second.
    assert time.monotonic() - started < 1


async def test_a_commit_fenced_on_a_claim_taken_over_since_the_head_read_never_lands(
    clock: FakeClock, log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    claim = await log.claim(conversation, UID)
    assert claim is not None

    class TakenOverMidCommit(ConversationLogRepository):
        async def commit_log_entry(
            self,
            head: LogHead,
            logged: LoggedEntry,
            state: ConversationState,
            *,
            epoch: int | None,
            unread: bool = False,
            flush: bool = True,
        ) -> bool:
            await redis.delete(alive_key(conversation, UID, 1))
            assert await log.claim(conversation, UID) is not None
            return await super().commit_log_entry(
                head, logged, state, epoch=epoch, unread=unread, flush=flush
            )

    with pytest.raises(ClaimLost):
        await LogAppends(TakenOverMidCommit(), clock).append_fenced(claim, notice("n1"))
    assert await log.read_after(conversation, UID, 0) == []


async def test_a_duplicate_reads_its_one_stored_entry_not_the_log(
    clock: FakeClock, conversation: str
) -> None:
    class CountedReads(ConversationLogRepository):
        def __init__(self) -> None:
            self.read: list[int] = []

        async def read_log(
            self,
            conversation_id: str,
            *,
            user_id: str,
            after_seq: int = 0,
            through_seq: int | None = None,
            ids: Sequence[str] | None = None,
            reply_ids: Sequence[str] | None = None,
        ) -> list[LoggedEntry] | None:
            entries = await super().read_log(
                conversation_id,
                user_id=user_id,
                after_seq=after_seq,
                through_seq=through_seq,
                ids=ids,
                reply_ids=reply_ids,
            )
            self.read.append(len(entries or []))
            return entries

    repository = CountedReads()
    appends = LogAppends(repository, clock)
    for number in range(6):
        await appends.append(conversation, UID, user(f"u{number}"))

    again = await appends.append(conversation, UID, user("u3"))

    assert (again.duplicate, again.logged.seq, again.logged.entry.id) == (True, 4, "u3")
    assert repository.read == [1]


async def test_an_id_whose_seq_holds_a_message_not_a_log_entry_fails_loud(
    appends: LogAppends, conversation: str, entries_collection: AsyncIOMotorCollection
) -> None:
    # A message the entries migration kept: an id and a seq, but no log kind.
    await entries_collection.insert_one(
        {"conversation_id": conversation, "user_id": UID, "id": "legacy", "seq": 1}
    )

    with pytest.raises(ConversationStoreError) as raised:
        await appends.append(conversation, UID, user("legacy"))

    assert raised.value.meta == {"conversation_id": conversation, "seq": 1}
    assert raised.value.message == (
        f"seq 1 of conversation {conversation} holds a message, not a log entry"
    )


async def test_an_append_that_loses_every_write_fails_loud(
    clock: FakeClock, conversation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mongo_log_append, "CONVERSATION_APPEND_MAX_ATTEMPTS", 2)
    repository = LosingRepository(lose_first=99)

    with pytest.raises(ConversationStoreError) as raised:
        await LogAppends(repository, clock).append(conversation, UID, user("m1"))

    assert repository.commits == 2
    assert raised.value.meta == {"conversation_id": conversation}
    assert conversation in raised.value.message
    assert raised.value.why is not None
    assert "2 attempts" in raised.value.why


async def test_a_notice_marks_the_conversation_unread(
    appends: LogAppends, raw_collection: AsyncIOMotorCollection, conversation: str
) -> None:
    await appends.append(conversation, UID, notice("n1"))

    assert await _unread(raw_collection, conversation)


@pytest.mark.parametrize(
    ("asked", "unread"),
    [
        pytest.param(user("m1"), False, id="the-users-message"),
        pytest.param(todo_woke("t1"), False, id="a-todos-wake"),
        pytest.param(notice("m1"), True, id="news-the-user-did-not-ask-for"),
    ],
)
async def test_an_answer_is_unread_only_when_it_answers_nothing_the_user_asked_here(
    appends: LogAppends,
    log: MongoConversationLog,
    raw_collection: AsyncIOMotorCollection,
    conversation: str,
    asked: Entry,
    unread: bool,
) -> None:
    # The earlier message is the user's too, so only the answered entries may decide.
    await _append_all(log, conversation, [user("m0"), asked, opened("o1")])
    await raw_collection.update_one({"conversation_id": conversation}, {"$unset": {"is_unread": 1}})

    await appends.append(conversation, UID, settled("s1", [asked.id], through=2))

    assert await _unread(raw_collection, conversation) is unread


async def test_a_failed_reply_never_marks_unread(
    appends: LogAppends,
    log: MongoConversationLog,
    raw_collection: AsyncIOMotorCollection,
    conversation: str,
) -> None:
    await _append_all(log, conversation, [notice("n1"), opened("o1")])
    await raw_collection.update_one({"conversation_id": conversation}, {"$unset": {"is_unread": 1}})

    await appends.append(
        conversation, UID, settled("s1", ["n1"], through=1, outcome=ReplyOutcome.FAILED)
    )

    assert not await _unread(raw_collection, conversation)


async def test_settling_a_reply_in_a_conversation_the_user_lacks_is_not_found(
    appends: LogAppends,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        await appends.append("c-missing", UID, settled("s1", ["m1"], through=1))
