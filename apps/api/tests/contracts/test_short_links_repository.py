"""Contract tests for ShortLinksRepository.

User-scoped, business-key slug identity, no cache policy: a bespoke suite,
not the inherited UserScopedRepositoryContract, matching
test_conversations_repository.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import uuid

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.mongodb.indexes import create_short_link_indexes
from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, ShortLinksRepository
from app.models.short_link_models import ShortLink, ShortLinkTargetType, ShortLinkUpdate


def _slug() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
def repo(raw_collection) -> ShortLinksRepository:
    return ShortLinksRepository()


@pytest.fixture
def make_doc() -> Callable[..., ShortLink]:
    def _make(**overrides: object) -> ShortLink:
        data: dict[str, object] = {
            "slug": _slug(),
            "user_id": "user-1",
            "target_type": ShortLinkTargetType.TODO_DELIVERABLE,
            "target_id": "todo-1",
        }
        data.update(overrides)
        return ShortLink.model_validate(data)

    return _make


@pytest.fixture
async def indexed_repo(
    repo: ShortLinksRepository, raw_collection, monkeypatch: pytest.MonkeyPatch
) -> ShortLinksRepository:
    """Return the repository over a collection carrying the real short_links indexes."""
    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", lambda _name: raw_collection)
    await create_short_link_indexes()
    return repo


class TestShortLinksLiveTargetUniqueness:
    """One live link per target is enforced by Mongo, not by the mint's read-then-write.

    Two overlapping mints must collide on the index, or the loser's link
    outlives the winner's revocation.
    """

    async def test_a_second_live_link_for_one_target_is_rejected(self, indexed_repo, make_doc):
        await indexed_repo.create(make_doc(user_id="u", target_id="t1"))
        with pytest.raises(DuplicateKeyError, match=LIVE_TARGET_UNIQUE_INDEX):
            await indexed_repo.create(make_doc(user_id="u", target_id="t1"))

    async def test_two_owners_sharing_a_target_id_each_hold_their_own_live_link(
        self, indexed_repo, make_doc
    ):
        """A target id is only unique per owner: one user's link never blocks another's mint."""
        await indexed_repo.create(make_doc(user_id="owner-a", target_id="conv-1/report.html"))
        theirs = await indexed_repo.create(
            make_doc(user_id="owner-b", target_id="conv-1/report.html")
        )
        assert await indexed_repo.get_by_slug(theirs.slug) is not None

    async def test_a_revoked_link_does_not_block_a_fresh_mint(self, indexed_repo, make_doc):
        await indexed_repo.create(make_doc(user_id="u", target_id="t1", revoked=True))
        fresh = await indexed_repo.create(make_doc(user_id="u", target_id="t1"))
        assert await indexed_repo.get_by_slug(fresh.slug) is not None

    async def test_the_index_refuses_to_build_over_duplicate_live_links(
        self, repo, raw_collection, make_doc, monkeypatch: pytest.MonkeyPatch
    ):
        await repo.create(make_doc(user_id="u", target_id="t1"))
        await repo.create(make_doc(user_id="u", target_id="t1"))
        monkeypatch.setattr(
            "app.db.mongodb.indexes.get_async_collection", lambda _name: raw_collection
        )
        with pytest.raises(DuplicateKeyError):
            await create_short_link_indexes()


class TestShortLinksCore:
    async def test_create_and_get_roundtrips(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        fetched = await repo.get(created.slug, user_id="owner")
        assert fetched == created

    async def test_get_is_scoped_to_user(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        assert await repo.get(created.slug, user_id="attacker") is None
        assert await repo.get(created.slug, user_id="owner") is not None

    async def test_update_partial_and_delete(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner", target_id="t1"))
        updated = await repo.update(
            created.slug, user_id="owner", update=ShortLinkUpdate(revoked=True)
        )
        assert updated is not None
        assert updated.revoked is True
        assert updated.target_id == "t1"  # untouched
        assert await repo.delete(created.slug, user_id="owner") is True
        assert await repo.get(created.slug, user_id="owner") is None


class TestShortLinksResolution:
    async def test_get_by_slug_is_global_unscoped(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.user_id == "owner"

    async def test_get_by_slug_missing_returns_none(self, repo):
        assert await repo.get_by_slug("does-not-exist") is None


class TestShortLinksMintingIdempotency:
    async def test_get_live_for_target_returns_the_live_link(self, indexed_repo, make_doc):
        created = await indexed_repo.create(make_doc(target_id="t1"))
        found = await indexed_repo.get_live_for_target(
            "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
        )
        assert found is not None and found.slug == created.slug

    async def test_get_live_for_target_none_when_no_link(self, indexed_repo):
        assert (
            await indexed_repo.get_live_for_target(
                "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "missing"
            )
            is None
        )

    async def test_get_live_for_target_skips_revoked_link(self, indexed_repo, make_doc):
        await indexed_repo.create(make_doc(target_id="t1", revoked=True))
        result = await indexed_repo.get_live_for_target(
            "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
        )
        assert result is None  # revoked link is dead — caller mints a fresh one

    async def test_get_live_for_target_never_returns_another_owners_link(
        self, indexed_repo, make_doc
    ):
        await indexed_repo.create(make_doc(user_id="someone-else", target_id="t1"))
        assert (
            await indexed_repo.get_live_for_target(
                "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
            )
            is None
        )

    async def test_target_types_do_not_share_a_live_link(self, indexed_repo, make_doc):
        await indexed_repo.create(make_doc(target_id="same-id"))
        other = await indexed_repo.create(
            make_doc(target_type=ShortLinkTargetType.BRIEFING, target_id="same-id")
        )
        found = await indexed_repo.get_live_for_target(
            "user-1", ShortLinkTargetType.BRIEFING, "same-id"
        )
        assert found is not None and found.slug == other.slug


class TestShortLinksLatestForTarget:
    """The newest link tells whether the owner shares a target, stopped, or never started."""

    async def test_none_when_never_shared(self, indexed_repo):
        assert (
            await indexed_repo.get_latest_for_target(
                "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
            )
            is None
        )

    async def test_a_revoked_link_stays_the_newest_after_stopping(self, indexed_repo, make_doc):
        live = await indexed_repo.create(make_doc(target_id="t1"))
        await indexed_repo.revoke("user-1", live.slug)

        latest = await indexed_repo.get_latest_for_target(
            "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
        )

        assert latest is not None and latest.slug == live.slug and latest.revoked

    async def test_re_sharing_makes_the_fresh_live_link_the_newest(self, indexed_repo, make_doc):
        old = make_doc(target_id="t1", revoked=True)
        old.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await indexed_repo.create(old)
        fresh = await indexed_repo.create(make_doc(target_id="t1"))

        latest = await indexed_repo.get_latest_for_target(
            "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
        )

        assert latest is not None and latest.slug == fresh.slug and not latest.revoked

    async def test_another_owners_link_is_never_the_latest(self, indexed_repo, make_doc):
        await indexed_repo.create(make_doc(user_id="someone-else", target_id="t1", revoked=True))
        assert (
            await indexed_repo.get_latest_for_target(
                "user-1", ShortLinkTargetType.TODO_DELIVERABLE, "t1"
            )
            is None
        )


class TestShortLinksRevoke:
    async def test_revoke_by_owner_succeeds(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        assert await repo.revoke("owner", created.slug) is True
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.revoked is True

    async def test_revoke_by_non_owner_fails(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        assert await repo.revoke("attacker", created.slug) is False
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.revoked is False
