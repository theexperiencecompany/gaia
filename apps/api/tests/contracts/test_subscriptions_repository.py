"""Contract tests for SubscriptionsRepository (global, identity = Mongo _id)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.subscriptions import SubscriptionsRepository
from app.models.payment_models import SubscriptionDocument, SubscriptionUpdate


def _sub(**overrides: object) -> SubscriptionDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "dodo_subscription_id": "sub1",
        "user_id": "u1",
        "product_id": "prod1",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SubscriptionDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> SubscriptionsRepository:
    return SubscriptionsRepository()


class TestSubscriptionsRepository:
    async def test_create_and_get_by_dodo_id(self, repo):
        created = await repo.create(_sub(dodo_subscription_id="sub-x"))
        assert isinstance(created.id, str) and created.id
        got = await repo.get_by_dodo_id("sub-x")
        assert got is not None and got.dodo_subscription_id == "sub-x"
        assert await repo.get_by_dodo_id("missing") is None

    async def test_get_active_for_user_ignores_non_active(self, repo):
        await repo.create(_sub(user_id="u", dodo_subscription_id="a", status="active"))
        await repo.create(_sub(user_id="u", dodo_subscription_id="b", status="cancelled"))
        active = await repo.get_active_for_user("u")
        assert active is not None and active.dodo_subscription_id == "a"
        assert await repo.get_active_for_user("someone-else") is None

    async def test_get_latest_active_for_user(self, repo):
        await repo.create(
            _sub(
                user_id="u", dodo_subscription_id="old", created_at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        await repo.create(
            _sub(
                user_id="u", dodo_subscription_id="new", created_at=datetime(2026, 2, 1, tzinfo=UTC)
            )
        )
        latest = await repo.get_latest_active_for_user("u")
        assert latest is not None and latest.dodo_subscription_id == "new"

    async def test_has_any_for_user_ignores_status_and_scopes_to_the_user(self, repo):
        await repo.create(_sub(user_id="lapsed", dodo_subscription_id="s", status="cancelled"))
        assert await repo.has_any_for_user("lapsed") is True
        assert await repo.has_any_for_user("never-paid") is False

    async def test_get_user_id_by_dodo_id(self, repo):
        await repo.create(_sub(user_id="owner", dodo_subscription_id="s"))
        assert await repo.get_user_id_by_dodo_id("s") == "owner"
        assert await repo.get_user_id_by_dodo_id("nope") is None

    async def test_apply_update_by_dodo_id_sets_status_and_stamps_updated_at(self, repo):
        created = await repo.create(_sub(dodo_subscription_id="s", status="active"))
        matched = await repo.apply_update_by_dodo_id("s", SubscriptionUpdate(status="cancelled"))
        assert matched is True
        got = await repo.get_by_dodo_id("s")
        assert got is not None and got.status == "cancelled"
        assert got.updated_at is not None and got.updated_at >= created.updated_at
        assert (
            await repo.apply_update_by_dodo_id("missing", SubscriptionUpdate(status="x")) is False
        )
        assert (
            await repo.apply_update_by_dodo_id("s", SubscriptionUpdate()) is False
        )  # empty patch → no-op

    async def test_extra_billing_fields_preserved(self, repo):
        await repo.create(
            _sub(dodo_subscription_id="s", next_billing_date="2026-03-01", quantity=2)
        )
        got = await repo.get_by_dodo_id("s")
        assert got is not None
        dump = got.model_dump()
        assert dump["next_billing_date"] == "2026-03-01" and dump["quantity"] == 2
