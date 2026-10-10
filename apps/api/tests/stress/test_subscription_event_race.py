"""Stress: two lifecycle events for one subscription, applied concurrently.

Real code under test: apply_subscription_event
(app/services/payments/subscription_events.py) — the one writer of subscription
state. It decides staleness by comparing the event's clock against the row's
last_event_at, which it read moments earlier, so read and write must be one
atomic step: two deliveries both pass the in-Python staleness check against the
same snapshot, and whichever writes last wins.

The repository is a stateful in-process fake with the find_one_and_update
semantics Mongo gives the real one — the guard is part of the filter, so a write
whose guard no longer matches the stored row touches nothing.

The invariant: an event older than one already applied can never overwrite the
newer status, whatever order the two writes land in.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment_models import SubscriptionDocument, SubscriptionStatus, SubscriptionUpdate
from app.models.webhook_models import DodoSubscriptionData
from app.services.payments.subscription_events import (
    SubscriptionEvent,
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    apply_subscription_event,
)

pytestmark = pytest.mark.stress

SUBSCRIPTION_ID = "sub_race_001"
USER_ID = "507f1f77bcf86cd799439011"

LAPSED_AT = datetime(2025, 3, 1, tzinfo=UTC)
ACTIVATED_AT = datetime(2025, 3, 2, tzinfo=UTC)
EXPIRED_AT = datetime(2025, 3, 3, tzinfo=UTC)


def _subscription_data(status: str) -> DodoSubscriptionData:
    return DodoSubscriptionData.model_validate(
        {
            "subscription_id": SUBSCRIPTION_ID,
            "product_id": "prod_abc123",
            "customer": {"customer_id": "cus_1", "email": "billing@example.com", "name": "Bill"},
            "billing": {
                "city": "SF",
                "country": "US",
                "state": "CA",
                "street": "1 Main",
                "zipcode": "94105",
            },
            "status": status,
            "currency": "usd",
            "quantity": 1,
            "recurring_pre_tax_amount": 2000,
            "payment_frequency_count": 1,
            "payment_frequency_interval": "month",
            "subscription_period_count": 1,
            "subscription_period_interval": "month",
            "created_at": LAPSED_AT.isoformat(),
            "metadata": {"user_id": USER_ID},
        }
    )


def _lapsed_row() -> SubscriptionDocument:
    return SubscriptionDocument.model_validate(
        {
            "id": "64b64b64b64b64b64b64b64b",
            "dodo_subscription_id": SUBSCRIPTION_ID,
            "user_id": USER_ID,
            "product_id": "prod_abc123",
            "status": SubscriptionStatus.ON_HOLD.value,
            "quantity": 1,
            "currency": "usd",
            "recurring_pre_tax_amount": 2000,
            "last_event_at": LAPSED_AT,
        }
    )


class _RacingSubscriptionRepository:
    """Mongo stand-in that schedules the interleaving instead of hoping for it.

    Both reducers read before either writes (the barrier), and the writes land
    in write_order — so the test can put the OLDER event's write last, the
    order in which a lost update rewrites history. apply_update_by_dodo_id
    reproduces the real filter semantics: if_not_newer_than is a condition
    on the stored row, not something the caller re-checks afterwards.
    """

    def __init__(self, row: SubscriptionDocument, write_order: list[datetime]) -> None:
        self.row = row
        self._both_read = asyncio.Barrier(2)
        self._write_order = write_order
        self._turn = 0
        self._turn_changed = asyncio.Condition()

    async def get_by_dodo_id(self, dodo_subscription_id: str) -> SubscriptionDocument | None:
        await self._both_read.wait()
        return self.row.model_copy(deep=True)

    async def apply_update_by_dodo_id(
        self,
        dodo_subscription_id: str,
        update: SubscriptionUpdate,
        *,
        # Defaulted so an unguarded write — the caller not passing a condition at
        # all — still reaches the row, and the test fails on the lost update
        # rather than on a signature mismatch.
        if_not_newer_than: datetime | None = None,
    ) -> bool:
        set_fields: dict[str, Any] = update.model_dump(exclude_unset=True)
        await self._await_turn(set_fields["last_event_at"])
        try:
            stored = self.row.last_event_at
            if if_not_newer_than is not None and stored is not None and stored > if_not_newer_than:
                return False
            self.row = self.row.model_copy(update=set_fields)
            return True
        finally:
            await self._end_turn()

    async def _await_turn(self, event_at: datetime) -> None:
        async with self._turn_changed:
            await self._turn_changed.wait_for(lambda: self._write_order[self._turn] == event_at)

    async def _end_turn(self) -> None:
        async with self._turn_changed:
            self._turn += 1
            self._turn_changed.notify_all()


@pytest.mark.usefixtures("_reducer_side_effects")
class TestConcurrentSubscriptionEvents:
    async def test_an_older_event_writing_last_cannot_restore_a_lapsed_subscription(
        self, reactivate_workflows: AsyncMock
    ) -> None:
        """Both reducers read the on-hold row and the older activation writes second."""
        repo = _RacingSubscriptionRepository(_lapsed_row(), write_order=[EXPIRED_AT, ACTIVATED_AT])

        with patch("app.services.payments.subscription_events.subscription_repository", repo):
            expired, activated = await asyncio.gather(
                apply_subscription_event(
                    SubscriptionEvent(
                        kind=SubscriptionEventKind.EXPIRED,
                        occurred_at=EXPIRED_AT,
                        data=_subscription_data("expired"),
                    )
                ),
                apply_subscription_event(
                    SubscriptionEvent(
                        kind=SubscriptionEventKind.ACTIVATED,
                        occurred_at=ACTIVATED_AT,
                        data=_subscription_data("active"),
                    )
                ),
            )

        assert repo.row.status == SubscriptionStatus.EXPIRED.value
        assert repo.row.last_event_at == EXPIRED_AT
        assert expired.outcome is SubscriptionEventOutcome.APPLIED
        assert activated.outcome is SubscriptionEventOutcome.STALE
        reactivate_workflows.assert_not_awaited()

    async def test_the_newer_event_still_applies_when_it_writes_last(
        self, reactivate_workflows: AsyncMock
    ) -> None:
        """The mirror image: a guard that refused every second writer would drop it."""
        repo = _RacingSubscriptionRepository(_lapsed_row(), write_order=[ACTIVATED_AT, EXPIRED_AT])

        with patch("app.services.payments.subscription_events.subscription_repository", repo):
            expired, activated = await asyncio.gather(
                apply_subscription_event(
                    SubscriptionEvent(
                        kind=SubscriptionEventKind.EXPIRED,
                        occurred_at=EXPIRED_AT,
                        data=_subscription_data("expired"),
                    )
                ),
                apply_subscription_event(
                    SubscriptionEvent(
                        kind=SubscriptionEventKind.ACTIVATED,
                        occurred_at=ACTIVATED_AT,
                        data=_subscription_data("active"),
                    )
                ),
            )

        assert repo.row.status == SubscriptionStatus.EXPIRED.value
        assert repo.row.last_event_at == EXPIRED_AT
        assert (expired.outcome, activated.outcome) == (
            SubscriptionEventOutcome.APPLIED,
            SubscriptionEventOutcome.APPLIED,
        )
        reactivate_workflows.assert_awaited_once_with(USER_ID)


@pytest.fixture
def reactivate_workflows() -> Any:
    """Patch the workflow resume at its source module, since the reducer defers the import."""
    with patch(
        "app.services.workflow.subscription_pause.reactivate_workflows_for_restored_subscription",
        new_callable=AsyncMock,
    ) as mock_fn:
        mock_fn.return_value = 0
        yield mock_fn


@pytest.fixture
def _reducer_side_effects() -> Any:
    """Patch everything the reducer fires alongside the write."""
    with (
        patch(
            "app.services.payments.subscription_events.invalidate_plan_cache",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.payments.subscription_events.track_subscription_event",
            MagicMock(),
        ),
        patch(
            "app.services.workflow.subscription_pause.deactivate_workflows_for_lapsed_subscription",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        yield
