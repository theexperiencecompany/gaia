"""A finished work Mongo refuses for its size, on real Mongo and Redis: saved without its cards, its cause logged."""

from dataclasses import replace

import bson
from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.conversation import WORK_ENDED_KEY_PREFIX
from app.db.redis import AsyncRedisCommands
from app.models.conversation_log_models import WorkFinished, WorkOutcome
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.work_log import WorkReport, record_work_finished
from shared.py.conversation_wire import ToolDataEntry
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import started, user
from tests.unit.services.conversation.runtime_doubles import Runtime
from tests.unit.services.conversation.test_conversation_log_contract import UID

MEGABYTE = 1024 * 1024
MONGO_DOCUMENT_CAP = 16 * MEGABYTE
BSON_OBJECT_TOO_LARGE = 10334


def _cards(megabytes: int) -> list[ToolDataEntry]:
    return [{"tool_name": "search", "data": {"rows": "r" * megabytes * MEGABYTE}}]


@pytest.fixture
async def running(
    log: MongoConversationLog,
    conversation: str,
    entries_collection: AsyncIOMotorCollection[dict[str, object]],
) -> Runtime:
    """Return the runtime of a conversation on the real log, with work t1 and t2 running.

    The entries collection has its indexes first: a flush relies on them to store an entry once.
    """
    runtime = Runtime()
    install_runtime_ports(replace(runtime.ports, log=log))
    for entry in (user("m1"), started("w1", "t1", 1), started("w2", "t2", 1)):
        await log.append(conversation, UID, entry)
    return runtime


async def _finished(log: MongoConversationLog, conversation: str) -> dict[str, WorkFinished]:
    logged = await log.read_after(conversation, UID, 0)
    return {e.entry.task_id: e.entry for e in logged if isinstance(e.entry, WorkFinished)}


@pytest.mark.usefixtures("running")
async def test_a_finish_that_would_grow_its_head_past_the_cap_is_saved_without_its_cards(
    log: MongoConversationLog, conversation: str, redis: AsyncRedisCommands
) -> None:
    # The step these finishes kick never runs here, so the first one still waits in the head.
    await record_work_finished(
        conversation, UID, "t1", WorkOutcome.DONE, WorkReport("first", _cards(9))
    )

    async with captured_wide_event() as event:
        await record_work_finished(
            conversation, UID, "t2", WorkOutcome.DONE, WorkReport("second", _cards(9))
        )

    finished = await _finished(log, conversation)
    assert (finished["t1"].report, len(finished["t1"].tool_data)) == ("first", 1)
    assert (finished["t2"].outcome, finished["t2"].report, finished["t2"].tool_data) == (
        WorkOutcome.DONE,
        "second",
        (),
    )
    refused, gave_up = event["errors"]
    assert 9 * MEGABYTE < refused.pop("entry_bytes") < MONGO_DOCUMENT_CAP
    assert refused == {
        "msg": "conversation store call failed",
        "operation": "log append",
        "error_type": "WriteError",
        "mongo_code": BSON_OBJECT_TOO_LARGE,
        "too_large": True,
    }
    assert gave_up == {
        "msg": "work finish refused by the conversation store",
        "conversation_id": conversation,
        "task_id": "t2",
        "error_type": "ConversationStoreError",
        "too_large": True,
        "cards": 1,
    }
    assert [w["msg"] for w in event["warnings"]][-1] == "work finish saved without its cards"
    assert await redis.keys(f"{WORK_ENDED_KEY_PREFIX}*") == []


@pytest.mark.usefixtures("running")
async def test_a_finish_the_driver_will_not_send_is_saved_without_its_cards(
    log: MongoConversationLog, conversation: str
) -> None:
    cards = _cards(17)

    async with captured_wide_event() as event:
        await record_work_finished(
            conversation, UID, "t1", WorkOutcome.DONE, WorkReport("r", cards)
        )

    assert (await _finished(log, conversation))["t1"].tool_data == ()
    refused = event["errors"][0]
    assert refused["entry_bytes"] > len(bson.encode({"cards": cards}))
    assert (refused["error_type"], refused["mongo_code"], refused["too_large"]) == (
        "DocumentTooLarge",
        None,
        True,
    )
