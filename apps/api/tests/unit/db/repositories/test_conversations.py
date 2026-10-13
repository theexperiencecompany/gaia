"""Hermetic unit tests for ConversationRepository's in-place writes and activation-signal count.

The real-Mongo proof lives in tests/contracts/test_conversations_repository.py;
this tier pins the exact filter, update document and array_filters the
repository hands the driver. The driver is mocked at
app.db.repositories.base.get_async_collection, the single seam every write
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


def _count_filter(collection: MagicMock) -> dict[str, Any]:
    """Return the single count_documents call's filter."""
    collection.count_documents.assert_awaited_once()
    return collection.count_documents.await_args.args[0]


class TestSetMessageResponse:
    """set_message_response — background delivery settling a message's text."""

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
        """Documented invariant: this write leaves updatedAt alone."""
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
    """set_message_tool_data — delivery re-persisting a message's whole frame list."""

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
    """set_message_approval_status settles a persisted approval frame wherever it sits in the messages array."""

    async def test_narrows_the_match_by_approval_id_not_just_conversation(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        """The array filters pick the element but never narrow matched_count, so the approval must be in the query filter too."""
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
    """Every settlement write names its cache scope (the owning user) and the document it touched.

    The repository ships with cache_policy = None, so these arguments are
    inert today; these tests switch the policy on for the duration and
    observe the Redis calls the base makes, pinning them correct for when a
    policy is turned on later.
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


class TestHasSentMessage:
    """has_sent_message — the activation checklist's "say hi" signal.

    The service tier mocks this method away entirely, so the predicate it hands
    Mongo is only visible here. Every clause is load-bearing: drop the
    is_system_generated guard and a workflow execution's own prompt vouches
    for a user who never typed anything, and drop the messages.type clause
    and an empty conversation counts as a sent message.
    """

    async def test_counts_only_human_threads_that_carry_a_user_message(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        await repo.has_sent_message(USER_ID)

        assert _count_filter(collection) == {
            "user_id": USER_ID,
            "is_system_generated": {"$ne": True},
            "messages.type": "user",
        }
        assert collection.get_collection.call_args.args == ("conversations",)

    async def test_reports_false_when_nothing_matches(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        assert await repo.has_sent_message(USER_ID) is False

    async def test_a_single_match_is_enough(
        self, repo: ConversationRepository, collection: MagicMock
    ) -> None:
        collection.count_documents.return_value = 1

        assert await repo.has_sent_message(USER_ID) is True


class TestBackgroundVisibility:
    def _matches(self, repo: ConversationRepository, doc: dict[str, object]) -> bool:
        """Evaluate the active filter against a stub doc (equality subset)."""

        flt = repo._active_filter(USER_ID)
        if doc.get("user_id") != flt.get("user_id"):
            return False
        for clause in flt["$and"]:
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
