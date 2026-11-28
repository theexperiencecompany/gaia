"""LogReadRepository on real Mongo: log windows over flushed and staged entries, and the unsettled read."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence

import pytest

from app.db.repositories.conversation_log_reads import LogReadRepository
from app.models.conversation_log_models import Entry, LoggedEntry, ScreenWindow
from app.services.conversation.mongo_log import MongoConversationLog
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import (
    finished,
    notice,
    opened,
    settled,
    started,
    stop,
    user,
)
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
    assert await repository.read_screen("c-missing", user_id=UID, after=None, limit=1) is None


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


def _window(window: ScreenWindow | None) -> tuple[list[str], int]:
    assert window is not None
    return [logged.entry.id for logged in window.entries], window.start


@pytest.mark.parametrize("flushed", [False, True])
async def test_a_screen_window_reaches_back_to_what_its_run_completes_runs_and_reads_beside(
    log: MongoConversationLog, conversation: str, held: HeldFlushes, flushed: bool
) -> None:
    quoting = settled("s2", ["u2"], 4, reply_id="r2").model_copy(update={"quote_target": "u1"})
    entries: list[Entry] = [
        user("u1"),
        notice("n1"),
        user("u2"),
        started("w1", "t1", 3),
        notice("n2"),
        finished("f1", "t1"),
        opened("o2", "r2"),
        quoting,
        started("w2", "t2", 8),
        notice("n3"),
    ]
    await _append_all(log, conversation, entries)
    if flushed:
        await held.run_all()
    repository = LogReadRepository()

    def read(after: int | None, limit: int) -> Awaitable[ScreenWindow | None]:
        return repository.read_screen(conversation, user_id=UID, after=after, limit=limit)

    # Running t2 reaches back to its start; nothing it holds reads anything beside it.
    assert _window(await read(after=9, limit=1)) == (["w2", "n3"], 9)
    # The newest user message is reached for within the newest limit seqs, the quote read beside.
    assert _window(await read(after=7, limit=10)) == (
        ["u1", "u2", "w1", "n2", "f1", "o2", "s2", "w2", "n3"],
        3,
    )
    # A settle reaches back to its reply, a finish to its start.
    assert _window(await read(after=None, limit=5)) == (
        ["u1", "u2", "w1", "n2", "f1", "o2", "s2", "w2", "n3"],
        4,
    )
    assert _window(await read(after=99, limit=1)) == (["w2", "n3"], 9)


async def test_an_empty_log_s_screen_window_is_empty(conversation: str) -> None:
    window = await LogReadRepository().read_screen(conversation, user_id=UID, after=None, limit=1)
    assert _window(window) == ([], 1)


async def test_a_screen_window_after_the_head_holds_only_the_newest_entry_and_its_message(
    log: MongoConversationLog, conversation: str
) -> None:
    await _append_all(log, conversation, [user("u1"), notice("n1")])
    repository = LogReadRepository()

    def read(after: int, limit: int) -> Awaitable[ScreenWindow | None]:
        return repository.read_screen(conversation, user_id=UID, after=after, limit=limit)

    # The message is past the newest seq, so the newest entry stands alone.
    assert _window(await read(after=9, limit=1)) == (["n1"], 2)
    # Within the newest limit seqs, the log's first entry is reached for.
    assert _window(await read(after=9, limit=2)) == (["u1", "n1"], 1)


async def test_a_screen_window_reaches_back_to_the_reply_still_being_written(
    log: MongoConversationLog, conversation: str
) -> None:
    await _append_all(log, conversation, [user("u1"), opened("o1"), user("u2"), notice("n1")])
    window = await LogReadRepository().read_screen(conversation, user_id=UID, after=3, limit=1)
    assert _window(window) == (["o1", "u2", "n1"], 2)
