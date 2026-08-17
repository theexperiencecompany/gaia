"""Contract tests for PlansRepository (global subscription_plans catalog)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.plans import PlansRepository
from app.models.payment_models import PlanDocument


def _plan(**overrides: object) -> PlanDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "name": "Pro",
        "amount": 1000,
        "currency": "usd",
        "duration": "monthly",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return PlanDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> PlansRepository:
    return PlansRepository()


class TestPlansRepository:
    async def test_create_roundtrips_string_id(self, repo):
        created = await repo.create(_plan(name="X"))
        assert isinstance(created.id, str) and created.id
        fetched = await repo.get(created.id)
        assert fetched is not None and fetched.name == "X"

    async def test_list_plans_active_only_cheapest_first(self, repo):
        await repo.create(_plan(name="B", amount=2000, is_active=True))
        await repo.create(_plan(name="A", amount=1000, is_active=True))
        await repo.create(_plan(name="Off", amount=500, is_active=False))

        active = await repo.list_plans(active_only=True)
        assert [p.amount for p in active] == [1000, 2000]  # inactive excluded, sorted asc

        every = await repo.list_plans(active_only=False)
        assert [p.amount for p in every] == [500, 1000, 2000]

    async def test_count(self, repo):
        await repo.create(_plan())
        await repo.create(_plan())
        assert await repo.count() == 2
