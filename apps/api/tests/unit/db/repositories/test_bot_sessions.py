"""Hermetic unit tests for BotSessionsRepository.

The real-Mongo proof lives in tests/contracts/test_bot_sessions_repository.py;
this tier pins the exact filter and update document the repository hands the
driver — what the contracts tier cannot see, and what keeps the DM-merge
migration's writes honest without a cluster. The driver is mocked at
app.db.repositories.base.get_async_collection, the single seam every read and
write in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.bot_sessions import (
    LEGACY_DM_SESSION_KEY_SUFFIX,
    BotSessionsRepository,
)
from app.models.bot_models import MessageReaction, OwedReaction, PartialReply

TELEGRAM_USER = "6222050155"
LEGACY_KEY = f"telegram:{TELEGRAM_USER}:dm"
CANONICAL_KEY = f"telegram:{TELEGRAM_USER}:{TELEGRAM_USER}"
TIMESTAMP = "2026-08-16T09:23:00+00:00"


def _raw(session_key: str, conversation_id: str) -> dict[str, Any]:
    return {
        "_id": "oid",
        "session_key": session_key,
        "conversation_id": conversation_id,
        "platform": "telegram",
        "platform_user_id": TELEGRAM_USER,
        "channel_id": None,
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
    }


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
    mock.find_one_and_update = AsyncMock(return_value=_raw(LEGACY_KEY, "conv-1"))
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[_raw(LEGACY_KEY, "conv-1")])
    mock.find = MagicMock(return_value=cursor)
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.fixture
def repo() -> BotSessionsRepository:
    return BotSessionsRepository()


class TestClaimSessionTimestamps:
    async def test_the_timestamp_stays_the_iso_string_it_was_given(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        """The collection's TTL reads created_at/updated_at as ISO strings; the base's auto-stamped datetime would silently break it."""
        await repo.claim_session(
            session_key=LEGACY_KEY,
            platform="telegram",
            platform_user_id=TELEGRAM_USER,
            channel_id=None,
            candidate_conversation_id="conv-1",
            timestamp=TIMESTAMP,
        )

        _filter, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["updated_at"] == TIMESTAMP
        assert update["$setOnInsert"]["created_at"] == TIMESTAMP


class TestListLegacyDmSessions:
    async def test_it_matches_only_keys_ending_in_the_retired_suffix(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        """Anchored at the end: a Slack channel id merely containing dm is a live session, and rewriting it would fork the chat."""
        await repo.list_legacy_dm_sessions()

        assert collection.find.call_args.args[0] == {
            "session_key": {"$regex": f"{LEGACY_DM_SESSION_KEY_SUFFIX}$"}
        }

    async def test_a_platform_filter_narrows_the_scan(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        await repo.list_legacy_dm_sessions(platform="telegram")

        assert collection.find.call_args.args[0]["platform"] == "telegram"

    async def test_it_returns_typed_documents_carrying_the_recency_stamps(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        """The migration picks a winner by recency, so the timestamps must survive the typed boundary rather than being dropped."""
        sessions = await repo.list_legacy_dm_sessions()

        assert [s.session_key for s in sessions] == [LEGACY_KEY]
        assert sessions[0].updated_at == TIMESTAMP
        assert sessions[0].created_at == TIMESTAMP


class TestRenameSessionKey:
    async def test_it_moves_the_row_and_stamps_the_channel(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        assert await repo.rename_session_key(
            session_key=LEGACY_KEY, new_session_key=CANONICAL_KEY, channel_id=TELEGRAM_USER
        )

        filter_, update = collection.update_one.await_args.args
        assert filter_ == {"session_key": LEGACY_KEY}
        assert update == {"$set": {"session_key": CANONICAL_KEY, "channel_id": TELEGRAM_USER}}

    async def test_it_reports_a_filter_that_matched_nothing(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.rename_session_key(
            session_key=LEGACY_KEY, new_session_key=CANONICAL_KEY, channel_id=TELEGRAM_USER
        )


class TestRepointConversation:
    async def test_it_sets_the_conversation_id_and_clears_the_delivery_cursor(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        assert await repo.repoint_conversation(
            session_key=CANONICAL_KEY, conversation_id="conv-winner"
        )

        filter_, update = collection.update_one.await_args.args
        assert filter_ == {"session_key": CANONICAL_KEY}
        assert update == {"$set": {"conversation_id": "conv-winner"}, "$unset": {"delivery": ""}}

    async def test_it_reports_a_filter_that_matched_nothing(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        """A repoint that hit no row must say so, or the migration reports a fork it never actually merged."""
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.repoint_conversation(
            session_key=CANONICAL_KEY, conversation_id="conv-winner"
        )


class TestDeleteBySessionKey:
    async def test_it_reports_how_many_rows_it_removed(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))

        assert await repo.delete_by_session_key(LEGACY_KEY) == 1
        assert collection.delete_many.await_args.args[0] == {"session_key": LEGACY_KEY}


class TestDeleteForPlatformUser:
    async def test_it_deletes_by_platform_and_account_and_reports_the_count(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=2))

        deleted = await repo.delete_for_platform_user(
            platform="telegram", platform_user_id=TELEGRAM_USER
        )

        assert deleted == 2
        assert collection.delete_many.await_args.args[0] == {
            "platform": "telegram",
            "platform_user_id": TELEGRAM_USER,
        }


class TestListSessions:
    async def test_without_a_platform_it_scans_every_session(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        found = await repo.list_sessions()

        assert collection.find.call_args.args[0] == {}
        assert [s.session_key for s in found] == [LEGACY_KEY]

    async def test_a_platform_narrows_the_scan(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        await repo.list_sessions(platform="slack")

        assert collection.find.call_args.args[0] == {"platform": "slack"}


OWED_AT = datetime(2026, 11, 26, tzinfo=UTC)
THUMBS = MessageReaction(message_id="u1", emoji="👍")


class TestOweReaction:
    async def test_it_starts_a_missing_cursor_before_the_message_then_owes_the_reaction(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        owed = OwedReaction(message_id="u1", emoji="👍", owed_at=OWED_AT)

        await repo.owe_reaction("conv-1", seq=4, reaction=owed)

        init_filter, init = collection.update_one.await_args.args
        assert init_filter == {"conversation_id": "conv-1", "delivery": {"$exists": False}}
        assert init == {"$set": {"delivery": {"delivered_seq": 3, "owed_seq": 0}}}
        push_filter, push = collection.find_one_and_update.await_args.args
        assert push_filter == {"conversation_id": "conv-1"}
        assert push == {
            "$push": {
                "delivery.owed_reactions": {"message_id": "u1", "emoji": "👍", "owed_at": OWED_AT}
            }
        }


class TestRecordDelivered:
    async def test_it_settles_each_placed_reaction_whatever_the_cursor_then_moves_the_cursor(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        partial = PartialReply(reply_id="r1", bubbles=1)

        assert await repo.record_delivered(
            "conv-1",
            platform="telegram",
            delivered_seq=7,
            partial_reply=partial,
            placed_reactions=[THUMBS, MessageReaction(message_id="u2", emoji="❤")],
        )

        (settle_filter, settle), (move_filter, move) = [
            c.args for c in collection.update_one.await_args_list
        ]
        assert settle_filter == {"conversation_id": "conv-1", "platform": "telegram"}
        assert settle == {
            "$pull": {
                "delivery.owed_reactions": {
                    "$or": [
                        {"message_id": "u1", "emoji": "👍"},
                        {"message_id": "u2", "emoji": "❤"},
                    ]
                }
            }
        }
        assert move_filter == {
            "conversation_id": "conv-1",
            "platform": "telegram",
            "$or": [
                {"delivery": {"$exists": False}},
                {"delivery.delivered_seq": {"$lte": 7}},
            ],
        }
        assert move == {
            "$set": {
                "delivery.delivered_seq": 7,
                "delivery.partial_reply": {
                    "reply_id": "r1",
                    "bubbles": 1,
                    "open_message_ids": [],
                },
            }
        }

    async def test_a_report_placing_nothing_only_moves_the_cursor(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        await repo.record_delivered(
            "conv-1", platform="telegram", delivered_seq=7, partial_reply=None
        )

        [(_filter, update)] = [c.args for c in collection.update_one.await_args_list]
        assert update == {"$set": {"delivery.delivered_seq": 7, "delivery.partial_reply": None}}

    async def test_a_report_behind_the_cursor_says_it_moved_nothing(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.update_one.return_value = MagicMock(matched_count=0, upserted_id=None)

        assert not await repo.record_delivered(
            "conv-1", platform="telegram", delivered_seq=3, partial_reply=None
        )


class TestDropOwedReactionsBefore:
    async def test_it_pulls_only_the_platforms_reactions_owed_before_the_cutoff(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.update_many = AsyncMock(return_value=MagicMock(modified_count=3))

        assert await repo.drop_owed_reactions_before("telegram", OWED_AT) == 3
        filter_, update = collection.update_many.await_args.args
        assert filter_ == {
            "platform": "telegram",
            "delivery.owed_reactions.owed_at": {"$lt": OWED_AT},
        }
        assert update == {"$pull": {"delivery.owed_reactions": {"owed_at": {"$lt": OWED_AT}}}}


class TestForgetDelivery:
    async def test_it_drops_the_cursor_of_the_deleted_conversation(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        await repo.forget_delivery("conv-1")

        filter_, update = collection.update_one.await_args.args
        assert (filter_, update) == ({"conversation_id": "conv-1"}, {"$unset": {"delivery": ""}})


class TestListOwed:
    async def test_it_lists_sessions_owing_an_entry_or_a_reaction(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        cursor = collection.find.return_value
        cursor.limit = MagicMock(return_value=cursor)

        await repo.list_owed("telegram", 50)

        cursor.limit.assert_called_once_with(50)
        assert collection.find.call_args.args[0] == {
            "platform": "telegram",
            "$or": [
                {"$expr": {"$gt": ["$delivery.owed_seq", "$delivery.delivered_seq"]}},
                {"delivery.owed_reactions.0": {"$exists": True}},
            ],
        }
