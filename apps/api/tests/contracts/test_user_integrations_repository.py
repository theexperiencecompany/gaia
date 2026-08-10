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
