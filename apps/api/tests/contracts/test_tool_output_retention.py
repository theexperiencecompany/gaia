"""Cards older than the retention lose their tool outputs and thinking; the cards, recent entries and MCP App data stay.

Real seams: Mongo (a conversation head, its outbox flushed into conversation_entries with their
real indexes) and the ARQ task the daily cron runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.conversation import TOOL_OUTPUT_RETENTION
from app.db.repositories.conversation_entries import OUTPUTS_DROPPED_FIELD
from app.db.repositories.conversation_log import conversation_log_repository
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
from app.workers.tasks.conversation_retention_tasks import drop_expired_tool_outputs
from shared.py.conversation_wire import ReplyItem, ToolDataEntry
from tests.helpers import shown_items

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

    swept = await _stored(entries_collection, old)
    assert await drop_expired_tool_outputs({}) == "entries=0 bytes_freed=0"
    assert await _stored(entries_collection, old) == swept

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
