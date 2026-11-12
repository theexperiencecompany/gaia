"""Hermetic unit tests for ConversationRepository's in-place writes and activation-signal count.

The real-Mongo proof lives in tests/contracts/test_conversations_repository.py;
this tier pins the exact filter, update document and array_filters the
repository hands the driver. The driver is mocked at
app.db.repositories.base.get_async_collection, the single seam every write
in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.cache import CachePolicy
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import MessageModel, ToolDataEntry

CONVERSATION_ID = "conv-1"
USER_ID = "user-1"
APPROVAL_ID = "appr-1"
CACHE_POLICY = CachePolicy(prefix="test-conversations")
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


def _update_call(collection: MagicMock) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the single update_one call's filter, update document and kwargs."""
    collection.update_one.assert_awaited_once()
    args, kwargs = collection.update_one.await_args
    return args[0], args[1], kwargs


def _matched(collection: MagicMock, count: int) -> None:
    collection.update_one.return_value = MagicMock(matched_count=count, upserted_id=None)


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

    async def test_background_run_surfaces_while_it_holds_approval(
        self, repo: ConversationRepository
    ) -> None:
        assert (
            self._matches(
                repo,
                {
                    "user_id": USER_ID,
                    "source": "background",
                    "starred": False,
                    "has_live_approval": True,
                },
            )
            is True
        )

    async def test_sourceless_legacy_row_stays_visible(self, repo: ConversationRepository) -> None:
        assert self._matches(repo, {"user_id": USER_ID, "starred": False}) is True

    async def test_null_starred_reads_as_unstarred(self, repo: ConversationRepository) -> None:
        """Several write paths store explicit null: a null-starred background row with a live approval must surface, not vanish."""
        assert (
            self._matches(
                repo,
                {
                    "user_id": USER_ID,
                    "source": "background",
                    "starred": None,
                    "has_live_approval": True,
                },
            )
            is True
        )
        assert (
            self._matches(
                repo,
                {"user_id": USER_ID, "source": "background", "starred": None},
            )
            is False
        )

    async def test_web_conversation_ignores_the_flag(self, repo: ConversationRepository) -> None:
        assert self._matches(repo, {"user_id": USER_ID, "source": "web", "starred": False}) is True

    async def test_mark_raises_flag_and_stamps_source_only_when_missing(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        assert (
            await repo.mark_background_with_live_approval(CONVERSATION_ID, user_id=USER_ID) is True
        )

        first, second = collection.update_one.await_args_list
        assert first.args[1] == {"$set": {"has_live_approval": True}}
        assert second.args[0]["source"] == {"$exists": False}
        assert second.args[1] == {"$set": {"source": "background"}}

    async def test_mark_on_missing_conversation_touches_nothing(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        _matched(collection, 0)

        assert (
            await repo.mark_background_with_live_approval(CONVERSATION_ID, user_id=USER_ID) is False
        )
        collection.update_one.assert_awaited_once()

    async def test_refresh_rewrites_the_flag(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.refresh_live_approval_flag(CONVERSATION_ID, user_id=USER_ID, live=False)

        flt, update, _kwargs = _update_call(collection)
        assert update == {"$set": {"has_live_approval": False}}


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


class TestFillMessage:
    async def test_the_opened_entry_takes_the_saved_reply_and_drops_its_in_progress_mark(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        reply = MessageModel(
            type="bot", response="Done.", message_id="bot-1", tool_data=TOOL_DATA_ENTRIES
        )

        assert await repo.fill_message(CONVERSATION_ID, user_id=USER_ID, message=reply) is True

        query, pipeline, _ = _update_call(collection)
        assert query == {"user_id": USER_ID, "conversation_id": CONVERSATION_ID, "id": "bot-1"}
        [set_stage, unset_stage] = pipeline
        assert set_stage["$set"]["response"] == {"$literal": "Done."}
        cards = {
            "$concatArrays": [{"$literal": TOOL_DATA_ENTRIES}, {"$ifNull": ["$tool_data", []]}]
        }
        assert set_stage["$set"]["tool_data"] == {
            "$cond": [{"$eq": [cards, []]}, "$$REMOVE", cards]
        }
        assert "in_progress" in unset_stage["$unset"]
        assert "pinned" not in unset_stage["$unset"]
