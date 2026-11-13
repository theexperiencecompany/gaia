"""The conversation log on real Mongo and Redis: the port's contract, the step's scenarios, and the races only a database has."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
import uuid

from hypothesis import HealthCheck, given, settings, strategies as st
import pytest
from redis.asyncio import Redis

from app.constants.chat import ConversationSource
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_entries_migration import (
    ConversationEntriesMigration,
    HeadRef,
)
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSyncItem, MessageModel
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    EntryKind,
    IntegrationConnected,
    IntegrationNeeded,
    LoggedEntry,
    Rejected,
    Reply,
    ReplyOutcome,
)
from app.models.conversation_models import ConversationDocument
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.reducer import reduce
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import (
    EMPTY,
    asked,
    barge,
    decided,
    finished,
    fired,
    notice,
    opened,
    settled,
    started,
    stop,
    todo_woke,
    user,
)
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    FakeClock,
    InMemoryConversationLog,
    LogUnderTest,
    PausingLog,
    Runtime,
)
from tests.unit.services.conversation.test_conversation_log_contract import (
    CID,
    UID,
    ConversationLogContract,
)
from tests.unit.services.conversation.test_step_scenarios import StepScenarios

pytestmark = pytest.mark.usefixtures("entries_collection")


async def _create_head(conversation_id: str, user_id: str) -> None:
    await ConversationRepository().create(
        ConversationDocument.model_validate(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "createdAt": datetime.now(UTC).isoformat(),
            }
        )
    )


def _mongo(
    raw_collection: Any, redis: Redis, conversation_id: str, user_id: str
) -> Callable[[FakeClock], LogUnderTest]:
    def make(clock: FakeClock) -> LogUnderTest:
        log = PausingLog(MongoConversationLog(ConversationLogRepository(), clock))

        async def lapse() -> None:
            head = await raw_collection.find_one(
                {"conversation_id": conversation_id, "user_id": user_id}
            )
            await redis.delete(head["runner"]["alive_key"])

        return LogUnderTest(log=log, lapse=lapse)

    return make


@pytest.fixture
async def contract_head() -> None:
    await _create_head(CID, UID)


@pytest.fixture
async def scenario_head() -> None:
    await _create_head(CONVERSATION, USER)


class TestMongoConversationLog(ConversationLogContract):
    @pytest.fixture
    def subject(self, contract_head: None, raw_collection: Any, redis: Redis) -> LogUnderTest:
        return _mongo(raw_collection, redis, CID, UID)(FakeClock())


class TestStepScenariosOnMongo(StepScenarios):
    @pytest.fixture
    def rt(self, scenario_head: None, raw_collection: Any, redis: Redis) -> Runtime:
        return Runtime(make_log=_mongo(raw_collection, redis, CONVERSATION, USER))


@pytest.fixture
def log() -> MongoConversationLog:
    return MongoConversationLog(ConversationLogRepository(), FakeClock())


@pytest.fixture
async def conversation(raw_collection: Any) -> str:
    conversation_id = f"c-{uuid.uuid4().hex}"
    await _create_head(conversation_id, UID)
    return conversation_id


async def test_a_wake_appended_after_the_step_read_nothing_keeps_it_from_releasing(
    log: MongoConversationLog, conversation: str
) -> None:
    claim = await log.claim(conversation, UID)
    assert claim is not None
    assert (await log.state(conversation, UID)).unsettled_waking == ()
    await log.append(conversation, UID, user("u1"))
    assert not await log.release_if_caught_up(claim)
    assert await log.claim(conversation, UID) is None
    assert (await log.state(conversation, UID)).unsettled_waking == (1,)


async def test_a_conversation_with_no_log_yet_is_claimed_and_released(
    log: MongoConversationLog, conversation: str, redis: Redis
) -> None:
    assert await log.state(conversation, UID) == EMPTY
    claim = await log.claim(conversation, UID)
    assert claim is not None
    assert await redis.ttl(f"conv:alive:{UID}:{conversation}:{claim.epoch}") > 0
    assert await log.release_if_caught_up(claim)
    again = await log.claim(conversation, UID)
    assert again is not None and again.epoch == claim.epoch + 1


async def test_of_many_concurrent_claimers_exactly_one_wins(
    log: MongoConversationLog, conversation: str
) -> None:
    claims = await asyncio.gather(*(log.claim(conversation, UID) for _ in range(10)))
    won = [claim for claim in claims if claim is not None]
    assert len(won) == 1
    assert (await log.hint(conversation, UID)).epoch == won[0].epoch


class _ReadThenPause(ConversationLogRepository):
    """Runs pause once, right after the next log read returns: the gap between an amend's read and its write."""

    def __init__(self) -> None:
        self.pause: Callable[[], Awaitable[None]] | None = None

    async def read_log(
        self,
        conversation_id: str,
        *,
        user_id: str,
        after_seq: int = 0,
        through_seq: int | None = None,
        ids: Sequence[str] | None = None,
    ) -> list[LoggedEntry] | None:
        rows = await super().read_log(
            conversation_id, user_id=user_id, after_seq=after_seq, through_seq=through_seq, ids=ids
        )
        pause, self.pause = self.pause, None
        if pause is not None:
            await pause()
        return rows


async def test_a_holder_that_lost_its_claim_mid_amend_never_changes_the_entry(
    conversation: str, redis: Redis, held: HeldFlushes, entries_collection: Any
) -> None:
    stale_repository = _ReadThenPause()
    stale = MongoConversationLog(stale_repository, FakeClock())
    fresh = MongoConversationLog(ConversationLogRepository(), FakeClock())
    await fresh.append(conversation, UID, user("u1"))
    old = await stale.claim(conversation, UID)
    assert old is not None
    reply = opened("o", "r1")
    await stale.append_fenced(old, reply)
    await held.run_all()
    recovered = reply.model_copy(update={"text": "what was shown"})

    async def take_over() -> None:
        await redis.flushdb()
        new = await fresh.claim(conversation, UID)
        assert new is not None
        await fresh.amend(new, recovered)
        await fresh.append_fenced(new, settled("s", [], 1, outcome=ReplyOutcome.FAILED))

    stale_repository.pause = take_over
    with pytest.raises(ClaimLost):
        await stale.amend(old, reply.model_copy(update={"text": "late"}))
    await held.run_all()
    [stored] = [
        item for item in await fresh.read_after(conversation, UID, 0) if item.entry.id == "o"
    ]
    assert stored.entry == recovered.model_copy(update={"revision": 1})
    document = await entries_collection.find_one({"conversation_id": conversation, "id": "o"})
    assert (document["text"], document["revision"]) == ("what was shown", 1)


async def test_a_stale_epoch_cannot_amend_and_a_released_one_cannot_beat(
    log: MongoConversationLog, conversation: str, redis: Redis
) -> None:
    await log.append(conversation, UID, user("u1"))
    old = await log.claim(conversation, UID)
    assert old is not None
    reply = opened("o", "r1")
    await log.append_fenced(old, reply)
    await redis.flushdb()
    new = await log.claim(conversation, UID)
    assert new is not None and new.epoch == old.epoch + 1
    with pytest.raises(ClaimLost):
        await log.amend(old, reply.model_copy(update={"text": "late"}))
    assert not await log.beat(old)
    await log.append_fenced(new, settled("s", ["u1"], 1))
    assert await log.release_if_caught_up(new)
    assert not await log.beat(new)
    [stored] = [item for item in await log.read_after(conversation, UID, 0) if item.entry.id == "o"]
    assert stored.entry == reply


async def test_the_same_id_appended_by_two_tasks_at_once_is_stored_once(
    log: MongoConversationLog, conversation: str, held: HeldFlushes, entries_collection: Any
) -> None:
    results = await asyncio.gather(*(log.append(conversation, UID, user("u1")) for _ in range(4)))
    await held.run_all()
    assert sorted(result.duplicate for result in results) == [False, True, True, True]
    assert {result.logged for result in results} == {results[0].logged}
    assert await entries_collection.count_documents({"conversation_id": conversation}) == 1


@pytest.mark.parametrize("flushed", [False, True])
async def test_amend_updates_the_one_entry_whether_or_not_it_was_flushed(
    log: MongoConversationLog,
    conversation: str,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
    flushed: bool,
) -> None:
    await log.append(conversation, UID, user("u1"))
    claim = await log.claim(conversation, UID)
    assert claim is not None
    reply = opened("o", "r1")
    await log.append_fenced(claim, reply)
    if flushed:
        await held.run_all()
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert bool(head.get("outbox")) is not flushed
    amended = await log.amend(claim, reply.model_copy(update={"text": "hello"}))
    await log.amend(claim, reply.model_copy(update={"text": "hello again"}))
    await held.run_all()
    assert not (await raw_collection.find_one({"conversation_id": conversation})).get("outbox")
    [stored] = await log.read_after(conversation, UID, 1)
    assert isinstance(amended.entry, Reply)
    assert (amended.seq, amended.entry.revision) == (2, 1)
    assert stored.entry == reply.model_copy(update={"text": "hello again", "revision": 2})
    assert (
        await entries_collection.count_documents({"conversation_id": conversation, "id": "o"}) == 1
    )


async def test_an_entry_whose_flush_never_ran_is_read_and_inserted_once_by_the_next_flush(
    log: MongoConversationLog,
    conversation: str,
    held: HeldFlushes,
    raw_collection: Any,
    entries_collection: Any,
) -> None:
    appended = await log.append(conversation, UID, user("u1"))
    held.drop_all()
    before = await log.read_after(conversation, UID, 0)
    assert before == [appended.logged]
    assert await entries_collection.count_documents({"conversation_id": conversation}) == 0
    await ConversationRepository().flush_outbox(conversation, user_id=UID)
    await ConversationRepository().flush_outbox(conversation, user_id=UID)
    assert await log.read_after(conversation, UID, 0) == before
    assert await entries_collection.count_documents({"conversation_id": conversation}) == 1
    head = await raw_collection.find_one({"conversation_id": conversation})
    assert not head.get("outbox")


async def test_an_append_reduced_before_the_comms_phase_changed_does_not_undo_it(
    log: MongoConversationLog, conversation: str
) -> None:
    repository = ConversationLogRepository()
    await log.append(conversation, UID, user("u1"))
    claim = await log.claim(conversation, UID)
    assert claim is not None
    read = await repository.read_log_head(conversation, user_id=UID)
    assert read is not None
    await log.set_comms(claim, CommsPhase.THINKING)
    late = LoggedEntry(seq=2, at=datetime.now(UTC), entry=user("u2"))
    result = reduce(read.state, late)
    assert not isinstance(result, Rejected)
    assert not await repository.commit_log_entry(read, late, result.state, epoch=None)
    await log.append(conversation, UID, user("u2"))
    state = await log.state(conversation, UID)
    assert (state.head, state.comms) == (2, CommsPhase.THINKING)


async def test_a_lost_hint_is_rebuilt_from_the_head(
    log: MongoConversationLog, conversation: str, redis: Redis
) -> None:
    await log.append(conversation, UID, user("u1"))
    claim = await log.claim(conversation, UID)
    assert claim is not None
    await log.append(conversation, UID, stop("s"))
    held = await log.hint(conversation, UID)
    await redis.flushdb()
    assert await log.hint(conversation, UID) == held
    assert (held.head, held.stop_through, held.epoch) == (2, 1, claim.epoch)


_BUILDERS: dict[str, Callable[[str, int, int], Entry]] = {
    "user": lambda entry_id, n, cause: user(entry_id),
    "stop": lambda entry_id, n, cause: stop(entry_id, cause),
    "barge": lambda entry_id, n, cause: barge(entry_id, f"r{n % 3}"),
    "fired": lambda entry_id, n, cause: fired(entry_id),
    "todo": lambda entry_id, n, cause: todo_woke(entry_id),
    "notice": lambda entry_id, n, cause: notice(entry_id),
    "start": lambda entry_id, n, cause: started(entry_id, f"t{n % 3}", max(cause, 1)),
    "ask": lambda entry_id, n, cause: asked(entry_id, f"t{n % 3}", f"ap{n % 3}"),
    "decide": lambda entry_id, n, cause: decided(entry_id, f"ap{n % 3}"),
    "finish": lambda entry_id, n, cause: finished(entry_id, f"t{n % 3}"),
    "open": lambda entry_id, n, cause: opened(entry_id, f"r{n % 3}"),
    "settle": lambda entry_id, n, cause: settled(
        entry_id, ["user1"], max(cause, 1), reply_id=f"r{n % 3}"
    ),
}


def _drawn(kind: str, number: int, cause: int) -> Entry:
    """Build a log entry from a drawn kind; the same draw is the same entry, so repeats are duplicates."""
    return _BUILDERS[kind](f"{kind}{number}", number, cause)


def _fold(entries: Sequence[LoggedEntry]) -> ConversationState:
    state = EMPTY
    for logged in entries:
        result = reduce(state, logged)
        assert not isinstance(result, Rejected), f"seq {logged.seq}: {result.reason}"
        state = result.state
    return state


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    draws=st.lists(
        st.tuples(st.sampled_from(sorted(_BUILDERS)), st.integers(1, 4), st.integers(0, 6)),
        max_size=14,
    )
)
async def test_the_stored_state_is_the_fold_of_the_stored_entries_and_matches_the_in_memory_log(
    raw_collection: Any, draws: list[tuple[str, int, int]]
) -> None:
    conversation_id = f"c-{uuid.uuid4().hex}"
    await _create_head(conversation_id, UID)
    clock = FakeClock()
    mongo = MongoConversationLog(ConversationLogRepository(), clock)
    memory = InMemoryConversationLog(clock)
    for kind, number, cause in draws:
        entry = _drawn(kind, number, cause)
        outcomes: list[object] = []
        for subject in (mongo, memory):
            try:
                appended = await subject.append(conversation_id, UID, entry)
                outcomes.append((appended.logged, appended.state, appended.effects))
            except EntryRejected as rejected:
                outcomes.append(rejected.reason)
        assert outcomes[0] == outcomes[1]
    entries = await mongo.read_after(conversation_id, UID, 0)
    assert [item.seq for item in entries] == list(range(1, len(entries) + 1))
    assert await mongo.state(conversation_id, UID) == _fold(entries)
    assert entries == await memory.read_after(conversation_id, UID, 0)


def _every_kind() -> list[Entry]:
    """One valid run of every kind the log appends, the user message at seq 3 of the mixed conversation."""
    return [
        user("u1"),
        started("w", "t1", 3),
        asked("a", "t1", "ap1"),
        decided("d", "ap1"),
        opened("o", "r1"),
        barge("b", "r1"),
        settled("s", ["u1"], 3),
        finished("f", "t1"),
        fired("wf"),
        todo_woke("tw"),
        notice("n"),
        IntegrationNeeded(id="in", integration_id="gmail", integration_name="Gmail"),
        IntegrationConnected(
            id="ic", integration_id="gmail", integration_name="Gmail", needed_id="in"
        ),
        stop("st"),
    ]


def _messages(prefix: str) -> list[MessageModel]:
    return [
        MessageModel(type="user", response=f"find the {prefix} invoice", message_id=f"{prefix}1"),
        MessageModel(type="bot", response=f"found the {prefix} invoice", message_id=f"{prefix}2"),
        MessageModel(type="user", response="thanks", message_id=f"{prefix}3"),
    ]


async def _message_payloads(user_id: str, conversation_id: str, pattern: str) -> list[object]:
    repo = ConversationRepository()
    doc = await repo.get(conversation_id, user_id=user_id)
    assert doc is not None
    [synced] = await repo.find_updated_since(
        user_id, [ConversationSyncItem(conversation_id=conversation_id, last_updated=None)]
    )
    search = await repo.search(user_id, pattern=pattern)
    pinned = await repo.list_pinned_messages(user_id)
    one = await repo.get_message(conversation_id, f"{pattern}2", user_id=user_id)
    owner = await repo.find_owner_of_message(user_id, f"{pattern}2")

    def shape(messages: Sequence[MessageModel]) -> list[dict[str, object]]:
        return [message.model_dump(exclude={"seq"}) for message in messages]

    return [
        shape(doc.messages),
        shape(synced.messages),
        shape([hit.message for hit in search.messages]),
        shape([hit.message for hit in pinned]),
        shape([one] if one else []),
        owner == conversation_id,
        await repo.has_sent_message(user_id),
    ]


async def test_message_readers_never_see_a_log_entry_of_any_kind(raw_collection: Any) -> None:
    repo = ConversationRepository()
    log = MongoConversationLog(ConversationLogRepository(), FakeClock())
    plain, mixed = (f"u-{uuid.uuid4().hex}", "c-plain"), (f"u-{uuid.uuid4().hex}", "c-mixed")
    for user_id, conversation_id in (plain, mixed):
        await _create_head(conversation_id, user_id)
    first, second, third = _messages("inv")
    for user_id, conversation_id in (plain, mixed):
        await repo.append_messages(conversation_id, user_id=user_id, messages=[first, second])
    kinds = _every_kind()
    for entry in kinds[:6]:
        await log.append(mixed[1], mixed[0], entry)
    for user_id, conversation_id in (plain, mixed):
        await repo.append_messages(conversation_id, user_id=user_id, messages=[third])
        await repo.set_message_pinned(
            conversation_id, user_id=user_id, message_id="inv2", pinned=True
        )
    for entry in kinds[6:]:
        await log.append(mixed[1], mixed[0], entry)
    stored_kinds = {item.entry.kind for item in await log.read_after(mixed[1], mixed[0], 0)}
    assert stored_kinds == set(EntryKind)
    assert await _message_payloads(*mixed, "inv") == await _message_payloads(*plain, "inv")


async def test_whole_conversation_reads_return_the_newest_messages_past_interleaved_log_entries(
    raw_collection: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 2)
    repo = ConversationRepository()
    log = MongoConversationLog(ConversationLogRepository(), FakeClock())
    user_id = f"u-{uuid.uuid4().hex}"
    chats = [f"c-{uuid.uuid4().hex}" for _ in range(2)]
    kinds = _every_kind()
    for conversation_id in chats:
        await _create_head(conversation_id, user_id)
        first, second, third = _messages(conversation_id)
        await repo.append_messages(conversation_id, user_id=user_id, messages=[first, second])
        for entry in kinds[:6]:
            await log.append(conversation_id, user_id, entry)
        await repo.append_messages(conversation_id, user_id=user_id, messages=[third])
        for entry in kinds[6:]:
            await log.append(conversation_id, user_id, entry)

    doc = await repo.get(chats[0], user_id=user_id)
    assert doc is not None
    assert [m.message_id for m in doc.messages] == [f"{chats[0]}2", f"{chats[0]}3"]
    synced = await repo.find_updated_since(
        user_id, [ConversationSyncItem(conversation_id=c, last_updated=None) for c in chats]
    )
    assert {d.conversation_id: [m.message_id for m in d.messages] for d in synced} == {
        c: [f"{c}2", f"{c}3"] for c in chats
    }


async def test_a_chat_shows_it_awaits_approval_exactly_while_its_work_waits_on_the_user(
    raw_collection: Any,
) -> None:
    repo = ConversationRepository()
    log = MongoConversationLog(ConversationLogRepository(), FakeClock())
    user_id, background, web = f"u-{uuid.uuid4().hex}", "c-background", "c-web"
    for conversation_id in (background, web):
        await _create_head(conversation_id, user_id)
        await log.append(conversation_id, user_id, user("u1"))
        await log.append(conversation_id, user_id, started("w", "t1", 1))
    await raw_collection.update_one(
        {"conversation_id": background}, {"$set": {"source": ConversationSource.BACKGROUND}}
    )

    async def shown() -> tuple[dict[str, bool], dict[str, bool]]:
        listed = await repo.list_active_summaries(user_id, skip=0, limit=10)
        synced = await repo.find_updated_since(
            user_id,
            [ConversationSyncItem(conversation_id=c, last_updated=None) for c in (background, web)],
        )
        return (
            {row.conversation_id: row.awaiting_approval for row in listed},
            {doc.conversation_id: doc.awaiting_approval for doc in synced},
        )

    assert await shown() == ({web: False}, {background: False, web: False})
    for conversation_id in (background, web):
        await log.append(conversation_id, user_id, asked("a", "t1", "ap1"))
    assert await shown() == ({background: True, web: True}, {background: True, web: True})
    for conversation_id in (background, web):
        await log.append(conversation_id, user_id, decided("d", "ap1"))
    assert await shown() == ({web: False}, {background: False, web: False})


async def test_a_migrated_conversation_reads_as_an_idle_log_at_its_message_count(
    raw_collection: Any,
) -> None:
    conversation_id = f"c-{uuid.uuid4().hex}"
    messages = [
        {"type": "user" if n % 2 else "bot", "response": f"m{n}", "message_id": f"m{n}"}
        for n in range(1, 6)
    ]
    inserted = await raw_collection.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": UID,
            "createdAt": datetime.now(UTC).isoformat(),
            "updatedAt": datetime.now(UTC),
            "messages": messages,
        }
    )
    await ConversationEntriesMigration().migrate(
        HeadRef(str(inserted.inserted_id), conversation_id, UID), apply=True
    )
    log = MongoConversationLog(ConversationLogRepository(), FakeClock())
    state = await log.state(conversation_id, UID)
    assert (state.head, state.comms, state.unsettled_waking) == (5, CommsPhase.IDLE, ())
    assert await log.read_after(conversation_id, UID, 0) == []
    appended = await log.append(conversation_id, UID, user("u6"))
    assert appended.logged.seq == 6
    doc = await ConversationRepository().get(conversation_id, user_id=UID)
    assert doc is not None
    assert [message.message_id for message in doc.messages] == [f"m{n}" for n in range(1, 6)]
