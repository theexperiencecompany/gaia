"""Contract tests for SupportRequestsRepository (user-scoped, string UUID _id)."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest

from app.db.repositories.support_requests import SupportRequestsRepository
from app.models.support_models import (
    SupportRequestDocument,
    SupportRequestPriority,
    SupportRequestStatus,
    SupportRequestType,
)

NOW = datetime.now(UTC)


def _req(**overrides: object) -> SupportRequestDocument:
    data: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "user_id": "u1",
        "ticket_id": f"GAIA-{uuid.uuid4().hex[:8]}",
        "user_email": "u@example.com",
        "type": SupportRequestType.SUPPORT,
        "title": "Help",
        "description": "Something is broken",
        "created_at": NOW,
    }
    data.update(overrides)
    return SupportRequestDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> SupportRequestsRepository:
    return SupportRequestsRepository()


class TestSupportRequestsRepository:
    async def test_create_uses_uuid_as_string_id(self, repo):
        rid = uuid.uuid4().hex
        created = await repo.create(_req(id=rid, user_id="u"))
        assert created.id == rid  # caller-minted UUID is the _id, not an ObjectId
        assert created.updated_at is not None  # base stamps updated_at on insert

        fetched = await repo.get(rid, user_id="u")
        assert fetched is not None and fetched.ticket_id == created.ticket_id

    async def test_get_is_user_scoped(self, repo):
        rid = uuid.uuid4().hex
        await repo.create(_req(id=rid, user_id="owner"))
        assert await repo.get(rid, user_id="intruder") is None

    async def test_delete_rolls_back_and_is_scoped(self, repo):
        rid = uuid.uuid4().hex
        await repo.create(_req(id=rid, user_id="u"))
        assert await repo.delete(rid, user_id="other") is False  # scope guards delete
        assert await repo.delete(rid, user_id="u") is True
        assert await repo.get(rid, user_id="u") is None

    async def test_page_newest_first_and_status_filter(self, repo):
        await repo.create(_req(user_id="u", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await repo.create(
            _req(
                user_id="u",
                created_at=datetime(2026, 2, 1, tzinfo=UTC),
                status=SupportRequestStatus.RESOLVED,
            )
        )
        await repo.create(_req(user_id="other"))  # another user's ticket

        page = await repo.page_for_user("u", skip=0, limit=10)
        assert [d.created_at for d in page] == sorted((d.created_at for d in page), reverse=True)
        assert {d.user_id for d in page} == {"u"}
        assert await repo.count_for_user_status("u") == 2

        resolved = await repo.page_for_user(
            "u", status=SupportRequestStatus.RESOLVED, skip=0, limit=10
        )
        assert len(resolved) == 1
        assert resolved[0].status is SupportRequestStatus.RESOLVED
        assert await repo.count_for_user_status("u", status=SupportRequestStatus.OPEN) == 1

    async def test_priority_default_is_medium(self, repo):
        created = await repo.create(_req(user_id="u"))
        assert created.priority is SupportRequestPriority.MEDIUM
