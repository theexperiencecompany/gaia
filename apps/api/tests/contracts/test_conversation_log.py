"""The conversation log on real Mongo and Redis: the port's contract, the step's scenarios, and the races only a database has."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
import uuid

from hypothesis import HealthCheck, given, settings, strategies as st
import pytest
from redis.asyncio import Redis

from app.constants.chat import ConversationSource
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSyncItem, MessageModel
from app.models.conversation_frame_models import state_frame
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    IntegrationConnected,
    IntegrationNeeded,
    LoggedEntry,
    Rejected,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
)
from app.models.conversation_models import ConversationDocument
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import ClaimLost, EntryRejected
from app.services.conversation.reducer import reduce
from tests.contracts.conftest import HeldFlushes
from tests.helpers import shown_messages
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


async def test_a_duplicate_append_reads_its_one_stored_entry_not_the_log(
    conversation: str, raw_collection: Any
) -> None:
    repository = ConversationLogRepository()
    log = MongoConversationLog(repository, FakeClock())
    for number in range(40):
        await log.append(conversation, UID, user(f"u{number}"))
    read_log = repository.read_log
    read: list[int] = []

    async def counted(*args: Any, **kwargs: Any) -> list[LoggedEntry] | None:
        entries = await read_log(*args, **kwargs)
        read.append(len(entries or []))
        return entries

    with patch.object(repository, "read_log", side_effect=counted):
        again = await log.append(conversation, UID, user("u3"))
    state = await log.state(conversation, UID)
    assert (again.duplicate, again.logged.seq, again.logged.entry.id) == (True, 4, "u3")
    assert (again.previous, again.state, again.effects) == (state, state, ())
    assert read == [1]


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


def _chat() -> list[Entry]:
    """Mix a chat turn, work with an approval, a notice, a workflow run and a todo run."""
    return [
        UserMessage(id="u1", text="find the acme invoice", surface=ConversationSource.WEB),
        started("w", "t1", 1),
        asked("a", "t1", "ap1"),
        decided("d", "ap1"),
        Reply(
            id="o",
            reply_id="r1",
            attempt_id="a1",
            text="found the acme invoice",
            quote_target="u1",
            follow_up_actions=("pay it",),
        ),
        ReplySettled(
            id="s",
            reply_id="r1",
            outcome=ReplyOutcome.ANSWERED,
            answers=("u1",),
            through=1,
            quote_target="u1",
        ),
        finished("f", "t1"),
        notice("n"),
        fired("wf"),
        todo_woke("tw"),
        UserMessage(id="u2", text="thanks", surface=ConversationSource.WEB, reply_to="u1"),
    ]


def _rows(messages: Sequence[MessageModel]) -> list[tuple[object, ...]]:
    return [
        (
            m.type,
            m.message_id,
            m.response,
            m.in_progress,
            m.replyToMessage.id if m.replyToMessage else None,
            bool(m.todo_run_wake),
            m.selectedWorkflow.id if m.selectedWorkflow else None,
        )
        for m in messages
    ]


_HISTORY = [
    ("user", "u1", "find the acme invoice", None, None, False, None),
    ("bot", "r1", "found the acme invoice", None, "u1", False, None),
    ("bot", "n", "delivered", None, None, False, None),
    ("user", "wf", "", None, None, False, "wf_1"),
    ("user", "tw", "", None, None, True, None),
    ("user", "u2", "thanks", None, "u1", False, None),
]


async def _mixed_chat(log: MongoConversationLog) -> tuple[str, str]:
    user_id, conversation_id = f"u-{uuid.uuid4().hex}", f"c-{uuid.uuid4().hex}"
    await _create_head(conversation_id, user_id)
    for entry in _chat():
        await log.append(conversation_id, user_id, entry)
    return user_id, conversation_id


async def test_a_load_a_sync_and_recent_reads_are_the_entries_the_events_stream_sends(
    raw_collection: Any, log: MongoConversationLog
) -> None:
    repo = ConversationRepository()
    user_id, conversation_id = await _mixed_chat(log)
    logged = await log.read_after(conversation_id, user_id, 0)
    state = state_frame(await log.state(conversation_id, user_id))

    doc = await repo.get(conversation_id, user_id=user_id)
    assert doc is not None
    assert (doc.entries, doc.state, doc.has_older, doc.cursor) == (logged, state, False, None)
    assert _rows(shown_messages(doc)) == _HISTORY
    [synced] = await repo.find_updated_since(
        user_id, [ConversationSyncItem(conversation_id=conversation_id, last_updated=None)]
    )
    assert (synced.entries, synced.state) == (logged, state)
    [recent] = await repo.recent_for_user(user_id, limit=1)
    assert recent.entries == logged
    assert await repo.find_owner_of_message(user_id, "r1") == conversation_id
    assert await repo.find_owner_of_message(user_id, "u1") is None
    assert await repo.has_sent_message(user_id)


async def test_a_page_reaches_back_to_the_task_and_the_reply_its_entries_complete(
    raw_collection: Any, log: MongoConversationLog
) -> None:
    repo = ConversationRepository()
    user_id, conversation_id = await _mixed_chat(log)
    finished_seq, settled_seq = 7, 6

    work = await repo.read_entries_before(
        conversation_id, user_id=user_id, before_seq=finished_seq + 1, limit=1
    )
    reply = await repo.read_entries_before(
        conversation_id, user_id=user_id, before_seq=settled_seq + 1, limit=1
    )

    assert work is not None and reply is not None
    assert [logged.entry.id for logged in work.entries] == ["w", "a", "d", "o", "s", "f"]
    assert (work.has_older, work.cursor) == (True, 2)
    assert [logged.entry.id for logged in reply.entries] == ["o", "s"]
    assert (reply.has_older, reply.cursor) == (True, 5)


async def test_an_unsettled_reply_reads_in_progress_and_a_failed_one_names_why(
    raw_collection: Any, log: MongoConversationLog
) -> None:
    repo = ConversationRepository()
    user_id, conversation_id = f"u-{uuid.uuid4().hex}", f"c-{uuid.uuid4().hex}"
    await _create_head(conversation_id, user_id)
    for entry in (
        user("u1"),
        opened("o1", "r1"),
        settled("s1", ["u1"], 1, reply_id="r1", outcome=ReplyOutcome.FAILED),
        user("u2"),
        opened("o2", "r2"),
    ):
        await log.append(conversation_id, user_id, entry)

    doc = await repo.get(conversation_id, user_id=user_id)
    assert doc is not None
    assert [(m.message_id, m.in_progress, m.error) for m in shown_messages(doc)] == [
        ("u1", None, None),
        ("r1", None, "server_restart"),
        ("u2", None, None),
        ("r2", True, None),
    ]


async def test_search_reads_the_text_of_messages_replies_and_notices_only(
    raw_collection: Any, log: MongoConversationLog
) -> None:
    repo = ConversationRepository()
    user_id, conversation_id = await _mixed_chat(log)

    found = await repo.search(user_id, pattern="acme")
    assert [(hit.conversation_id, *_rows([hit.message])) for hit in found.messages] == [
        (conversation_id, _HISTORY[0]),
        (conversation_id, _HISTORY[1]),
    ]
    assert [
        hit.message.message_id for hit in (await repo.search(user_id, pattern="deliver")).messages
    ] == ["n"]
    assert (await repo.search(user_id, pattern="Watch the Acme")).messages == []


async def test_the_newest_page_is_the_newest_entries_when_none_completes_an_older_one(
    raw_collection: Any, log: MongoConversationLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversations_module, "CONVERSATION_READ_LIMIT", 2)
    repo = ConversationRepository()
    user_id, conversation_id = await _mixed_chat(log)

    doc = await repo.get(conversation_id, user_id=user_id)
    assert doc is not None
    assert [logged.entry.id for logged in doc.entries] == ["tw", "u2"]
    assert (doc.has_older, doc.cursor) == (True, 10)


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
