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
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    RenderMode,
    RevokeReason,
    ShortLink,
    ShortLinkTargetType,
    ShortLinkUpdate,
)


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
        await indexed_repo.revoke("user-1", live.slug, RevokeReason.OWNER)

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
    async def test_revoke_by_owner_records_when_and_why(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        revoked = await repo.revoke("owner", created.slug, RevokeReason.ROTATED)
        assert revoked is not None
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.revoked is True
        assert found.revoked_reason is RevokeReason.ROTATED
        assert found.revoked_at is not None

    async def test_revoke_by_non_owner_fails(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        assert await repo.revoke("attacker", created.slug, RevokeReason.OWNER) is None
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.revoked is False

    async def test_a_dead_link_is_not_revoked_again(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        await repo.revoke("owner", created.slug, RevokeReason.ROTATED)
        assert await repo.revoke("owner", created.slug, RevokeReason.OWNER) is None
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.revoked_reason is RevokeReason.ROTATED


class TestShortLinksUpdateLive:
    async def test_the_owner_changes_a_live_link(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))

        updated = await repo.update_live(
            "owner", created.slug, ShortLinkUpdate(access=LinkAccess.PUBLIC)
        )

        assert updated is not None and updated.access is LinkAccess.PUBLIC
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.access is LinkAccess.PUBLIC

    async def test_another_users_link_is_left_alone(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))

        assert (
            await repo.update_live("attacker", created.slug, ShortLinkUpdate(suspended=True))
            is None
        )
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.suspended is False

    async def test_a_revoked_link_keeps_its_record(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="owner"))
        await repo.revoke("owner", created.slug, RevokeReason.ROTATED)

        assert (
            await repo.update_live("owner", created.slug, ShortLinkUpdate(access=LinkAccess.PUBLIC))
            is None
        )
        found = await repo.get_by_slug(created.slug)
        assert found is not None and found.access is LinkAccess.UNLISTED


class TestShortLinksSnapshots:
    def _snapshot(self, content_id: str, size: int = 10) -> LinkSnapshot:
        return LinkSnapshot(
            filename="r.html",
            mime="text/html",
            size_bytes=size,
            render=RenderMode.FRAME_ACTIVE,
            content_id=content_id,
        )

    async def test_the_content_origin_finds_only_the_live_link_pinning_a_snapshot(
        self, indexed_repo, make_doc
    ):
        cid = "c" * 26
        rotated = await indexed_repo.create(make_doc(snapshot=self._snapshot(cid), target_id="a"))
        await indexed_repo.revoke("user-1", rotated.slug, RevokeReason.ROTATED)
        live = await indexed_repo.create(make_doc(snapshot=self._snapshot(cid), target_id="a"))

        found = await indexed_repo.get_live_by_content_id(cid)

        assert found is not None and found.slug == live.slug
        assert await indexed_repo.live_pins_content(cid)
        await indexed_repo.revoke("user-1", live.slug, RevokeReason.OWNER)
        assert await indexed_repo.get_live_by_content_id(cid) is None
        assert not await indexed_repo.live_pins_content(cid)

    async def test_stored_bytes_sum_the_owners_live_published_snapshots(
        self, indexed_repo, make_doc
    ):
        await indexed_repo.create(make_doc(snapshot=self._snapshot("a" * 26, 100), target_id="1"))
        await indexed_repo.create(make_doc(snapshot=self._snapshot("b" * 26, 50), target_id="2"))
        dead = await indexed_repo.create(
            make_doc(snapshot=self._snapshot("d" * 26, 7), target_id="3")
        )
        await indexed_repo.revoke("user-1", dead.slug, RevokeReason.OWNER)
        unpublished = self._snapshot("e" * 26, 999).model_copy(update={"content_id": None})
        await indexed_repo.create(make_doc(snapshot=unpublished, target_id="4"))
        await indexed_repo.create(
            make_doc(user_id="other", snapshot=self._snapshot("f" * 26, 1000), target_id="5")
        )

        assert await indexed_repo.stored_snapshot_bytes("user-1") == 150
        assert await indexed_repo.stored_snapshot_bytes("nobody") == 0

    async def test_takedowns_count_per_owner(self, indexed_repo, make_doc):
        first = await indexed_repo.create(make_doc(target_id="1"))
        await indexed_repo.revoke("user-1", first.slug, RevokeReason.TAKEDOWN)
        second = await indexed_repo.create(make_doc(target_id="2"))
        await indexed_repo.revoke("user-1", second.slug, RevokeReason.OWNER)

        assert await indexed_repo.count_takedowns("user-1") == 1

    async def test_the_backfill_finds_live_file_links_without_a_snapshot(
        self, indexed_repo, make_doc
    ):
        session = ShortLinkTargetType.SESSION_ARTIFACT
        legacy = await indexed_repo.create(make_doc(target_type=session, target_id="c/a.html"))
        await indexed_repo.create(
            make_doc(target_type=session, target_id="c/b.html", snapshot=self._snapshot("a" * 26))
        )
        gone = await indexed_repo.create(make_doc(target_type=session, target_id="c/c.html"))
        await indexed_repo.revoke("user-1", gone.slug, RevokeReason.OWNER)

        pending = await indexed_repo.live_without_snapshot(session)

        assert [link.slug for link in pending] == [legacy.slug]
