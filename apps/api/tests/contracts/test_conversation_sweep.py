"""ConversationSweepRepository on real Mongo with its partial index: which heads a sweep and the bot followers visit."""

from __future__ import annotations

from typing import Any

import pytest

from app.constants.chat import ConversationSource
from app.db.mongodb.indexes import CONVERSATION_SWEEP_KEYS, CONVERSATION_SWEEP_OPTIONS
from app.db.repositories.conversation_entries import EMPTY_LOG_STATE
from app.db.repositories.conversation_sweep import ConversationSweepRepository, SweepHead
from app.models.conversation_log_models import LiveWork
from app.services.conversation.mongo_log import MongoConversationLog
from tests.contracts.conftest import HeldFlushes, create_conversation_head
from tests.unit.services.conversation.log_helpers import notice, user
from tests.unit.services.conversation.test_conversation_log_contract import UID

pytestmark = pytest.mark.usefixtures("entries_collection")

_WORK = LiveWork(task_id="t1", cause_through=1, answers=(), pending_approvals=())


@pytest.fixture
async def sweep_index(raw_collection: Any) -> None:
    await raw_collection.create_index(CONVERSATION_SWEEP_KEYS, **CONVERSATION_SWEEP_OPTIONS)


async def _head(raw_collection: Any, name: str, source: ConversationSource | None = None) -> str:
    conversation_id = f"c-{name}"
    await create_conversation_head(conversation_id, UID)
    if source is not None:
        await raw_collection.update_one(
            {"conversation_id": conversation_id}, {"$set": {"source": source.value}}
        )
    return conversation_id


async def _with_work(raw_collection: Any, conversation_id: str) -> None:
    state = EMPTY_LOG_STATE.model_copy(update={"work": (_WORK,)})
    await raw_collection.update_one(
        {"conversation_id": conversation_id}, {"$set": {"state": state.model_dump(mode="json")}}
    )


def _names(heads: list[SweepHead]) -> list[str]:
    return [head.conversation_id for head in heads]


@pytest.fixture
async def due(
    sweep_index: None, raw_collection: Any, log: MongoConversationLog, held: HeldFlushes
) -> dict[str, str]:
    """Five heads in _id order: idle, staged-only, unsettled, working, and a flushed quiet one."""
    idle = await _head(raw_collection, "idle")
    staged = await _head(raw_collection, "staged")
    await log.append(staged, UID, notice("n1"))
    unsettled = await _head(raw_collection, "unsettled")
    await log.append(unsettled, UID, user("u1"))
    await held.run_all()
    working = await _head(raw_collection, "working")
    await _with_work(raw_collection, working)
    quiet = await _head(raw_collection, "quiet")
    await log.append(quiet, UID, notice("n1"))
    await held.run_all()
    await log.append(staged, UID, notice("n2"))
    return {
        "idle": idle,
        "staged": staged,
        "unsettled": unsettled,
        "working": working,
        "quiet": quiet,
    }


async def test_the_sweep_lists_only_due_heads_in_id_order(due: dict[str, str]) -> None:
    heads = await ConversationSweepRepository().list_heads_to_sweep(10, None)

    assert _names(heads) == [due["staged"], due["unsettled"], due["working"]]
    staged, unsettled, working = heads
    assert (staged.user_id, staged.has_outbox, staged.state.unsettled_waking) == (UID, True, ())
    assert unsettled.state.unsettled_waking == (1,)
    assert (working.has_outbox, working.state.work) == (False, (_WORK,))


async def test_the_sweep_pages_by_limit_from_the_cursor_after(due: dict[str, str]) -> None:
    repository = ConversationSweepRepository()

    first = await repository.list_heads_to_sweep(2, None)
    rest = await repository.list_heads_to_sweep(2, first[-1].cursor)

    assert _names(first) == [due["staged"], due["unsettled"]]
    assert _names(rest) == [due["working"]]
    assert await repository.list_heads_to_sweep(2, rest[-1].cursor) == []


async def test_live_heads_are_the_sources_heads_with_work_or_unanswered_inputs(
    sweep_index: None, raw_collection: Any, log: MongoConversationLog, held: HeldFlushes
) -> None:
    telegram = ConversationSource.TELEGRAM
    staged = await _head(raw_collection, "staged", telegram)
    await log.append(staged, UID, notice("n1"))
    unsettled = await _head(raw_collection, "unsettled", telegram)
    await log.append(unsettled, UID, user("u1"))
    working = await _head(raw_collection, "working", telegram)
    await _with_work(raw_collection, working)
    elsewhere = await _head(raw_collection, "elsewhere", ConversationSource.WEB)
    await log.append(elsewhere, UID, user("u1"))
    repository = ConversationSweepRepository()

    live = await repository.list_live_heads(telegram.value, 10)
    capped = await repository.list_live_heads(telegram.value, 2)

    assert sorted(_names(live)) == sorted([unsettled, working])
    assert _names(capped) == [unsettled]
