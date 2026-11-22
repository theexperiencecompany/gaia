"""LogReadRepository on real Mongo: log windows over flushed and staged entries, and the unsettled read."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.db.repositories.conversation_log_reads import LogReadRepository
from app.models.conversation_log_models import Entry, LoggedEntry
from app.services.conversation.mongo_log import MongoConversationLog
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import notice, opened, settled, stop, user
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")


async def _append_all(
    log: MongoConversationLog, conversation: str, entries: Sequence[Entry]
) -> None:
    for entry in entries:
        await log.append(conversation, UID, entry)


def _ids(logged: Sequence[LoggedEntry] | None) -> list[tuple[int, str]]:
    assert logged is not None
    return [(entry.seq, entry.entry.id) for entry in logged]


async def test_a_missing_or_foreign_conversation_reads_none(conversation: str) -> None:
    repository = LogReadRepository()

    assert await repository.read_log("c-missing", user_id=UID) is None
    assert await repository.read_log(conversation, user_id="someone-else") is None
    assert await repository.read_unsettled("c-missing", user_id=UID) is None
    assert await repository.read_unsettled(conversation, user_id="someone-else") is None


async def test_an_empty_log_reads_empty(conversation: str) -> None:
    assert await LogReadRepository().read_log(conversation, user_id=UID) == []


@pytest.mark.parametrize("flushed", [False, True])
async def test_the_log_window_is_after_after_seq_through_through_seq_in_seq_order(
    log: MongoConversationLog, conversation: str, held: HeldFlushes, flushed: bool
) -> None:
    await _append_all(log, conversation, [notice("n1"), notice("n2"), notice("n3"), notice("n4")])
    if flushed:
        await held.run_all()
    repository = LogReadRepository()

    every = await repository.read_log(conversation, user_id=UID)
    window = await repository.read_log(conversation, user_id=UID, after_seq=1, through_seq=3)
    tail = await repository.read_log(conversation, user_id=UID, after_seq=2)

    assert _ids(every) == [(1, "n1"), (2, "n2"), (3, "n3"), (4, "n4")]
    assert _ids(window) == [(2, "n2"), (3, "n3")]
    assert _ids(tail) == [(3, "n3"), (4, "n4")]


async def test_ids_and_reply_ids_pick_only_their_entries(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _append_all(
        log, conversation, [user("u1"), opened("open-1", reply_id="r1"), notice("n1")]
    )
    await held.run_all()
    repository = LogReadRepository()

    by_id = await repository.read_log(conversation, user_id=UID, ids=["n1"])
    by_reply = await repository.read_log(conversation, user_id=UID, reply_ids=["r1"])
    either = await repository.read_log(conversation, user_id=UID, ids=["u1"], reply_ids=["r1"])

    assert _ids(by_id) == [(3, "n1")]
    assert _ids(by_reply) == [(2, "open-1")]
    assert _ids(either) == [(1, "u1"), (2, "open-1")]


async def test_the_unsettled_read_is_every_entry_while_nothing_is_settled(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _append_all(log, conversation, [user("u1"), user("u2")])
    await held.run_all()

    read = await LogReadRepository().read_unsettled(conversation, user_id=UID)

    assert read is not None
    state, unsettled = read
    assert (state.head, state.unsettled_waking) == (2, (1, 2))
    assert _ids(unsettled) == [(1, "u1"), (2, "u2")]


async def test_the_unsettled_read_starts_after_what_a_reply_settled(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _append_all(
        log,
        conversation,
        [user("u1"), opened("open-1"), settled("s1", ["u1"], through=1), user("u2")],
    )
    await held.run_all()

    read = await LogReadRepository().read_unsettled(conversation, user_id=UID)

    assert read is not None
    state, unsettled = read
    assert state.settled_through > state.stopped_through
    assert [entry.seq for entry in unsettled] == list(
        range(state.settled_through + 1, state.head + 1)
    )
    assert "u2" in [entry.entry.id for entry in unsettled]
    assert "u1" not in [entry.entry.id for entry in unsettled]


async def test_the_unsettled_read_starts_after_what_a_stop_covered(
    log: MongoConversationLog, conversation: str, held: HeldFlushes
) -> None:
    await _append_all(log, conversation, [user("u1"), user("u2"), stop("x1"), user("u3")])

    read = await LogReadRepository().read_unsettled(conversation, user_id=UID)

    assert read is not None
    state, unsettled = read
    assert (state.stopped_through, state.settled_through) == (2, 0)
    assert _ids(unsettled) == [(3, "x1"), (4, "u3")]
