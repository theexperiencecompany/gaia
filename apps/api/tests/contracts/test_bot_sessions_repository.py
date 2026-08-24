"""Contract tests for BotSessionsRepository (global, atomic session claim).

The unique ``session_key`` index is what makes the claim atomic, so the fixture
mirrors it on the throwaway collection before asserting get-or-create semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest

from app.db.repositories.bot_sessions import BotSessionsRepository


@pytest.fixture
async def repo(raw_collection) -> BotSessionsRepository:
    await raw_collection.create_index("session_key", unique=True)
    return BotSessionsRepository()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TestBotSessionsRepository:
    async def test_first_claim_creates_with_candidate_id(self, repo):
        key = f"discord:{uuid.uuid4().hex}:dm"
        candidate = str(uuid.uuid4())

        session = await repo.claim_session(
            session_key=key,
            platform="discord",
            platform_user_id="u1",
            channel_id=None,
            candidate_conversation_id=candidate,
            timestamp=_now(),
        )
        # The fresh session commits the candidate id.
        assert session.conversation_id == candidate
        assert session.session_key == key
        assert session.channel_id is None

    async def test_second_claim_reuses_conversation_id(self, repo):
        key = f"slack:{uuid.uuid4().hex}:c1"
        first = await repo.claim_session(
            session_key=key,
            platform="slack",
            platform_user_id="u1",
            channel_id="c1",
            candidate_conversation_id=str(uuid.uuid4()),
            timestamp=_now(),
        )

        # A racing second claim gets the SAME conversation_id — its candidate is
        # discarded (this is the anti-fork guarantee).
        second = await repo.claim_session(
            session_key=key,
            platform="slack",
            platform_user_id="u1",
            channel_id="c1",
            candidate_conversation_id=str(uuid.uuid4()),
            timestamp=_now(),
        )
        assert second.conversation_id == first.conversation_id

    async def test_timestamps_stored_as_iso_strings(self, repo, raw_collection):
        key = f"telegram:{uuid.uuid4().hex}:dm"
        ts = _now()
        await repo.claim_session(
            session_key=key,
            platform="telegram",
            platform_user_id="u1",
            channel_id=None,
            candidate_conversation_id=str(uuid.uuid4()),
            timestamp=ts,
        )
        raw = await raw_collection.find_one({"session_key": key})
        assert raw is not None
        # Written raw, not normalised to a BSON date (the base did not stamp it).
        assert raw["created_at"] == ts and isinstance(raw["created_at"], str)
        assert raw["updated_at"] == ts and isinstance(raw["updated_at"], str)

    async def test_delete_by_session_key(self, repo, raw_collection):
        key = f"discord:{uuid.uuid4().hex}:dm"
        await repo.claim_session(
            session_key=key,
            platform="discord",
            platform_user_id="u1",
            channel_id=None,
            candidate_conversation_id=str(uuid.uuid4()),
            timestamp=_now(),
        )
        assert await repo.delete_by_session_key(key) == 1
        assert await raw_collection.find_one({"session_key": key}) is None

    async def test_delete_by_session_key_reports_a_miss(self, repo):
        assert await repo.delete_by_session_key(f"discord:{uuid.uuid4().hex}:dm") == 0

    async def test_get_by_session_key_reads_without_minting(self, repo, raw_collection):
        """Unlike ``claim_session``, a miss must stay a miss — the migration asks
        whether the canonical key is taken, and an upsert there would create the
        very row it is checking for."""
        key = f"telegram:{uuid.uuid4().hex}:dm"
        assert await repo.get_by_session_key(key) is None
        assert await raw_collection.find_one({"session_key": key}) is None

        conversation_id = str(uuid.uuid4())
        await repo.claim_session(
            session_key=key,
            platform="telegram",
            platform_user_id="u1",
            channel_id=None,
            candidate_conversation_id=conversation_id,
            timestamp=_now(),
        )
        found = await repo.get_by_session_key(key)
        assert found is not None and found.conversation_id == conversation_id


class TestLegacyDmSessionRepair:
    """The finders and mutators ``app.scripts.merge_legacy_dm_bot_sessions`` runs
    against real rows."""

    async def _claim(self, repo, key: str, platform: str = "telegram") -> str:
        conversation_id = str(uuid.uuid4())
        await repo.claim_session(
            session_key=key,
            platform=platform,
            platform_user_id=key.split(":")[1],
            channel_id=None,
            candidate_conversation_id=conversation_id,
            timestamp=_now(),
        )
        return conversation_id

    async def test_it_finds_legacy_keys_and_ignores_a_channel_containing_dm(self, repo):
        user = uuid.uuid4().hex
        legacy = f"telegram:{user}:dm"
        await self._claim(repo, legacy)
        # A live Slack channel whose id merely CONTAINS "dm" must not be swept up.
        await self._claim(repo, f"slack:{user}:Cdm123", platform="slack")

        found = await repo.list_legacy_dm_sessions()

        assert [s.session_key for s in found if s.platform_user_id == user] == [legacy]

    async def test_the_recency_stamps_survive_the_typed_boundary(self, repo):
        """The migration picks a winner by recency; the ISO strings have to come
        back as strings, not be dropped as unmodelled extras."""
        key = f"telegram:{uuid.uuid4().hex}:dm"
        await self._claim(repo, key)

        found = next(s for s in await repo.list_legacy_dm_sessions() if s.session_key == key)

        assert isinstance(found.updated_at, str) and found.updated_at
        assert isinstance(found.created_at, str) and found.created_at

    async def test_a_platform_filter_narrows_the_result(self, repo):
        user = uuid.uuid4().hex
        await self._claim(repo, f"telegram:{user}:dm")
        await self._claim(repo, f"discord:{user}:dm", platform="discord")

        found = await repo.list_legacy_dm_sessions(platform="discord")

        assert {s.platform for s in found} == {"discord"}

    async def test_rename_moves_the_row_and_keeps_its_conversation(self, repo, raw_collection):
        user = uuid.uuid4().hex
        legacy, canonical = f"telegram:{user}:dm", f"telegram:{user}:{user}"
        conversation_id = await self._claim(repo, legacy)

        assert await repo.rename_session_key(
            session_key=legacy, new_session_key=canonical, channel_id=user
        )

        assert await raw_collection.find_one({"session_key": legacy}) is None
        moved = await raw_collection.find_one({"session_key": canonical})
        assert moved is not None
        assert moved["conversation_id"] == conversation_id
        assert moved["channel_id"] == user
        # The TTL anchor must survive the rewrite as a string, not a BSON date.
        assert isinstance(moved["updated_at"], str)

    async def test_rename_reports_a_filter_that_matched_nothing(self, repo):
        user = uuid.uuid4().hex
        assert not await repo.rename_session_key(
            session_key=f"telegram:{user}:dm",
            new_session_key=f"telegram:{user}:{user}",
            channel_id=user,
        )

    async def test_repoint_swaps_the_conversation_and_leaves_the_key(self, repo, raw_collection):
        user = uuid.uuid4().hex
        canonical = f"telegram:{user}:{user}"
        await self._claim(repo, canonical)
        winner = str(uuid.uuid4())

        assert await repo.repoint_conversation(session_key=canonical, conversation_id=winner)

        row = await raw_collection.find_one({"session_key": canonical})
        assert row is not None
        assert row["conversation_id"] == winner
        assert row["session_key"] == canonical

    async def test_repoint_reports_a_filter_that_matched_nothing(self, repo):
        assert not await repo.repoint_conversation(
            session_key=f"telegram:{uuid.uuid4().hex}:{uuid.uuid4().hex}",
            conversation_id=str(uuid.uuid4()),
        )
