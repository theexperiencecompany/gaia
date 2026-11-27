"""Hermetic unit tests for ConversationRepository's in-place writes and activation-signal count.

The real-Mongo proof lives in tests/contracts/test_conversations_repository.py;
this tier pins the exact filter, update document and array_filters the
repository hands the driver. The driver is mocked at
app.db.repositories.base.get_async_collection, the single seam every write
in the base repository goes through.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.chat import ConversationSource
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversation_entries import (
    EntryWindow,
    StoredRow,
    head_from_raw,
    log_document,
)
from app.db.repositories.conversations import (
    ConversationRepository,
    read_beside,
    union_with_outboxes,
)
from app.models.conversation_log_models import (
    Entry,
    LoggedEntry,
    Notice,
    Reply,
    ReplySettled,
    UserMessage,
)
from app.models.conversation_screen_models import NoticeItem
from app.utils.artifact_utils import FILE_LINKS
from shared.py.conversation_wire import ReplyOutcome, ToolDataEntry

CONVERSATION_ID = "conv-1"
USER_ID = "user-1"
APPROVAL_ID = "appr-1"
TOOL_DATA_ENTRIES: list[ToolDataEntry] = [{"tool_name": "search", "data": {"ok": True}}]


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    """Return the mocked Mongo collection every repository write lands on."""
    mock = MagicMock()
    mock.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
    mock.count_documents = AsyncMock(return_value=0)
    with patch(
        "app.db.repositories.base.get_async_collection", return_value=mock
    ) as get_collection:
        mock.get_collection = get_collection
        yield mock


@pytest.fixture
def repo() -> ConversationRepository:
    return ConversationRepository()


def _update_call(
    collection: MagicMock,
) -> tuple[dict[str, Any], dict[str, Any] | list[dict[str, Any]], dict[str, Any]]:
    """Return the single update_one call's filter, update (a document or a pipeline) and kwargs."""
    collection.update_one.assert_awaited_once()
    args, kwargs = collection.update_one.await_args
    return args[0], args[1], kwargs


class TestBackgroundVisibility:
    def _matches(self, repo: ConversationRepository, doc: dict[str, object]) -> bool:
        """Evaluate the active filter against a stub doc (equality subset)."""

        flt = repo._active_filter(USER_ID)
        if doc.get("user_id") != flt.get("user_id"):
            return False
        # A Mongo filter: $and holds clauses, each an $or of field -> condition branches.
        clauses = cast(list[dict[str, list[dict[str, object]]]], flt["$and"])
        for clause in clauses:
            ok = False
            for branch in clause["$or"]:
                good = True
                for key, cond in branch.items():
                    value = doc.get(key)
                    if isinstance(cond, dict):
                        if "$ne" in cond and value == cond["$ne"]:
                            good = False
                        if "$exists" in cond and (key in doc) != cond["$exists"]:
                            good = False
                    elif value != cond:
                        good = False
                if good:
                    ok = True
                    break
            if not ok:
                return False
        return True

    async def test_background_run_is_hidden_without_a_live_approval(
        self, repo: ConversationRepository
    ) -> None:
        assert (
            self._matches(
                repo,
                {"user_id": USER_ID, "source": "background", "starred": False},
            )
            is False
        )

    async def test_sourceless_legacy_row_stays_visible(self, repo: ConversationRepository) -> None:
        assert self._matches(repo, {"user_id": USER_ID, "starred": False}) is True

    async def test_null_starred_reads_as_unstarred(self, repo: ConversationRepository) -> None:
        """Several write paths store explicit null: a null-starred web row must stay listed."""
        assert self._matches(repo, {"user_id": USER_ID, "source": "web", "starred": None}) is True

    async def test_web_conversation_ignores_the_flag(self, repo: ConversationRepository) -> None:
        assert self._matches(repo, {"user_id": USER_ID, "source": "web", "starred": False}) is True


class TestOwnerIds:
    async def test_it_collects_every_user_holding_the_conversation_id(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        collection.distinct = AsyncMock(return_value=["first", "second"])

        owners = await repo.owner_ids(CONVERSATION_ID)

        assert owners == {"first", "second"}
        collection.distinct.assert_awaited_once()
        args = collection.distinct.await_args.args
        assert args[0] == "user_id"
        assert args[1] == {"conversation_id": CONVERSATION_ID}


_AT = datetime(2026, 1, 2, tzinfo=UTC)


def _row(seq: int, entry: Entry) -> StoredRow:
    return StoredRow(
        conversation_id=CONVERSATION_ID, logged=LoggedEntry(seq=seq, at=_AT, entry=entry)
    )


async def test_a_field_write_tells_the_users_clients_the_row_changed(
    repo: ConversationRepository, collection: MagicMock
) -> None:
    announce = AsyncMock()
    with patch.object(websocket_manager, "announce", announce):
        assert await repo.set_starred(CONVERSATION_ID, user_id=USER_ID, starred=True) is True
        for _ in range(5):
            await asyncio.sleep(0)

    announce.assert_awaited_once_with(
        USER_ID, {"type": "conversation.list_changed", "conversation_id": CONVERSATION_ID}
    )


async def test_a_hit_reads_its_settle_then_the_message_the_settle_quotes_asking_each_once() -> None:
    reply = Reply(id="o-r1", reply_id="r1", attempt_id="a1", text="the answer")
    settle = ReplySettled(
        id="settle:r1",
        reply_id="r1",
        outcome=ReplyOutcome.ANSWERED,
        answers=("u1",),
        through=1,
        quote_target="u1",
    )
    asked = UserMessage(id="u1", text="the question", surface=ConversationSource.WEB)
    stored = [_row(1, asked), _row(3, settle)]
    calls: list[tuple[list[str], list[str]]] = []

    async def lookup(ids: Sequence[str], reply_ids: Sequence[str]) -> list[StoredRow]:
        calls.append((list(ids), list(reply_ids)))
        return [
            row
            for row in stored
            if row.logged.entry.id in ids
            or getattr(row.logged.entry, "reply_id", None) in reply_ids
        ]

    related = await read_beside([_row(2, reply)], lookup)

    assert related == [_row(3, settle), _row(1, asked)]
    assert calls == [(["work:r1:finished", "work:r1:lost"], ["r1"]), (["u1"], [])]


def test_a_stored_copy_newer_than_the_heads_outbox_snapshot_wins_the_read() -> None:
    draft = Reply(id="o-r1", reply_id="r1", attempt_id="a1", text="dra", revision=1)
    done = draft.model_copy(update={"text": "draft", "revision": 2})
    staged = log_document(CONVERSATION_ID, USER_ID, LoggedEntry(seq=1, at=_AT, entry=draft))
    head = head_from_raw(
        {
            "conversation_id": CONVERSATION_ID,
            "user_id": USER_ID,
            "log_head": 1,
            "outbox": {"1": staged},
        }
    )
    flushed = log_document(CONVERSATION_ID, USER_ID, LoggedEntry(seq=1, at=_AT, entry=done))

    [(_, entries)] = union_with_outboxes([head], [flushed], EntryWindow())

    assert [(entry.seq, entry.revision) for entry in entries] == [(1, 2)]


async def test_an_artifact_registry_write_touches_only_its_users_conversation(
    repo: ConversationRepository, collection: MagicMock
) -> None:
    await repo.set_artifacts(CONVERSATION_ID, user_id=USER_ID, entries=[])

    filter_, update, _ = _update_call(collection)
    assert filter_ == {"conversation_id": CONVERSATION_ID, "user_id": USER_ID}
    assert update == {"$set": {"artifacts": []}}


async def test_a_pinned_message_links_its_files_to_its_own_conversation(
    repo: ConversationRepository,
) -> None:
    notice = Notice(id="n1", text="Wrote /workspace/sessions/s1/artifacts/a.csv", origin="reminder")
    reads = iter([[_row(1, notice)]])

    async def find_entries(_user_id: str, _match: object) -> list[StoredRow]:
        return next(reads, [])

    with patch.object(repo, "_find_entries", side_effect=find_entries):
        [hit] = await repo.list_pinned_messages(USER_ID)

    assert isinstance(hit.item, NoticeItem)
    assert hit.item.bubbles == (f"Wrote [a.csv]({FILE_LINKS.conversation_page(CONVERSATION_ID)})",)
