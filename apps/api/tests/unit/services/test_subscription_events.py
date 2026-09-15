"""``apply_subscription_event`` — the one writer of subscription state.

Every source of a subscription change (the Dodo webhooks, the user-initiated
cancel, payment verification's reconciliation) lands here, so the rules
below are asserted through those public entry points rather than against any
one handler: ordering, idempotency, recovery, and the scheduled cancel that
must never downgrade early.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from dodopayments.types import Subscription
import pytest

from app.constants.log_tags import LogTag
from app.constants.payments import SUBSCRIPTION_WORKFLOW_SYNC_TASK, SubscriptionWorkflowSync
from app.models.payment_models import SubscriptionDocument
from app.models.webhook_models import DodoSubscriptionData
from app.services.analytics_service import AnalyticsEvents, SubscriptionPlan
from app.services.payments.payment_service import DodoPaymentService
from app.services.payments.subscription_events import (
    DESIRED_STATE,
    SubscriptionEvent,
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    SubscriptionEventResult,
    apply_subscription_event,
    deactivate_workflows_safely,
    reactivate_workflows_safely,
    resolve_subscription_owner,
    send_welcome_email_safely,
)
from tests.helpers import captured_wide_event
from tests.unit.services.conftest import (
    FAKE_EMAIL,
    FAKE_USER_ID,
    SUBSCRIPTION_DATA_PAYLOAD,
    _make_webhook_event,
)

pytestmark = pytest.mark.usefixtures(
    "mock_processed_webhook_repository",
    "mock_activation_workflow_reactivation",
    "mock_deactivate_workflows",
)

SERVICE_MODULE = "app.services.payments.payment_service"

RECOVERED_AT = "2025-03-01T00:00:00Z"
BEFORE_RECOVERY = "2025-02-28T00:00:00Z"


def _row(**overrides: Any) -> SubscriptionDocument:
    base: dict[str, Any] = {
        "id": "64b64b64b64b64b64b64b64b",
        "dodo_subscription_id": SUBSCRIPTION_DATA_PAYLOAD["subscription_id"],
        "user_id": FAKE_USER_ID,
        "product_id": SUBSCRIPTION_DATA_PAYLOAD["product_id"],
        "status": "active",
        "quantity": 1,
        "recurring_pre_tax_amount": 999,
        "next_billing_date": SUBSCRIPTION_DATA_PAYLOAD["next_billing_date"],
        "previous_billing_date": SUBSCRIPTION_DATA_PAYLOAD["previous_billing_date"],
        "cancel_at_next_billing_date": None,
        "last_event_at": datetime.fromisoformat(RECOVERED_AT),
    }
    base.update(overrides)
    return SubscriptionDocument.model_validate(base)


def _event(event_type: str, timestamp: str, **data_overrides: Any) -> dict[str, Any]:
    event = _make_webhook_event(event_type, {**SUBSCRIPTION_DATA_PAYLOAD, **data_overrides})
    event["timestamp"] = timestamp
    return event


def _written_fields(repo: MagicMock) -> dict[str, Any]:
    return repo.apply_update_by_dodo_id.await_args.args[1].model_dump(exclude_unset=True)


@pytest.mark.unit
class TestOrdering:
    async def test_an_event_older_than_the_rows_last_change_is_a_no_op(
        self, webhook_service, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        """Dodo retries out of order: a delayed ``on_hold`` can land after the
        ``active`` that recovered the same subscription. Applying it would put
        a paying user back on hold until the next event happened to arrive."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=datetime.fromisoformat(RECOVERED_AT))
        )

        async with captured_wide_event() as wide:
            result = await webhook_service.process_webhook(
                _event("subscription.on_hold", BEFORE_RECOVERY), "wh_late_hold"
            )

        assert (result.status, result.message) == ("ignored", "Stale event")
        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_not_awaited()
        mock_track_subscription.assert_not_called()
        assert wide["warnings"] == [
            {
                "msg": f"{LogTag.PAYMENT} Stale subscription event ignored",
                "event_kind": "on_hold",
                "subscription_id": SUBSCRIPTION_DATA_PAYLOAD["subscription_id"],
                "event_at": BEFORE_RECOVERY,
                "row_last_event_at": RECOVERED_AT,
            }
        ]


@pytest.mark.unit
class TestIdempotency:
    async def test_replaying_the_current_state_writes_nothing_and_fires_no_analytics(
        self, webhook_service, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=_row())

        result = await webhook_service.process_webhook(
            _event("subscription.active", "2025-03-02T00:00:00Z"), "wh_active_replay"
        )

        assert result.status == "processed"
        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_not_awaited()
        mock_webhook_subscription_repository.create.assert_not_awaited()
        mock_track_subscription.assert_not_called()

    async def test_a_scheduled_cancel_already_recorded_is_not_captured_twice(
        self, webhook_service, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        """The user's own cancel request records the flag first; Dodo's
        ``subscription.cancelled`` then reports the same state. One
        cancellation, one ``subscription:cancelled``."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(cancel_at_next_billing_date=True)
        )

        await webhook_service.process_webhook(
            _event(
                "subscription.cancelled", "2025-03-02T00:00:00Z", cancel_at_next_billing_date=True
            ),
            "wh_cancel_replay",
        )

        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_not_awaited()
        mock_track_subscription.assert_not_called()


@pytest.mark.unit
class TestRecovery:
    @pytest.mark.parametrize("lapsed_status", ["on_hold", "failed", "expired", "cancelled"])
    async def test_active_after_a_lapse_writes_status_and_billing_dates_and_captures_once(
        self,
        lapsed_status: str,
        webhook_service,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ) -> None:
        """The row existing is not the row being active. Recovery used to
        restore the workflows and drop the cache, but never wrote the status
        back — so ``get_active_for_user`` kept filtering the row out and the
        customer kept reading FREE — and never carried the new billing dates."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(
                status=lapsed_status,
                next_billing_date="2025-01-01",
                previous_billing_date="2024-12-01",
                last_event_at=datetime.fromisoformat(BEFORE_RECOVERY),
            )
        )

        result = await webhook_service.process_webhook(
            _event("subscription.active", RECOVERED_AT), "wh_recover"
        )

        assert result.status == "processed"
        written = _written_fields(mock_webhook_subscription_repository)
        assert written["status"] == "active"
        assert written["next_billing_date"] == SUBSCRIPTION_DATA_PAYLOAD["next_billing_date"]
        assert (
            written["previous_billing_date"] == (SUBSCRIPTION_DATA_PAYLOAD["previous_billing_date"])
        )
        assert written["last_event_at"] == datetime.fromisoformat(RECOVERED_AT)
        mock_track_subscription.assert_called_once()
        assert mock_track_subscription.call_args.kwargs["user_id"] == FAKE_USER_ID
        assert (
            mock_track_subscription.call_args.kwargs["event_type"]
            == AnalyticsEvents.SUBSCRIPTION_ACTIVATED
        )


def _dodo_subscription(status: str) -> Subscription:
    return Subscription.model_validate(
        {
            "subscription_id": SUBSCRIPTION_DATA_PAYLOAD["subscription_id"],
            "product_id": SUBSCRIPTION_DATA_PAYLOAD["product_id"],
            "status": status,
            "quantity": 1,
            "currency": "USD",
            "recurring_pre_tax_amount": 999,
            "payment_frequency_count": 1,
            "payment_frequency_interval": "Month",
            "subscription_period_count": 1,
            "subscription_period_interval": "Month",
            "next_billing_date": datetime(2025, 2, 1, tzinfo=UTC),
            "previous_billing_date": datetime(2025, 1, 1, tzinfo=UTC),
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "cancelled_at": datetime(2025, 1, 15, tzinfo=UTC),
            "metadata": {"user_id": FAKE_USER_ID},
            "customer": {"customer_id": "cus_1", "email": FAKE_EMAIL, "name": "Alice"},
            "billing": {"country": "US"},
            "addons": [],
            "meters": [],
            "cancel_at_next_billing_date": True,
            "on_demand": False,
            "tax_inclusive": False,
            "trial_period_days": 0,
        }
    )


@pytest.mark.unit
class TestScheduledCancelNeverDowngradesEarly:
    @pytest.mark.parametrize("dodo_status", ["active", "cancelled"])
    async def test_the_users_own_cancel_keeps_the_status_until_expiry(
        self,
        dodo_status: str,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ) -> None:
        """``cancel_subscription`` used to mirror whatever status Dodo returned.
        The webhook path already refused to do that — a cancel scheduled for
        period end keeps the user on Pro until ``subscription.expired`` — and
        the two paths must agree, or the same cancel downgrades a user early
        depending only on which path recorded it first."""
        service = DodoPaymentService()
        service.client = MagicMock()
        service.client.subscriptions.update.return_value = _dodo_subscription(dodo_status)
        row = _row(last_event_at=None)
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=row)

        with (
            patch(f"{SERVICE_MODULE}.subscription_repository") as service_repo,
            patch.object(service, "get_user_subscription_status", new_callable=AsyncMock),
        ):
            service_repo.get_active_for_user = AsyncMock(return_value=row)
            await service.cancel_subscription(FAKE_USER_ID)

        written = _written_fields(mock_webhook_subscription_repository)
        assert "status" not in written
        assert written["cancel_at_next_billing_date"] is True
        assert written["cancelled_at"] == "2025-01-15T00:00:00Z"
        # One cancellation, captured where it was recorded — the webhook that
        # follows finds the state already written (see TestIdempotency).
        mock_track_subscription.assert_called_once()
        assert (
            mock_track_subscription.call_args.kwargs["event_type"]
            == AnalyticsEvents.SUBSCRIPTION_CANCELLED
        )


# ============================================================================
# The reducer directly: what each transition writes and fires
# ============================================================================

EVENTS_MODULE = "app.services.payments.subscription_events"
PAUSE = "app.services.workflow.subscription_pause"
NOW = datetime(2025, 3, 2, tzinfo=UTC)


def _sub_data(**overrides: Any) -> DodoSubscriptionData:
    return DodoSubscriptionData.model_validate({**SUBSCRIPTION_DATA_PAYLOAD, **overrides})


def _apply(kind: SubscriptionEventKind, **overrides: Any):
    return apply_subscription_event(
        SubscriptionEvent(kind=kind, occurred_at=NOW, data=_sub_data(**overrides))
    )


@pytest.mark.unit
class TestActivationCreatesTheRow:
    @pytest.fixture(autouse=True)
    def _no_row(self, mock_webhook_subscription_repository) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)

    async def test_writes_every_dodo_field_onto_the_new_row(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
    ) -> None:
        result = await _apply(SubscriptionEventKind.ACTIVATED)

        created = mock_webhook_subscription_repository.create.await_args.args[0]
        assert created.dodo_subscription_id == "sub_xyz789"
        assert created.user_id == FAKE_USER_ID
        assert created.product_id == "prod_abc123"
        assert created.status == "active"
        assert created.quantity == 1
        assert created.currency == "USD"
        assert created.recurring_pre_tax_amount == 999
        assert created.payment_frequency_count == 1
        assert created.payment_frequency_interval == "month"
        assert created.subscription_period_count == 1
        assert created.subscription_period_interval == "month"
        assert created.next_billing_date == "2025-02-01"
        assert created.previous_billing_date == "2025-01-01"
        assert created.last_event_at == NOW
        assert created.metadata == {"user_id": FAKE_USER_ID}
        # One UTC-aware instant on both timestamps, never a naive local one.
        assert created.created_at is not None
        assert created.created_at.utcoffset() == timedelta(0)
        assert created.updated_at == created.created_at
        assert result == SubscriptionEventResult(SubscriptionEventOutcome.CREATED, FAKE_USER_ID)

    async def test_captures_the_priced_pro_plan_in_dollars_once_and_welcomes_the_user(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_activation_workflow_reactivation,
    ) -> None:
        await _apply(SubscriptionEventKind.ACTIVATED)

        mock_track_subscription.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            subscription_id="sub_xyz789",
            plan=SubscriptionPlan(name="Pro", amount=9.99, currency="USD"),
        )
        mock_webhook_send_email.assert_awaited_once_with(
            user_name="Alice", user_email=FAKE_EMAIL, user_id=FAKE_USER_ID
        )
        mock_subscription_plan_cache_drop.assert_awaited_once_with(FAKE_USER_ID)
        mock_activation_workflow_reactivation.assert_awaited_once_with(FAKE_USER_ID)

    async def test_a_zero_amount_subscription_reports_no_price(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
    ) -> None:
        await _apply(SubscriptionEventKind.ACTIVATED, recurring_pre_tax_amount=0)

        assert mock_track_subscription.call_args.kwargs["plan"].amount is None

    async def test_falls_back_to_the_customer_email_to_find_the_owner(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
    ) -> None:
        result = await _apply(SubscriptionEventKind.ACTIVATED, metadata={})

        mock_webhook_users_collection.get_by_email.assert_awaited_once_with(FAKE_EMAIL)
        assert result.user_id == FAKE_USER_ID

    async def test_a_subscription_belonging_to_nobody_is_not_written(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_track_subscription,
    ) -> None:
        mock_webhook_users_collection.get_by_email = AsyncMock(return_value=None)

        async with captured_wide_event() as wide:
            result = await _apply(SubscriptionEventKind.ACTIVATED, metadata={})

        mock_webhook_subscription_repository.create.assert_not_awaited()
        mock_track_subscription.assert_not_called()
        assert result == SubscriptionEventResult(SubscriptionEventOutcome.NO_OWNER, None)
        assert wide["errors"] == [
            {
                "msg": f"{LogTag.PAYMENT} User not found for subscription",
                "subscription_id": "sub_xyz789",
            }
        ]

    async def test_a_lifecycle_event_never_creates_a_row(
        self, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        result = await _apply(SubscriptionEventKind.RENEWED)

        mock_webhook_subscription_repository.create.assert_not_awaited()
        assert result == SubscriptionEventResult(SubscriptionEventOutcome.NO_ROW, None)


@pytest.mark.unit
class TestTransitionsDriveTheSideEffects:
    """Workflows follow the status: crossing into ``active`` restores them,
    leaving it pauses them, and anything else leaves them alone."""

    async def test_a_lapse_pauses_the_workflows_and_a_recovery_restores_them(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_deactivate_workflows,
        mock_activation_workflow_reactivation,
    ) -> None:
        await _apply(SubscriptionEventKind.ON_HOLD)
        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)
        mock_activation_workflow_reactivation.assert_not_awaited()

        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(status="on_hold", last_event_at=None)
        )
        await _apply(SubscriptionEventKind.RENEWED)
        mock_activation_workflow_reactivation.assert_awaited_once_with(FAKE_USER_ID)
        mock_deactivate_workflows.assert_awaited_once()

    async def test_an_existing_row_recovered_by_activation_is_not_welcomed_again(
        self,
        mock_webhook_subscription_repository,
        mock_webhook_send_email,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_activation_workflow_reactivation,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(status="failed", last_event_at=None)
        )

        result = await _apply(SubscriptionEventKind.ACTIVATED)

        assert result.outcome is SubscriptionEventOutcome.APPLIED
        mock_webhook_send_email.assert_not_awaited()
        mock_subscription_plan_cache_drop.assert_awaited_once_with(FAKE_USER_ID)

    async def test_an_immediate_cancel_drops_the_status_pauses_and_captures(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_deactivate_workflows,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=None)
        )

        await _apply(
            SubscriptionEventKind.CANCELLED,
            cancel_at_next_billing_date=False,
            cancelled_at="2025-03-02T00:00:00Z",
        )

        written = _written_fields(mock_webhook_subscription_repository)
        assert written["status"] == "cancelled"
        assert written["cancelled_at"] == "2025-03-02T00:00:00Z"
        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)
        mock_track_subscription.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.SUBSCRIPTION_CANCELLED,
            subscription_id="sub_xyz789",
            properties={"product_id": "prod_abc123", "billing_interval": "month"},
        )

    async def test_a_scheduled_cancel_keeps_the_workflows_running(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_deactivate_workflows,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=None)
        )

        await _apply(SubscriptionEventKind.CANCELLED, cancel_at_next_billing_date=True)

        written = _written_fields(mock_webhook_subscription_repository)
        assert "status" not in written
        assert written["cancel_at_next_billing_date"] is True
        mock_deactivate_workflows.assert_not_awaited()

    async def test_expiry_captures_and_pauses(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_deactivate_workflows,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=None)
        )

        await _apply(SubscriptionEventKind.EXPIRED)

        assert _written_fields(mock_webhook_subscription_repository)["status"] == "expired"
        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)
        mock_track_subscription.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.SUBSCRIPTION_EXPIRED,
            subscription_id="sub_xyz789",
        )

    async def test_a_plan_change_touches_neither_workflows_nor_analytics(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_deactivate_workflows,
        mock_activation_workflow_reactivation,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(product_id="prod_old", last_event_at=None)
        )

        await _apply(SubscriptionEventKind.PLAN_CHANGED)

        assert _written_fields(mock_webhook_subscription_repository) == {
            "product_id": "prod_abc123",
            "last_event_at": NOW,
        }
        mock_track_subscription.assert_not_called()
        mock_deactivate_workflows.assert_not_awaited()
        mock_activation_workflow_reactivation.assert_not_awaited()
        # The gate reads the tier off a cache; any write drops it.
        mock_subscription_plan_cache_drop.assert_awaited_once_with(FAKE_USER_ID)

    async def test_a_renewal_that_omits_the_dates_leaves_the_stored_ones_alone(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_activation_workflow_reactivation,
    ) -> None:
        """``None`` in the update would be written as null over a good value."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(status="on_hold", last_event_at=None)
        )

        await _apply(
            SubscriptionEventKind.RENEWED, next_billing_date=None, previous_billing_date=None
        )

        written = _written_fields(mock_webhook_subscription_repository)
        assert written["status"] == "active"
        assert "next_billing_date" not in written
        assert "previous_billing_date" not in written


@pytest.mark.unit
class TestSideEffectsNeverFailTheEvent:
    """A workflow or email failure must not turn an otherwise-recorded billing
    change into a failure Dodo would retry; it is logged with its cause."""

    async def test_a_reactivation_failure_is_swallowed_and_logged(self) -> None:
        with (
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{EVENTS_MODULE}.log") as mock_log,
            patch(f"{EVENTS_MODULE}.enqueue_worker_job", new_callable=AsyncMock),
            patch(f"{EVENTS_MODULE}.RedisPoolManager.get_pool", new_callable=AsyncMock),
        ):
            await reactivate_workflows_safely(FAKE_USER_ID)

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to reactivate workflows for restored subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=FAKE_USER_ID,
        )

    async def test_a_deactivation_failure_is_swallowed_and_logged(self) -> None:
        with (
            patch(
                f"{PAUSE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{EVENTS_MODULE}.log") as mock_log,
            patch(f"{EVENTS_MODULE}.enqueue_worker_job", new_callable=AsyncMock),
            patch(f"{EVENTS_MODULE}.RedisPoolManager.get_pool", new_callable=AsyncMock),
        ):
            await deactivate_workflows_safely(FAKE_USER_ID)

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to deactivate workflows for lapsed subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=FAKE_USER_ID,
        )


@pytest.mark.unit
class TestAFailedWorkflowSyncIsOwedToTheWorker:
    """Dodo's own retry cannot recover this one.

    By the time the pause runs the row already carries the reported status, so a
    redelivery reduces to "unchanged" and never reaches the workflows again — the
    remainder has to become durable work here or it is lost for good.
    """

    async def test_a_deactivation_failure_queues_the_lapsed_sync(self) -> None:
        pool = object()
        with (
            patch(
                f"{PAUSE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("composio down"),
            ),
            patch(
                f"{EVENTS_MODULE}.RedisPoolManager.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
            patch(f"{EVENTS_MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue,
        ):
            await deactivate_workflows_safely(FAKE_USER_ID)

        enqueue.assert_awaited_once_with(
            pool,
            SUBSCRIPTION_WORKFLOW_SYNC_TASK,
            FAKE_USER_ID,
            SubscriptionWorkflowSync.PAUSE.value,
            _job_id=f"{SUBSCRIPTION_WORKFLOW_SYNC_TASK}:{FAKE_USER_ID}:pause",
        )

    async def test_a_reactivation_failure_queues_the_restored_sync(self) -> None:
        pool = object()
        with (
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("composio down"),
            ),
            patch(
                f"{EVENTS_MODULE}.RedisPoolManager.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
            patch(f"{EVENTS_MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue,
        ):
            await reactivate_workflows_safely(FAKE_USER_ID)

        enqueue.assert_awaited_once_with(
            pool,
            SUBSCRIPTION_WORKFLOW_SYNC_TASK,
            FAKE_USER_ID,
            SubscriptionWorkflowSync.RESUME.value,
            _job_id=f"{SUBSCRIPTION_WORKFLOW_SYNC_TASK}:{FAKE_USER_ID}:resume",
        )

    async def test_a_successful_pause_queues_nothing(self) -> None:
        with (
            patch(
                f"{PAUSE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(f"{EVENTS_MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue,
        ):
            await deactivate_workflows_safely(FAKE_USER_ID)

        enqueue.assert_not_awaited()

    async def test_a_queue_that_is_itself_down_is_reported_not_hidden(self) -> None:
        """The line naming the user is the only trace the stranded workflows leave."""
        with (
            patch(
                f"{PAUSE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("composio down"),
            ),
            patch(
                f"{EVENTS_MODULE}.RedisPoolManager.get_pool",
                new_callable=AsyncMock,
                side_effect=ConnectionError("redis down"),
            ),
            patch(f"{EVENTS_MODULE}.log") as mock_log,
        ):
            await deactivate_workflows_safely(FAKE_USER_ID)

        assert mock_log.error.call_count == 2
        assert mock_log.error.call_args.kwargs["user_id"] == FAKE_USER_ID
        assert "could not be queued" in mock_log.error.call_args.args[0]

    async def test_the_welcome_mail_names_who_was_mailed_not_where(
        self, mock_webhook_users_collection, mock_webhook_send_email
    ) -> None:
        with patch(f"{EVENTS_MODULE}.log") as mock_log:
            await send_welcome_email_safely(FAKE_USER_ID)

        mock_webhook_users_collection.get.assert_awaited_once_with(FAKE_USER_ID)
        mock_webhook_send_email.assert_awaited_once_with(
            user_name="Alice", user_email=FAKE_EMAIL, user_id=FAKE_USER_ID
        )
        # The address is mailed, never logged: log fields are ids, counts and
        # enums, so the line names who was mailed rather than where.
        mock_log.info.assert_called_once_with("[PAYMENT] Welcome email sent", user_id=FAKE_USER_ID)

    async def test_a_user_without_an_email_is_never_mailed(
        self, mock_webhook_users_collection, mock_webhook_send_email
    ) -> None:
        mock_webhook_users_collection.get = AsyncMock(
            return_value=MagicMock(first_name="Alice", email=None)
        )

        await send_welcome_email_safely(FAKE_USER_ID)

        mock_webhook_send_email.assert_not_awaited()

    async def test_a_user_with_no_first_name_is_greeted_generically(
        self, mock_webhook_users_collection, mock_webhook_send_email
    ) -> None:
        mock_webhook_users_collection.get = AsyncMock(
            return_value=MagicMock(first_name=None, email="a@example.com")
        )

        await send_welcome_email_safely(FAKE_USER_ID)

        assert mock_webhook_send_email.await_args.kwargs["user_name"] == "User"

    async def test_a_mail_failure_is_swallowed_and_logged(
        self, mock_webhook_users_collection, mock_webhook_send_email
    ) -> None:
        mock_webhook_send_email.side_effect = RuntimeError("SMTP down")

        with patch(f"{EVENTS_MODULE}.log") as mock_log:
            await send_welcome_email_safely(FAKE_USER_ID)

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to send welcome email",
            error="SMTP down",
            error_type="RuntimeError",
            user_id=FAKE_USER_ID,
        )


@pytest.mark.unit
class TestResolveSubscriptionOwner:
    async def test_metadata_user_id_wins_without_touching_the_user_repository(
        self, mock_webhook_users_collection
    ) -> None:
        owner = await resolve_subscription_owner(_sub_data())

        assert owner == FAKE_USER_ID
        mock_webhook_users_collection.get_by_email.assert_not_awaited()

    async def test_an_unknown_customer_email_belongs_to_nobody(
        self, mock_webhook_users_collection
    ) -> None:
        mock_webhook_users_collection.get_by_email = AsyncMock(return_value=None)

        assert await resolve_subscription_owner(_sub_data(metadata={})) is None


@pytest.mark.unit
class TestDesiredState:
    """What each event kind says the row should now have — the exact fields,
    because the repository writes exactly these as ``$set``."""

    def test_activation_and_renewal_carry_the_billing_dates(self) -> None:
        for kind in (SubscriptionEventKind.ACTIVATED, SubscriptionEventKind.RENEWED):
            desired = DESIRED_STATE[kind](_sub_data()).model_dump(exclude_unset=True)
            assert desired == {
                "status": "active",
                "next_billing_date": "2025-02-01",
                "previous_billing_date": "2025-01-01",
            }

    def test_a_scheduled_cancel_records_the_flag_and_leaves_the_status_alone(self) -> None:
        desired = DESIRED_STATE[SubscriptionEventKind.CANCELLED](
            _sub_data(cancel_at_next_billing_date=True, cancelled_at="2025-01-15T00:00:00Z")
        )
        assert desired.model_dump(exclude_unset=True) == {
            "cancel_at_next_billing_date": True,
            "cancelled_at": "2025-01-15T00:00:00Z",
            "next_billing_date": "2025-02-01",
        }

    def test_an_immediate_cancel_drops_the_status_now(self) -> None:
        desired = DESIRED_STATE[SubscriptionEventKind.CANCELLED](
            _sub_data(cancel_at_next_billing_date=False, cancelled_at=None, next_billing_date=None)
        )
        assert desired.model_dump(exclude_unset=True) == {
            "cancel_at_next_billing_date": False,
            "status": "cancelled",
        }

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (SubscriptionEventKind.EXPIRED, "expired"),
            (SubscriptionEventKind.FAILED, "failed"),
            (SubscriptionEventKind.ON_HOLD, "on_hold"),
        ],
    )
    def test_a_lapse_is_exactly_its_status(self, kind: SubscriptionEventKind, status: str) -> None:
        assert DESIRED_STATE[kind](_sub_data()).model_dump(exclude_unset=True) == {"status": status}

    def test_a_plan_change_is_the_product_quantity_and_price(self) -> None:
        desired = DESIRED_STATE[SubscriptionEventKind.PLAN_CHANGED](
            _sub_data(product_id="prod_new", quantity=3, recurring_pre_tax_amount=4500)
        )
        assert desired.model_dump(exclude_unset=True) == {
            "product_id": "prod_new",
            "quantity": 3,
            "recurring_pre_tax_amount": 4500,
        }


@pytest.mark.unit
class TestResultsNameTheOwnerAndTheRow:
    """Every outcome hands back the owner the caller acts on, and every write
    targets the row that was read — not some other id."""

    async def test_an_equal_timestamp_is_not_stale_and_the_result_names_the_owner(
        self,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_subscription_plan_cache_drop,
        mock_activation_workflow_reactivation,
    ) -> None:
        """Dodo can stamp two events in the same second; only strictly older
        ones are stale."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(status="on_hold", last_event_at=NOW)
        )

        result = await _apply(SubscriptionEventKind.RENEWED)

        assert result == SubscriptionEventResult(SubscriptionEventOutcome.APPLIED, FAKE_USER_ID)
        dodo_id, update = (
            mock_webhook_subscription_repository.apply_update_by_dodo_id.await_args.args
        )
        assert dodo_id == "sub_xyz789"
        assert update.last_event_at == NOW
        mock_subscription_plan_cache_drop.assert_awaited_once_with(FAKE_USER_ID)
        mock_activation_workflow_reactivation.assert_awaited_once_with(FAKE_USER_ID)
        mock_track_subscription.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.SUBSCRIPTION_RENEWED,
            subscription_id="sub_xyz789",
            plan=SubscriptionPlan(currency="USD"),
        )

    async def test_a_stale_event_still_names_the_owner(
        self, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=NOW + timedelta(seconds=1))
        )

        result = await _apply(SubscriptionEventKind.ON_HOLD)

        assert result == SubscriptionEventResult(SubscriptionEventOutcome.STALE, FAKE_USER_ID)

    async def test_an_unchanged_event_still_names_the_owner(
        self, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(last_event_at=None)
        )

        result = await _apply(SubscriptionEventKind.ACTIVATED)

        assert result == SubscriptionEventResult(SubscriptionEventOutcome.UNCHANGED, FAKE_USER_ID)

    async def test_a_missing_row_is_on_the_record_by_kind_and_id(
        self, mock_webhook_subscription_repository, mock_track_subscription
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)

        async with captured_wide_event() as wide:
            result = await _apply(SubscriptionEventKind.EXPIRED)

        assert result == SubscriptionEventResult(SubscriptionEventOutcome.NO_ROW, None)
        assert wide["errors"] == [
            {
                "msg": f"{LogTag.PAYMENT} No local subscription matched the Dodo id",
                "event_kind": "expired",
                "subscription_id": "sub_xyz789",
            }
        ]
