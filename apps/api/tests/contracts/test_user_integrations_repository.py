"""Contract tests for UserIntegrationsRepository (user-scoped, per-integration)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository
from app.models.integration_models import UserIntegrationDocument


@pytest.fixture
def repo(raw_collection) -> UserIntegrationsRepository:
    return UserIntegrationsRepository()


def _ui(user_id: str, integration_id: str, **overrides: object) -> UserIntegrationDocument:
    data: dict[str, object] = {
        "user_id": user_id,
        "integration_id": integration_id,
        "status": "created",
        "created_at": datetime.now(UTC),
    }
    data.update(overrides)
    return UserIntegrationDocument.model_validate(data)


class TestUserIntegrationsRepository:
    async def test_create_get_and_exists(self, repo):
        await repo.create(_ui("u", "slack", status="connected"))
        got = await repo.get_for_user("u", "slack")
        assert got is not None and got.status == "connected"
        assert await repo.exists("u", "slack") is True
        assert await repo.exists("u", "github") is False

    async def test_scoped_to_user(self, repo):
        await repo.create(_ui("owner", "slack"))
        assert await repo.get_for_user("intruder", "slack") is None
        assert await repo.exists("intruder", "slack") is False

    async def test_list_newest_first(self, repo):
        await repo.create(_ui("u", "old", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await repo.create(_ui("u", "new", created_at=datetime(2026, 2, 1, tzinfo=UTC)))
        await repo.create(_ui("other", "theirs"))

        listed = await repo.list_for_user_newest_first("u")
        assert [d.integration_id for d in listed] == ["new", "old"]  # created_at desc

    async def test_delete_for_user_is_scoped(self, repo):
        await repo.create(_ui("u", "slack"))
        assert await repo.delete_for_user("other", "slack") is False
        assert await repo.delete_for_user("u", "slack") is True
        assert await repo.exists("u", "slack") is False

    async def test_connected_at_roundtrips(self, repo):
        when = datetime.now(UTC) - timedelta(hours=1)
        await repo.create(_ui("u", "gmail", status="connected", connected_at=when))
        got = await repo.get_for_user("u", "gmail")
        assert got is not None and got.connected_at is not None

    async def test_is_expired_separates_a_dead_connection_from_one_never_made(self, repo):
        # The whole point of the pair: "not connected" is not one state. Only the
        # stored record tells a grant that died from one that was never granted.
        await repo.create(_ui("u", "gmail", status="expired"))
        await repo.create(_ui("u", "slack", status="created"))
        await repo.create(_ui("u", "notion", status="connected"))

        assert await repo.is_expired("u", "gmail") is True
        assert await repo.is_expired("u", "slack") is False
        assert await repo.is_expired("u", "notion") is False
        assert await repo.is_expired("u", "never_added") is False

        assert await repo.is_connected("u", "gmail") is False
        assert await repo.is_connected("u", "notion") is True

    async def test_is_expired_is_scoped_to_the_user(self, repo):
        await repo.create(_ui("owner", "gmail", status="expired"))
        assert await repo.is_expired("intruder", "gmail") is False
