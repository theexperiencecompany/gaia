"""Contract tests for ShortLinksRepository (user-scoped, business-key ``slug``
identity, no cache policy — a bespoke suite, not the inherited
``UserScopedRepositoryContract``, matching ``test_conversations_repository.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.db.repositories.short_links import ShortLinksRepository
from app.models.short_link_models import ShortLink, ShortLinkUpdate


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
            "target_type": "todo_canvas",
            "target_id": "todo-1",
        }
        data.update(overrides)
        return ShortLink.model_validate(data)

    return _make


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
    async def test_refresh_for_target_pushes_expiry_when_live_link_exists(self, repo, make_doc):
        original_expiry = datetime.now(UTC) + timedelta(days=1)
        created = await repo.create(
            make_doc(
                user_id="u", target_type="todo_canvas", target_id="t1", expires_at=original_expiry
            )
        )
        new_expiry = datetime.now(UTC) + timedelta(days=30)
        refreshed = await repo.refresh_for_target("u", "todo_canvas", "t1", expires_at=new_expiry)
        assert refreshed is not None
        assert refreshed.slug == created.slug  # same link reused, not a new mint
        assert refreshed.expires_at is not None
        assert abs((refreshed.expires_at - new_expiry).total_seconds()) < 1

    async def test_refresh_for_target_none_when_no_existing_link(self, repo):
        assert (
            await repo.refresh_for_target(
                "u", "todo_canvas", "missing", expires_at=datetime.now(UTC)
            )
            is None
        )

    async def test_refresh_for_target_skips_revoked_link(self, repo, make_doc):
        await repo.create(
            make_doc(user_id="u", target_type="todo_canvas", target_id="t1", revoked=True)
        )
        result = await repo.refresh_for_target(
            "u", "todo_canvas", "t1", expires_at=datetime.now(UTC) + timedelta(days=30)
        )
        assert result is None  # revoked link is dead — caller mints a fresh one


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
