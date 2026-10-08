"""Contract tests for PlansRepository (global subscription_plans catalog)."""

from __future__ import annotations

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.plans import PlansRepository
from app.models.payment_models import PlanDocument, PlanTier
from app.services.payments.payment_service import DodoPaymentService
from app.services.payments.plan_tier_backfill import backfill_plan_tiers


def _plan(**overrides: object) -> PlanDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "name": "Pro",
        "plan_type": "pro",
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


def _pre_migration_row(name: str, amount: int, duration: str, product_id: str) -> dict[str, object]:
    """Build a catalogue row as payment_setup.py wrote it before rows carried plan_type."""
    now = datetime.now(UTC)
    return {
        "name": name,
        "dodo_product_id": product_id,
        "amount": amount,
        "currency": "USD",
        "duration": duration,
        "features": [],
        "is_active": name != "Free",
        "created_at": now,
        "updated_at": now,
    }


PRE_MIGRATION_CATALOGUE = [
    _pre_migration_row("Free", 0, "monthly", ""),
    _pre_migration_row("Pro", 3000, "monthly", "pdt_m"),
    _pre_migration_row("Pro", 30000, "yearly", "pdt_y"),
    _pre_migration_row("Enterprise", 0, "monthly", ""),
]


class TestPlanTierBackfill:
    async def test_tag_one_untagged_tags_a_single_row_and_reports_when_none_is_left(
        self, repo: PlansRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await raw_collection.insert_many([dict(row) for row in PRE_MIGRATION_CATALOGUE[1:3]])

        assert await repo.tag_one_untagged("Pro", PlanTier.PRO) is True
        assert await repo.untagged_names() == ["Pro"]
        assert await repo.tag_one_untagged("Pro", PlanTier.PRO) is True
        assert await repo.tag_one_untagged("Pro", PlanTier.PRO) is False
        assert await repo.untagged_names() == []

    async def test_the_plans_endpoint_serves_a_pre_migration_catalogue_once_backfilled(
        self, repo: PlansRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await raw_collection.insert_many([dict(row) for row in PRE_MIGRATION_CATALOGUE])

        assert await backfill_plan_tiers() == 4
        plans = await DodoPaymentService().get_plans(active_only=False)

        assert sorted((p.name, p.plan_type, p.duration) for p in plans) == [
            ("Enterprise", PlanTier.ENTERPRISE, "monthly"),
            ("Pro", PlanTier.PRO, "monthly"),
            ("Pro", PlanTier.PRO, "yearly"),
        ]

    async def test_the_backfill_is_idempotent(
        self, repo: PlansRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await raw_collection.insert_many([dict(row) for row in PRE_MIGRATION_CATALOGUE])
        await backfill_plan_tiers()
        before = await raw_collection.find({}, {"_id": 0}).sort("amount", 1).to_list(None)

        assert await backfill_plan_tiers() == 0
        assert await raw_collection.find({}, {"_id": 0}).sort("amount", 1).to_list(None) == before

    async def test_a_row_with_no_known_tier_fails_loudly(
        self, repo: PlansRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await raw_collection.insert_one(_pre_migration_row("Team", 9900, "monthly", "pdt_t"))

        with pytest.raises(RuntimeError, match=r"no known tier: \['Team'\]"):
            await backfill_plan_tiers()
