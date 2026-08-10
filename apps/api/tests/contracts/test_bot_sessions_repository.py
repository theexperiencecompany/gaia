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
        await repo.delete_by_session_key(key)
        assert await raw_collection.find_one({"session_key": key}) is None
