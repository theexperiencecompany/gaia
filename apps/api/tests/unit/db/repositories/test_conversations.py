"""The conversation settlement writes, at the Mongo-query boundary.

``tests/contracts/test_conversations_repository.py`` proves these against real
Mongo, but the whole contract suite skips without ``USE_REAL_SERVICES=1`` — so
on a hermetic run (and in the mutation gate, which never starts a database)
nothing executes these methods at all. These pin the query documents they emit:
which document is matched, which element is written, and what a miss reports.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ToolDataEntry


@pytest.fixture
def collection(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The repository's collection handle, recording ``update_one`` calls.

    Matching one document is the default; a test that is about the miss path
    sets ``matched_count`` to 0 itself.
    """
    from app.db.redis import redis_cache

    monkeypatch.setattr(redis_cache, "redis", None)
    handle = MagicMock()
    handle.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: handle)
    return handle


@pytest.fixture
def repo() -> ConversationRepository:
    return ConversationRepository()


def _call(collection: MagicMock) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The emitted (filter, update, kwargs) of the single recorded write."""
    collection.update_one.assert_awaited_once()
    args = collection.update_one.await_args
    return args.args[0], args.args[1], args.kwargs


class TestSetMessageResponse:
    async def test_writes_the_response_onto_the_named_message_of_the_named_user(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """Both keys are load-bearing: message_id picks the element, user_id is
        what stops one user settling another user's turn."""
        assert await repo.set_message_response(
            "c-1", user_id="u-1", message_id="m-1", response="done"
        )

        filter_, update, _ = _call(collection)
        assert filter_ == {
            "conversation_id": "c-1",
            "messages.message_id": "m-1",
            "user_id": "u-1",
        }
        assert update == {"$set": {"messages.$.response": "done"}}

    async def test_a_write_that_matched_nothing_reports_failure(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """Callers branch on this; a blanket True would hide a lost response."""
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.set_message_response(
            "c-1", user_id="u-1", message_id="missing", response="done"
        )


class TestSetMessageToolData:
    async def test_replaces_the_entries_wholesale(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """A ``$push`` here would double every card on a re-delivery."""
        entries: list[ToolDataEntry] = [{"tool_name": "calendar_options", "data": {"n": 1}}]

        assert await repo.set_message_tool_data(
            "c-1", user_id="u-1", message_id="m-1", entries=entries
        )

        filter_, update, _ = _call(collection)
        assert filter_ == {
            "conversation_id": "c-1",
            "messages.message_id": "m-1",
            "user_id": "u-1",
        }
        assert update == {"$set": {"messages.$.tool_data": entries}}

    async def test_a_write_that_matched_nothing_reports_failure(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.set_message_tool_data(
            "c-1", user_id="u-1", message_id="missing", entries=[]
        )


class TestSetMessageApprovalStatus:
    async def test_the_approval_id_narrows_the_matched_document(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """Array filters pick which element is written but never narrow the
        match, so a filter on the conversation alone reported success for an
        approval the document never held."""
        assert await repo.set_message_approval_status(
            "c-1", user_id="u-1", approval_id="a-1", status="approved"
        )

        filter_, update, kwargs = _call(collection)
        assert filter_ == {
            "conversation_id": "c-1",
            "messages.tool_data.data.approval_id": "a-1",
            "user_id": "u-1",
        }
        assert update == {"$set": {"messages.$[msg].tool_data.$[entry].data.status": "approved"}}
        assert kwargs["array_filters"] == [
            {"msg.tool_data": {"$elemMatch": {"data.approval_id": "a-1"}}},
            {"entry.data.approval_id": "a-1"},
        ]

    async def test_an_unknown_approval_reports_failure(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """The return value is how the HIL resume path learns the frame was
        already settled (or never existed)."""
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.set_message_approval_status(
            "c-1", user_id="u-1", approval_id="unknown", status="approved"
        )


class TestSettlementWritesDoNotTouchTheConversationTimestamp:
    async def test_no_settlement_write_stamps_updatedat(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """Settling a message is not conversation activity — stamping it would
        reorder the sidebar every time a background delivery lands."""
        await repo.set_message_response("c-1", user_id="u-1", message_id="m-1", response="done")
        await repo.set_message_tool_data("c-1", user_id="u-1", message_id="m-1", entries=[])
        await repo.set_message_approval_status(
            "c-1", user_id="u-1", approval_id="a-1", status="approved"
        )

        for call in collection.update_one.await_args_list:
            assert "updatedAt" not in call.args[1].get("$set", {})
            assert "updated_at" not in call.args[1].get("$set", {})


class TestSettlementWritesDeclareTheirCacheScope:
    async def test_every_settlement_write_is_scoped_to_the_owner_and_the_conversation(
        self, repo: ConversationRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserted at the write seam rather than through Mongo on purpose: this
        collection sets ``cache_policy = None``, so today these two arguments
        reach an eviction that does nothing. They are still what the write
        declares its cache identity to be, and the day the conversations
        collection gets a policy, a wrong scope evicts another user's entry and
        a missing ``doc_id`` leaves the settled turn cached as unsettled.
        """
        seam = AsyncMock(return_value=1)
        monkeypatch.setattr(ConversationRepository, "_apply_raw_update_unfetched", seam)

        await repo.set_message_response("c-1", user_id="u-1", message_id="m-1", response="done")
        await repo.set_message_tool_data("c-1", user_id="u-1", message_id="m-1", entries=[])
        await repo.set_message_approval_status(
            "c-1", user_id="u-1", approval_id="a-1", status="approved"
        )

        assert [(call.kwargs["scope"], call.kwargs["doc_id"]) for call in seam.await_args_list] == [
            ("u-1", "c-1")
        ] * 3
