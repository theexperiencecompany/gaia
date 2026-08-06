"""Contract tests for AwardsRepository (user-scoped, ObjectId identity, no
cache policy — a bespoke suite, not the inherited ``UserScopedRepositoryContract``,
matching ``test_reminders_repository.py`` / ``test_user_integrations_repository.py``).
"""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.awards import AwardsRepository
from app.models.briefing_models import AwardDocument


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def repo(raw_collection) -> AwardsRepository:
    return AwardsRepository()


class TestAwardsCore:
    async def test_create_get_and_delete(self, repo):
        user_id = _uid("owner")
        created = await repo.create(AwardDocument(user_id=user_id, key="first_approve"))
        assert created.key == "first_approve"
        fetched = await repo.get(created.id, user_id=user_id)
        assert fetched == created
        assert await repo.delete(created.id, user_id=user_id) is True
        assert await repo.get(created.id, user_id=user_id) is None

    async def test_get_is_scoped_to_user(self, repo):
        owner = _uid("owner")
        created = await repo.create(AwardDocument(user_id=owner, key="streak_7"))
        assert await repo.get(created.id, user_id="attacker") is None
        assert await repo.get(created.id, user_id=owner) is not None


class TestAwardsBadges:
    async def test_award_badge_once_then_blocked_by_the_real_unique_index(
        self, repo, raw_collection
    ):
        # The ad hoc test collection carries no indexes by default; create the
        # production (user_id, key) unique index so this exercises the real
        # DuplicateKeyError path `award_badge` depends on, not a false pass.
        await raw_collection.create_index([("user_id", 1), ("key", 1)], unique=True)
        user_id = _uid("owner")
        assert await repo.award_badge(user_id, "first_approve") is True
        assert await repo.award_badge(user_id, "first_approve") is False  # already held

    async def test_award_badge_is_scoped_per_user(self, repo, raw_collection):
        await raw_collection.create_index([("user_id", 1), ("key", 1)], unique=True)
        assert await repo.award_badge("u1", "streak_7") is True
        assert await repo.award_badge("u2", "streak_7") is True  # different user, not blocked

    async def test_get_awarded_keys(self, repo):
        user_id = _uid("owner")
        await repo.award_badge(user_id, "first_approve")
        await repo.award_badge(user_id, "streak_7")
        await repo.award_badge(_uid("other"), "streak_30")
        assert await repo.get_awarded_keys(user_id) == {"first_approve", "streak_7"}

    async def test_get_awarded_keys_empty_for_unknown_user(self, repo):
        assert await repo.get_awarded_keys("nobody") == set()
