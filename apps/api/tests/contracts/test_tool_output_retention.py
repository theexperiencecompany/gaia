"""Cards older than the retention lose their tool outputs and thinking; the cards, recent entries and MCP App data stay.

Real seams: Mongo (a conversation head, its outbox flushed into conversation_entries with their
real indexes) and the ARQ task the daily cron runs.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
import uuid

import bson
import pytest

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.conversation import TOOL_OUTPUT_RETENTION
from app.db.repositories.conversation_entries import OUTPUTS_DROPPED_FIELD
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversation_output_retention import (
    EntryCards,
    tool_output_retention_repository,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice, Reply, UserMessage
from app.models.conversation_models import ConversationDocument
from app.models.conversation_screen_models import NoticeItem
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.tool_cards import (
    MCP_APP_CARD,
    OUTPUT_ORIGINAL_LENGTH,
    REASONING_STEP,
    TOOL_CALLS_CARD,
)
from app.utils.errors import ConversationStoreError
from app.workers.tasks import conversation_retention_tasks
from app.workers.tasks.conversation_retention_tasks import drop_expired_tool_outputs
from shared.py.conversation_wire import ReplyItem, ToolDataEntry
from tests.helpers import captured_wide_event, shown_items

pytestmark = pytest.mark.usefixtures("entries_collection")

RESULT = "rows of the forecast " * 50
THOUGHT = "the user wants the weekend forecast"
APP_DATA = {"content": [{"type": "text", "text": RESULT}], "structuredContent": {"days": 3}}


def _call(call_id: str, output: str) -> dict[str, object]:
    return {
        "tool_name": "get_forecast",
        "tool_call_id": call_id,
        "message": "Get forecast",
        "inputs": {"city": "Pune"},
        "output": output,
    }


def _thinking() -> dict[str, object]:
    return {
        "tool_name": REASONING_STEP,
        "tool_category": REASONING_STEP,
        "message": "",
        "reasoning": THOUGHT,
    }


def _cards() -> tuple[ToolDataEntry, ...]:
    calls: ToolDataEntry = {
        "tool_name": TOOL_CALLS_CARD,
        "data": [_thinking(), _call("tc-1", RESULT)],
    }
    nested = {
        "subagent_id": "sa-2",
        "subagent_name": "Weather",
        "tool_calls": [_call("tc-3", RESULT)],
    }
    group: ToolDataEntry = {
        "tool_name": SUBAGENT_GROUP_TOOL_NAME,
        "tool_category": "subagent",
        "data": {
            "subagent_id": "sa-1",
            "subagent_name": "Planner",
            "tool_calls": [_thinking(), _call("tc-2", RESULT)],
            "nested_subagents": [nested],
        },
    }
    app: ToolDataEntry = {
        "tool_name": MCP_APP_CARD,
        "data": {"tool_call_id": "tc-4", "tool_result": APP_DATA},
    }
    return (calls, group, app)


async def _chat(repo: ConversationRepository) -> ConversationDocument:
    """Store a chat whose reply and notice carry cards, flushed into conversation_entries."""
    doc = ConversationDocument.model_validate(
        {
            "user_id": f"u-{uuid.uuid4().hex}",
            "conversation_id": f"c-{uuid.uuid4().hex}",
            "source": "web",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    )
    await repo.create(doc)
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    reply_id = f"r-{uuid.uuid4().hex}"
    for entry in (
        UserMessage(id=f"u-{uuid.uuid4().hex}", text="forecast?", surface=ConversationSource.WEB),
        Reply(
            id=f"o-{reply_id}",
            reply_id=reply_id,
            attempt_id="a1",
            text="sunny",
            tool_data=_cards(),
        ),
        Notice(id=f"n-{uuid.uuid4().hex}", text="rain later", origin="test", tool_data=_cards()),
    ):
        await log.append(doc.conversation_id, doc.user_id, entry)
    await repo.flush_outbox(doc.conversation_id, user_id=doc.user_id)
    return doc


async def _stored(entries_collection, doc: ConversationDocument) -> list[dict[str, object]]:
    cursor = entries_collection.find(
        {"conversation_id": doc.conversation_id, "tool_data.0": {"$exists": True}},
        {"_id": 0},
        sort=[("seq", 1)],
    )
    return [row async for row in cursor]


def _cut_call(call_id: str) -> dict[str, object]:
    return {**_call(call_id, ""), OUTPUT_ORIGINAL_LENGTH: len(RESULT)}


async def test_old_cards_lose_outputs_and_thinking_while_recent_ones_and_app_data_stay(
    entries_collection,
) -> None:
    repo = ConversationRepository()
    old, recent = await _chat(repo), await _chat(repo)
    aged = datetime.now(UTC) - TOOL_OUTPUT_RETENTION - timedelta(days=1)
    await entries_collection.update_many(
        {"conversation_id": old.conversation_id}, {"$set": {"at": aged}}
    )
    recent_before = await _stored(entries_collection, recent)

    summary = await drop_expired_tool_outputs({})

    assert summary.startswith("entries=2 ")
    calls, group, app = _cards()
    for stored in await _stored(entries_collection, old):
        assert stored[OUTPUTS_DROPPED_FIELD] is True
        assert stored["tool_data"] == [
            {**calls, "data": [_cut_call("tc-1")]},
            {
                **group,
                "data": {
                    **group["data"],
                    "tool_calls": [_cut_call("tc-2")],
                    "nested_subagents": [
                        {
                            "subagent_id": "sa-2",
                            "subagent_name": "Weather",
                            "tool_calls": [_cut_call("tc-3")],
                            "nested_subagents": [],
                        }
                    ],
                },
            },
            app,
        ]
    assert await _stored(entries_collection, recent) == recent_before

    page = await repo.get(old.conversation_id, user_id=old.user_id)
    assert page is not None
    carded = [
        item
        for item in shown_items(old.conversation_id, page)
        if isinstance(item, ReplyItem | NoticeItem)
    ]
    assert [item.bubbles for item in carded] == [("sunny",), ("rain later",)]
    for item in carded:
        assert item.tool_data[2] == app
        [first_call] = item.tool_data[0]["data"]
        assert first_call["output"] == "" and first_call[OUTPUT_ORIGINAL_LENGTH] == len(RESULT)


async def _aged_chat(
    repo: ConversationRepository, entries_collection, age: timedelta
) -> ConversationDocument:
    doc = await _chat(repo)
    await entries_collection.update_many(
        {"conversation_id": doc.conversation_id}, {"$set": {"at": datetime.now(UTC) - age}}
    )
    return doc


def _cards_bytes(rows: list[dict[str, object]]) -> int:
    return sum(len(bson.encode({"tool_data": row["tool_data"]})) for row in rows)


async def test_a_backlog_past_one_page_is_cut_page_by_page_and_totalled(
    entries_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversation_retention_tasks, "TOOL_OUTPUT_DROP_PAGE", 2)
    repo = ConversationRepository()
    past = TOOL_OUTPUT_RETENTION + timedelta(hours=1)
    old = [await _aged_chat(repo, entries_collection, past) for _ in range(3)]
    kept = await _aged_chat(repo, entries_collection, TOOL_OUTPUT_RETENTION - timedelta(hours=1))
    before = [row for doc in old for row in await _stored(entries_collection, doc)]
    kept_before = await _stored(entries_collection, kept)

    async with captured_wide_event() as event:
        summary = await drop_expired_tool_outputs({})

    after = [row for doc in old for row in await _stored(entries_collection, doc)]
    freed = _cards_bytes(before) - _cards_bytes(after)
    assert freed > 0
    assert summary == f"entries=6 bytes_freed={freed}"
    assert event["tool_output_retention"] == {
        "entries_cut": 6,
        "bytes_freed": freed,
        "entries_passed_over": 0,
        "out_of_time": False,
    }
    assert [row[OUTPUTS_DROPPED_FIELD] for row in after] == [True] * 6
    assert await _stored(entries_collection, kept) == kept_before


@pytest.mark.usefixtures("local_time_offset_from_utc")
async def test_the_cutoff_is_a_utc_instant_whatever_zone_the_worker_runs_in(
    entries_collection,
) -> None:
    repo = ConversationRepository()
    nearly = await _aged_chat(repo, entries_collection, TOOL_OUTPUT_RETENTION - timedelta(hours=1))
    before = await _stored(entries_collection, nearly)

    assert await drop_expired_tool_outputs({}) == "entries=0 bytes_freed=0"
    assert await _stored(entries_collection, nearly) == before


async def test_a_second_run_finds_nothing_and_changes_nothing(entries_collection) -> None:
    repo = ConversationRepository()
    old = await _aged_chat(repo, entries_collection, TOOL_OUTPUT_RETENTION + timedelta(days=1))
    assert (await drop_expired_tool_outputs({})).startswith("entries=2 ")
    swept = await _stored(entries_collection, old)

    assert await drop_expired_tool_outputs({}) == "entries=0 bytes_freed=0"
    assert await _stored(entries_collection, old) == swept


async def test_a_page_whose_every_entry_changed_since_it_was_read_fails_loud(
    entries_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = ConversationRepository()
    old = await _aged_chat(repo, entries_collection, TOOL_OUTPUT_RETENTION + timedelta(days=1))
    read = tool_output_retention_repository.list_unswept

    async def read_then_amended(
        at_before: datetime, limit: int, *, excluding: Collection[str] = ()
    ) -> list[EntryCards]:
        page = await read(at_before, limit, excluding=excluding)
        await entries_collection.update_many({}, {"$inc": {"revision": 1}})
        return page

    monkeypatch.setattr(tool_output_retention_repository, "list_unswept", read_then_amended)

    with pytest.raises(ConversationStoreError) as failed:
        await drop_expired_tool_outputs({})
    assert failed.value.message == "the tool output retention sweep stored no entry of a page"
    assert failed.value.meta == {"page": "2"}
    assert all(OUTPUTS_DROPPED_FIELD not in row for row in await _stored(entries_collection, old))


async def test_an_entry_that_changes_after_every_read_is_passed_over_and_the_rest_counted(
    entries_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversation_retention_tasks, "TOOL_OUTPUT_DROP_PAGE", 3)
    repo = ConversationRepository()
    past = TOOL_OUTPUT_RETENTION + timedelta(days=1)
    old = [await _aged_chat(repo, entries_collection, past) for _ in range(2)]
    [moving, *steady] = [row for doc in old for row in await _stored(entries_collection, doc)]
    read = tool_output_retention_repository.list_unswept

    async def read_then_moved(
        at_before: datetime, limit: int, *, excluding: Collection[str] = ()
    ) -> list[EntryCards]:
        page = await read(at_before, limit, excluding=excluding)
        await entries_collection.update_one({"id": moving["id"]}, {"$inc": {"revision": 1}})
        return page

    monkeypatch.setattr(tool_output_retention_repository, "list_unswept", read_then_moved)

    async with captured_wide_event() as event:
        summary = await drop_expired_tool_outputs({})

    after = [row for doc in old for row in await _stored(entries_collection, doc)]
    cut_rows = [row for row in after if row["id"] != moving["id"]]
    freed = _cards_bytes(steady) - _cards_bytes(cut_rows)
    assert summary == f"entries=3 bytes_freed={freed}"
    assert event["tool_output_retention"] == {
        "entries_cut": 3,
        "bytes_freed": freed,
        "entries_passed_over": 1,
        "out_of_time": False,
    }
    [still] = [row for row in after if row["id"] == moving["id"]]
    assert OUTPUTS_DROPPED_FIELD not in still and still["tool_data"] == moving["tool_data"]


async def test_a_run_out_of_time_stops_between_pages_and_the_next_carries_on(
    entries_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conversation_retention_tasks, "TOOL_OUTPUT_DROP_PAGE", 2)
    # Each reading of the clock is one budget later: the first page spends the whole of it.
    ticks = iter(range(0, 100 * 900, 900))
    monkeypatch.setattr(conversation_retention_tasks, "RUN_BUDGET_SECONDS", 900)
    monkeypatch.setattr(conversation_retention_tasks, "clock", lambda: next(ticks))
    repo = ConversationRepository()
    past = TOOL_OUTPUT_RETENTION + timedelta(days=1)
    old = [await _aged_chat(repo, entries_collection, past) for _ in range(2)]

    async with captured_wide_event() as event:
        assert (await drop_expired_tool_outputs({})).startswith("entries=2 ")
    assert event["tool_output_retention"]["out_of_time"] is True

    assert (await drop_expired_tool_outputs({})).startswith("entries=2 ")
    rows = [row for doc in old for row in await _stored(entries_collection, doc)]
    assert [row.get(OUTPUTS_DROPPED_FIELD) for row in rows] == [True] * 4
