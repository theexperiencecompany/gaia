"""Hermetic unit tests for ``BotSessionsRepository``.

The real-Mongo proof lives in ``tests/contracts/test_bot_sessions_repository.py``;
this tier pins the exact filter and update document the repository hands the
driver — what the contracts tier cannot see, and what keeps the DM-merge
migration's writes honest without a cluster. The driver is mocked at
``app.db.repositories.base.get_async_collection``, the single seam every read and
write in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.bot_sessions import (
    LEGACY_DM_SESSION_KEY_SUFFIX,
    BotSessionsRepository,
)

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
        """The collection's TTL reads ``created_at``/``updated_at`` as ISO strings.
        The base auto-stamps a ``datetime`` into ``$set`` for any document that
        MODELS ``updated_at`` — which would silently replace the string and break
        the TTL. This repository opts out; nothing else enforces that."""
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
        """Anchored at the end: a Slack channel id merely CONTAINING ``dm`` is a
        live session, and rewriting it would fork the very chat this repairs."""
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
        """The migration picks a winner by recency, so the timestamps have to
        survive the typed boundary rather than being dropped as extras."""
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
    async def test_it_sets_only_the_conversation_id(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        assert await repo.repoint_conversation(
            session_key=CANONICAL_KEY, conversation_id="conv-winner"
        )

        filter_, update = collection.update_one.await_args.args
        assert filter_ == {"session_key": CANONICAL_KEY}
        assert update == {"$set": {"conversation_id": "conv-winner"}}

    async def test_it_reports_a_filter_that_matched_nothing(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        """A repoint that hit no row must say so: the migration counts it as
        applied otherwise, and reports a fork it never actually merged."""
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


class TestSessionWritesBustTheGlobalCache:
    """These three rows are keyed by ``session_key``, not by user, so they live
    in the repository's GLOBAL cache scope. Invalidating any other scope leaves
    the pre-migration session cached: the row moves, the next lookup still reads
    the old conversation, and the fork the migration just merged comes back.
    """

    async def test_rename_invalidates_the_global_scope(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        with patch.object(repo, "_invalidate", new_callable=AsyncMock) as invalidate:
            await repo.rename_session_key(
                session_key=LEGACY_KEY, new_session_key=CANONICAL_KEY, channel_id=TELEGRAM_USER
            )

        invalidate.assert_awaited_once_with(REPO_GLOBAL_SCOPE)

    async def test_repoint_invalidates_the_global_scope(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        with patch.object(repo, "_invalidate", new_callable=AsyncMock) as invalidate:
            await repo.repoint_conversation(
                session_key=CANONICAL_KEY, conversation_id="conv-winner"
            )

        invalidate.assert_awaited_once_with(REPO_GLOBAL_SCOPE)

    async def test_delete_invalidates_the_global_scope(
        self, repo: BotSessionsRepository, collection: MagicMock
    ) -> None:
        collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))

        with patch.object(repo, "_invalidate", new_callable=AsyncMock) as invalidate:
            await repo.delete_by_session_key(LEGACY_KEY)

        invalidate.assert_awaited_once_with(REPO_GLOBAL_SCOPE)
