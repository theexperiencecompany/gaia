"""Hermetic unit tests for ``ConversationRepository``'s in-place message writes.

The real-Mongo proof of these methods lives in
``tests/contracts/test_conversations_repository.py``; this tier pins the exact
filter, update document and ``array_filters`` the repository hands the driver,
which is what the contracts tier cannot see and what the mutation gate needs a
hermetic suite to kill mutants on. The driver is mocked at
``app.db.repositories.base.get_async_collection`` — the single seam every write
in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.cache import CachePolicy
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ToolDataEntry

CONVERSATION_ID = "conv-1"
USER_ID = "user-1"
MESSAGE_ID = "msg-1"
APPROVAL_ID = "appr-1"
CACHE_POLICY = CachePolicy(prefix="test-conversations")
TOOL_DATA_ENTRIES: list[ToolDataEntry] = [{"tool_name": "search", "data": {"ok": True}}]


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    """The mocked Mongo collection every repository write lands on."""
    mock = MagicMock()
    mock.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
    with patch(
        "app.db.repositories.base.get_async_collection", return_value=mock
    ) as get_collection:
        mock.get_collection = get_collection
        yield mock


@pytest.fixture
def repo() -> ConversationRepository:
    return ConversationRepository()


def _update_call(collection: MagicMock) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The single ``update_one`` call's filter, update document and kwargs."""
    collection.update_one.assert_awaited_once()
    args, kwargs = collection.update_one.await_args
    return args[0], args[1], kwargs


def _matched(collection: MagicMock, count: int) -> None:
    collection.update_one.return_value = MagicMock(matched_count=count, upserted_id=None)


class TestSetMessageResponse:
    """``set_message_response`` — background delivery settling a message's text."""

    async def test_targets_the_named_message_of_the_owning_user(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.set_message_response(
            CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, response="the answer"
        )

        filter_, update, kwargs = _update_call(collection)
        assert filter_ == {
            "conversation_id": CONVERSATION_ID,
            "messages.message_id": MESSAGE_ID,
            "user_id": USER_ID,
        }
        assert update == {"$set": {"messages.$.response": "the answer"}}
        assert kwargs["array_filters"] is None
        assert collection.get_collection.call_args.args == ("conversations",)

    async def test_does_not_advance_the_sync_clock(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """Documented invariant: this write leaves ``updatedAt`` alone."""
        await repo.set_message_response(
            CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, response="the answer"
        )

        _filter, update, _kwargs = _update_call(collection)
        assert set(update) == {"$set"}
        assert set(update["$set"]) == {"messages.$.response"}

    async def test_reports_true_when_a_message_matched(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        assert (
            await repo.set_message_response(
                CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, response="x"
            )
            is True
        )

    async def test_reports_false_when_nothing_matched(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        _matched(collection, 0)

        assert (
            await repo.set_message_response(
                CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, response="x"
            )
            is False
        )


class TestSetMessageToolData:
    """``set_message_tool_data`` — delivery re-persisting a message's whole frame list."""

    async def test_replaces_the_whole_list_on_the_named_message(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.set_message_tool_data(
            CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, entries=TOOL_DATA_ENTRIES
        )

        filter_, update, kwargs = _update_call(collection)
        assert filter_ == {
            "conversation_id": CONVERSATION_ID,
            "messages.message_id": MESSAGE_ID,
            "user_id": USER_ID,
        }
        # ``$set`` on the whole array, not ``$push``/``$each`` — a stale entry
        # must not survive the write.
        assert update == {"$set": {"messages.$.tool_data": TOOL_DATA_ENTRIES}}
        assert kwargs["array_filters"] is None

    async def test_does_not_advance_the_sync_clock(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.set_message_tool_data(
            CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, entries=TOOL_DATA_ENTRIES
        )

        _filter, update, _kwargs = _update_call(collection)
        assert set(update) == {"$set"}
        assert set(update["$set"]) == {"messages.$.tool_data"}

    async def test_reports_true_when_a_message_matched(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        assert (
            await repo.set_message_tool_data(
                CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, entries=TOOL_DATA_ENTRIES
            )
            is True
        )

    async def test_reports_false_when_nothing_matched(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        _matched(collection, 0)

        assert (
            await repo.set_message_tool_data(
                CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, entries=[]
            )
            is False
        )


class TestSetMessageApprovalStatus:
    """``set_message_approval_status`` — the HIL bridge settling a persisted
    approval frame wherever it sits in the messages array."""

    async def test_narrows_the_match_by_approval_id_not_just_conversation(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """The array filters pick the element but never narrow ``matched_count``,
        so the approval must be in the query filter too."""
        await repo.set_message_approval_status(
            CONVERSATION_ID, user_id=USER_ID, approval_id=APPROVAL_ID, status="approved"
        )

        filter_, _update, _kwargs = _update_call(collection)
        assert filter_ == {
            "conversation_id": CONVERSATION_ID,
            "messages.tool_data.data.approval_id": APPROVAL_ID,
            "user_id": USER_ID,
        }

    async def test_writes_the_status_through_both_array_filters(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.set_message_approval_status(
            CONVERSATION_ID, user_id=USER_ID, approval_id=APPROVAL_ID, status="approved"
        )

        _filter, update, kwargs = _update_call(collection)
        assert update == {"$set": {"messages.$[msg].tool_data.$[entry].data.status": "approved"}}
        # Both levels are filtered: ``messages.$[]`` would demand tool_data on
        # every message and Mongo rejects the whole update.
        assert kwargs["array_filters"] == [
            {"msg.tool_data": {"$elemMatch": {"data.approval_id": APPROVAL_ID}}},
            {"entry.data.approval_id": APPROVAL_ID},
        ]

    async def test_does_not_advance_the_sync_clock(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.set_message_approval_status(
            CONVERSATION_ID, user_id=USER_ID, approval_id=APPROVAL_ID, status="approved"
        )

        _filter, update, _kwargs = _update_call(collection)
        assert set(update) == {"$set"}
        assert set(update["$set"]) == {"messages.$[msg].tool_data.$[entry].data.status"}

    async def test_reports_true_when_the_frame_was_there_to_settle(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        assert (
            await repo.set_message_approval_status(
                CONVERSATION_ID, user_id=USER_ID, approval_id=APPROVAL_ID, status="approved"
            )
            is True
        )

    async def test_reports_false_when_the_document_never_held_the_approval(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        _matched(collection, 0)

        assert (
            await repo.set_message_approval_status(
                CONVERSATION_ID, user_id=USER_ID, approval_id="no-such", status="approved"
            )
            is False
        )


async def _write_response(repo: ConversationRepository) -> None:
    await repo.set_message_response(
        CONVERSATION_ID, user_id=USER_ID, message_id=MESSAGE_ID, response="the answer"
    )


async def _write_tool_data(repo: ConversationRepository) -> None:
    await repo.set_message_tool_data(
        CONVERSATION_ID,
        user_id=USER_ID,
        message_id=MESSAGE_ID,
        entries=[{"tool_name": "search", "data": {}}],
    )


async def _write_approval_status(repo: ConversationRepository) -> None:
    await repo.set_message_approval_status(
        CONVERSATION_ID, user_id=USER_ID, approval_id=APPROVAL_ID, status="approved"
    )


class TestSettlementWritesRefreshTheCache:
    """Every settlement write names its cache scope (the owning user) and the
    document it touched.

    The repository ships with ``cache_policy = None``, so those arguments are
    inert today — the module docstring's stated reason for passing them anyway
    is that turning a policy on later must need no call-site change. That only
    holds if they are correct now, which is what these tests pin: the policy is
    switched on for the duration and the Redis calls the base makes are observed.
    """

    @pytest.fixture
    def cache(self) -> Iterator[tuple[AsyncMock, AsyncMock]]:
        with (
            patch.object(ConversationRepository, "cache_policy", CACHE_POLICY),
            patch("app.db.repositories.base.delete_cache", AsyncMock()) as delete_cache,
            patch("app.db.repositories.base.bump_generation", AsyncMock()) as bump_generation,
        ):
            yield delete_cache, bump_generation

    @pytest.mark.parametrize(
        "write",
        [_write_response, _write_tool_data, _write_approval_status],
        ids=["set_message_response", "set_message_tool_data", "set_message_approval_status"],
    )
    async def test_evicts_the_conversation_and_bumps_the_user_generation(
        self,
        write: Callable[[ConversationRepository], Awaitable[None]],
        repo: ConversationRepository,
        collection: MagicMock,
        cache: tuple[AsyncMock, AsyncMock],
    ) -> None:
        delete_cache, bump_generation = cache

        await write(repo)

        delete_cache.assert_awaited_once_with(f"test-conversations:{USER_ID}:{CONVERSATION_ID}")
        bump_generation.assert_awaited_once_with(CACHE_POLICY, USER_ID)

    @pytest.mark.parametrize(
        "write",
        [_write_response, _write_tool_data, _write_approval_status],
        ids=["set_message_response", "set_message_tool_data", "set_message_approval_status"],
    )
    async def test_leaves_the_cache_alone_when_nothing_matched(
        self,
        write: Callable[[ConversationRepository], Awaitable[None]],
        repo: ConversationRepository,
        collection: MagicMock,
        cache: tuple[AsyncMock, AsyncMock],
    ) -> None:
        _matched(collection, 0)
        delete_cache, bump_generation = cache

        await write(repo)

        delete_cache.assert_not_awaited()
        bump_generation.assert_not_awaited()
