"""The billing-webhook <-> workflow-pause integration in ``PaymentWebhookService``.

subscription.active / subscription.renewed reactivate paused workflows;
subscription.failed / subscription.on_hold deactivate them. Workflows
deactivated with DeactivationReason.SUBSCRIPTION_LAPSED (cancel, expire,
payment failure, on-hold) were never turned back on when the user
resubscribed — nothing called ``reactivate_workflows_for_restored_subscription``
from the billing webhook path. See ``app/services/workflow/subscription_pause.py``.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.webhook_models import (
    DodoBillingData,
    DodoCustomerData,
    DodoSubscriptionData,
    DodoWebhookEvent,
    DodoWebhookEventType,
)
from app.services.analytics_service import AnalyticsEvents, SubscriptionPlan
from app.services.payments.payment_webhook_service import PaymentWebhookService
from app.services.payments.subscription_activation import (
    SubscriptionActivation,
    activate_subscription,
    reactivate_workflows_safely,
    resolve_subscription_owner,
    send_welcome_email_safely,
)

MODULE = "app.services.payments.payment_webhook_service"
ACTIVATION = "app.services.payments.subscription_activation"
# `subscription_activation` imports this lazily (it would otherwise pull the
# workflow stack into `app.decorators`' import graph), so it is only ever
# patchable at its source module.
PAUSE = "app.services.workflow.subscription_pause"

USER_ID = "507f1f77bcf86cd799439011"


def _billing() -> DodoBillingData:
    return DodoBillingData(city="SF", country="US", state="CA", street="1 Main St", zipcode="94105")


def _customer() -> DodoCustomerData:
    return DodoCustomerData(customer_id="cus_1", email="user@example.com", name="Test User")


def _subscription_data(**overrides: object) -> DodoSubscriptionData:
    base: dict = {
        "subscription_id": "sub_123",
        "product_id": "prod_pro",
        "customer": _customer(),
        "billing": _billing(),
        "status": "active",
        "currency": "usd",
        "quantity": 1,
        "recurring_pre_tax_amount": 2000,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "Month",
        "subscription_period_count": 1,
        "subscription_period_interval": "Month",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"user_id": USER_ID},
    }
    base.update(overrides)
    return DodoSubscriptionData(**base)


def _event(event_type: DodoWebhookEventType, **overrides: object) -> DodoWebhookEvent:
    return DodoWebhookEvent(
        business_id="biz_1",
        type=event_type,
        timestamp="2026-01-01T00:00:00Z",
        data=_subscription_data(**overrides).model_dump(),
    )


@pytest.mark.unit
class TestSubscriptionActiveReactivatesWorkflows:
    async def test_existing_subscription_reactivates_paused_workflows(self) -> None:
        """The common resubscribe path: Dodo re-fires `subscription.active` for a
        subscription row that already exists (early-return branch)."""
        service = PaymentWebhookService()
        existing = MagicMock(user_id=USER_ID)
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=existing)
            result = await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        assert result.status == "processed"
        # The message is the only thing distinguishing a redelivery from a real
        # activation in Dodo's dashboard and in our own webhook log.
        assert result.message == "Subscription already active"
        reactivate.assert_awaited_once_with(USER_ID)

    async def test_newly_created_subscription_reactivates_paused_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
            patch(f"{ACTIVATION}.track_subscription_event"),
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            result = await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        assert result.status == "processed"
        assert result.message == "Subscription activated"
        reactivate.assert_awaited_once_with(USER_ID)

    async def test_a_subscription_belonging_to_nobody_fails_the_webhook(self) -> None:
        """Dodo retries a failed result, so the ownerless subscription has to come
        back as a failure that names why rather than a silent success."""
        service = PaymentWebhookService()
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            users.get_by_email = AsyncMock(return_value=None)
            result = await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE, metadata={})
            )

        assert result.status == "failed"
        assert result.message == "User not found"
        reactivate.assert_not_awaited()


@pytest.mark.unit
class TestSubscriptionActivatedAnalytics:
    """The server owns ``subscription:activated`` — it is the only place a
    completed subscription is captured (the web app's success page used to fire
    its own ``subscription:completed`` for the same action, double-counting it
    and missing every overlay checkout that never lands on that page)."""

    async def test_activation_captures_the_event_once_against_the_gaia_user_id(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ),
            patch(f"{ACTIVATION}.track_subscription_event") as track,
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        track.assert_called_once()
        assert track.call_args.kwargs["user_id"] == USER_ID
        assert track.call_args.kwargs["event_type"] == AnalyticsEvents.SUBSCRIPTION_ACTIVATED
        assert track.call_args.kwargs["subscription_id"] == "sub_123"

    async def test_a_redelivered_activation_does_not_capture_a_second_time(self) -> None:
        """Dodo re-fires ``subscription.active`` for an existing row; that early
        return must not inflate the activation count."""
        service = PaymentWebhookService()
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ),
            patch(f"{ACTIVATION}.track_subscription_event") as track,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=MagicMock(user_id=USER_ID))
            await service._handle_subscription_active(
                _event(DodoWebhookEventType.SUBSCRIPTION_ACTIVE)
            )

        track.assert_not_called()


@pytest.mark.unit
class TestSubscriptionRenewedReactivatesWorkflows:
    async def test_renewal_reactivates_paused_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
            ) as reactivate,
            patch(f"{MODULE}.track_subscription_event") as track,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)
            result = await service._handle_subscription_renewed(
                _event(DodoWebhookEventType.SUBSCRIPTION_RENEWED, currency="eur")
            )

        assert result.status == "processed"
        reactivate.assert_awaited_once_with(USER_ID)
        # Revenue reporting splits on currency; a renewal that reports none is
        # counted in the default currency and quietly skews the numbers.
        assert track.call_args.kwargs["plan"] == SubscriptionPlan(currency="eur")

    async def test_reactivation_failure_never_fails_the_webhook(self) -> None:
        """Same swallow-and-log posture as deactivation — a reactivation bug must
        not turn an otherwise-successful billing webhook into a Dodo retry."""
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch(f"{MODULE}.track_subscription_event"),
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock(return_value=True)
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)
            result = await service._handle_subscription_renewed(
                _event(DodoWebhookEventType.SUBSCRIPTION_RENEWED)
            )

        assert result.status == "processed"


@pytest.mark.unit
class TestSubscriptionFailedDeactivatesWorkflows:
    async def test_marks_the_subscription_failed_and_deactivates_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)

            result = await service._handle_subscription_failed(
                _event(DodoWebhookEventType.SUBSCRIPTION_FAILED, subscription_id="sub_failed")
            )

        sub_repo.apply_update_by_dodo_id.assert_awaited_once()
        call_args = sub_repo.apply_update_by_dodo_id.call_args
        assert call_args.args[0] == "sub_failed"
        assert call_args.args[1].status == "failed"
        sub_repo.get_user_id_by_dodo_id.assert_awaited_once_with("sub_failed")
        deactivate.assert_awaited_once_with(USER_ID)
        assert result.event_type == DodoWebhookEventType.SUBSCRIPTION_FAILED.value
        assert result.status == "processed"
        assert result.message == "Subscription failed"
        assert result.subscription_id == "sub_failed"

    async def test_no_resolvable_user_never_calls_deactivate(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=None)

            await service._handle_subscription_failed(
                _event(DodoWebhookEventType.SUBSCRIPTION_FAILED)
            )

        deactivate.assert_not_awaited()

    async def test_missing_subscription_data_raises(self) -> None:
        service = PaymentWebhookService()
        event = MagicMock(spec=DodoWebhookEvent)
        event.get_subscription_data.return_value = None

        with pytest.raises(ValueError, match="Invalid subscription data"):
            await service._handle_subscription_failed(event)


@pytest.mark.unit
class TestSubscriptionOnHoldDeactivatesWorkflows:
    async def test_marks_the_subscription_on_hold_and_deactivates_workflows(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=USER_ID)

            result = await service._handle_subscription_on_hold(
                _event(DodoWebhookEventType.SUBSCRIPTION_ON_HOLD, subscription_id="sub_hold")
            )

        sub_repo.apply_update_by_dodo_id.assert_awaited_once()
        call_args = sub_repo.apply_update_by_dodo_id.call_args
        assert call_args.args[0] == "sub_hold"
        assert call_args.args[1].status == "on_hold"
        sub_repo.get_user_id_by_dodo_id.assert_awaited_once_with("sub_hold")
        deactivate.assert_awaited_once_with(USER_ID)
        assert result.event_type == DodoWebhookEventType.SUBSCRIPTION_ON_HOLD.value
        assert result.status == "processed"
        assert result.message == "Subscription on hold"
        assert result.subscription_id == "sub_hold"

    async def test_no_resolvable_user_never_calls_deactivate(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(f"{MODULE}.subscription_repository") as sub_repo,
            patch.object(
                service, "_deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
            ) as deactivate,
        ):
            sub_repo.apply_update_by_dodo_id = AsyncMock()
            sub_repo.get_user_id_by_dodo_id = AsyncMock(return_value=None)

            await service._handle_subscription_on_hold(
                _event(DodoWebhookEventType.SUBSCRIPTION_ON_HOLD)
            )

        deactivate.assert_not_awaited()

    async def test_missing_subscription_data_raises(self) -> None:
        service = PaymentWebhookService()
        event = MagicMock(spec=DodoWebhookEvent)
        event.get_subscription_data.return_value = None

        with pytest.raises(ValueError, match="Invalid subscription data"):
            await service._handle_subscription_on_hold(event)


@pytest.mark.unit
class TestDeactivateWorkflowsWrapperNeverRaises:
    """The private wrapper ``_deactivate_workflows_for_lapsed_subscription`` — a
    workflow-deactivation bug must not turn an otherwise-successful billing
    webhook into a Dodo retry."""

    async def test_delegates_to_the_free_function(self) -> None:
        service = PaymentWebhookService()
        with patch(
            f"{MODULE}.deactivate_workflows_for_lapsed_subscription", new_callable=AsyncMock
        ) as deactivate:
            await service._deactivate_workflows_for_lapsed_subscription(USER_ID)

        deactivate.assert_awaited_once_with(USER_ID)

    async def test_a_failure_is_swallowed_and_logged_with_exact_context(self) -> None:
        service = PaymentWebhookService()
        with (
            patch(
                f"{MODULE}.deactivate_workflows_for_lapsed_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await service._deactivate_workflows_for_lapsed_subscription(USER_ID)  # must not raise

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to deactivate workflows for lapsed subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


@pytest.mark.unit
class TestReactivateWorkflowsWrapperNeverRaises:
    """``reactivate_workflows_safely`` — same swallow-and-log posture as
    deactivation. Shared by the webhook and the verification reconciliation."""

    async def test_delegates_to_the_free_function(self) -> None:
        with patch(
            f"{PAUSE}.reactivate_workflows_for_restored_subscription", new_callable=AsyncMock
        ) as reactivate:
            await reactivate_workflows_safely(USER_ID)

        reactivate.assert_awaited_once_with(USER_ID)

    async def test_a_failure_is_swallowed_and_logged_with_exact_context(self) -> None:
        with (
            patch(
                f"{PAUSE}.reactivate_workflows_for_restored_subscription",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo exploded"),
            ),
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            await reactivate_workflows_safely(USER_ID)  # must not raise

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to reactivate workflows for restored subscription",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


@pytest.mark.unit
class TestSendWelcomeEmailSafely:
    """The new subscriber's welcome mail — same swallow-and-log posture as the
    workflow wrappers."""

    async def test_sends_to_the_looked_up_users_name_and_address(self) -> None:
        user = MagicMock(first_name="Alice", email="alice@example.com")
        with (
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(
                f"{ACTIVATION}.send_pro_subscription_email", new_callable=AsyncMock
            ) as send_email,
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            users.get = AsyncMock(return_value=user)
            await send_welcome_email_safely(USER_ID)

        users.get.assert_awaited_once_with(USER_ID)
        send_email.assert_awaited_once_with(user_name="Alice", user_email="alice@example.com")
        mock_log.info.assert_called_once_with(
            "[PAYMENT] Welcome email sent to", email="alice@example.com"
        )

    async def test_a_user_with_no_first_name_is_greeted_generically(self) -> None:
        with (
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(
                f"{ACTIVATION}.send_pro_subscription_email", new_callable=AsyncMock
            ) as send_email,
        ):
            users.get = AsyncMock(return_value=MagicMock(first_name=None, email="a@example.com"))
            await send_welcome_email_safely(USER_ID)

        assert send_email.await_args.kwargs["user_name"] == "User"

    async def test_a_user_without_an_email_is_never_mailed(self) -> None:
        with (
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(
                f"{ACTIVATION}.send_pro_subscription_email", new_callable=AsyncMock
            ) as send_email,
        ):
            users.get = AsyncMock(return_value=MagicMock(first_name="Alice", email=None))
            await send_welcome_email_safely(USER_ID)

        send_email.assert_not_awaited()

    async def test_a_failure_is_swallowed_and_logged_with_exact_context(self) -> None:
        with (
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            users.get = AsyncMock(side_effect=RuntimeError("mongo exploded"))
            await send_welcome_email_safely(USER_ID)  # must not raise

        mock_log.error.assert_called_once_with(
            "[PAYMENT] Failed to send welcome email",
            error="mongo exploded",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


@pytest.mark.unit
class TestResolveSubscriptionOwner:
    """Checkout stamps the GAIA user id into metadata; the customer email is the
    fallback for sessions minted before that."""

    async def test_metadata_user_id_wins_without_touching_the_user_repository(self) -> None:
        with patch(f"{ACTIVATION}.user_repository") as users:
            users.get_by_email = AsyncMock()
            owner = await resolve_subscription_owner(_subscription_data())

        assert owner == USER_ID
        users.get_by_email.assert_not_awaited()

    async def test_falls_back_to_the_customer_email_lookup(self) -> None:
        with patch(f"{ACTIVATION}.user_repository") as users:
            users.get_by_email = AsyncMock(return_value=MagicMock(id=USER_ID))
            owner = await resolve_subscription_owner(_subscription_data(metadata={}))

        users.get_by_email.assert_awaited_once_with("user@example.com")
        assert owner == USER_ID

    async def test_an_unknown_customer_email_belongs_to_nobody(self) -> None:
        with patch(f"{ACTIVATION}.user_repository") as users:
            users.get_by_email = AsyncMock(return_value=None)
            owner = await resolve_subscription_owner(_subscription_data(metadata={}))

        assert owner is None


@pytest.mark.unit
class TestActivateSubscription:
    """The single write path shared by the ``subscription.active`` webhook and
    payment verification's Dodo reconciliation."""

    async def test_writes_every_dodo_field_onto_the_new_row(self) -> None:
        sub_data = _subscription_data(
            next_billing_date="2026-02-01T00:00:00Z",
            previous_billing_date="2026-01-01T00:00:00Z",
        )
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.track_subscription_event"),
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION}.reactivate_workflows_safely", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            result = await activate_subscription(sub_data)

        sub_repo.get_by_dodo_id.assert_awaited_once_with("sub_123")
        created = sub_repo.create.await_args.args[0]
        assert created.dodo_subscription_id == "sub_123"
        assert created.user_id == USER_ID
        assert created.product_id == "prod_pro"
        assert created.status == "active"
        assert created.quantity == 1
        assert created.currency == "usd"
        assert created.recurring_pre_tax_amount == 2000
        assert created.payment_frequency_count == 1
        assert created.payment_frequency_interval == "Month"
        assert created.subscription_period_count == 1
        assert created.subscription_period_interval == "Month"
        assert created.next_billing_date == "2026-02-01T00:00:00Z"
        assert created.previous_billing_date == "2026-01-01T00:00:00Z"
        assert created.metadata == {"user_id": USER_ID}
        # One UTC-aware instant on both timestamps, never a naive local one.
        assert created.created_at is not None
        assert created.created_at.utcoffset() == timedelta(0)
        assert created.updated_at == created.created_at
        assert result == SubscriptionActivation(user_id=USER_ID, created=True)

    async def test_reports_the_priced_pro_plan_in_dollars_to_analytics(self) -> None:
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.track_subscription_event") as track,
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock) as welcome,
            patch(f"{ACTIVATION}.reactivate_workflows_safely", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            await activate_subscription(_subscription_data())

        assert track.call_args.kwargs["plan"] == SubscriptionPlan(
            name="Pro", amount=20.0, currency="usd"
        )
        welcome.assert_awaited_once_with(USER_ID)

    async def test_a_zero_amount_subscription_reports_no_price(self) -> None:
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.track_subscription_event") as track,
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION}.reactivate_workflows_safely", new_callable=AsyncMock),
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            await activate_subscription(_subscription_data(recurring_pre_tax_amount=0))

        assert track.call_args.kwargs["plan"].amount is None

    async def test_logs_the_activation_against_the_dodo_subscription_id(self) -> None:
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.track_subscription_event"),
            patch(f"{ACTIVATION}.send_welcome_email_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION}.reactivate_workflows_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            await activate_subscription(_subscription_data())

        mock_log.info.assert_called_once_with(
            "[PAYMENT] Subscription activated", subscription_id="sub_123"
        )

    async def test_an_already_recorded_subscription_is_not_rewritten(self) -> None:
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.reactivate_workflows_safely", new_callable=AsyncMock),
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=MagicMock(user_id=USER_ID))
            sub_repo.create = AsyncMock()
            result = await activate_subscription(_subscription_data())

        sub_repo.create.assert_not_awaited()
        assert result == SubscriptionActivation(user_id=USER_ID, created=False)
        mock_log.info.assert_called_once_with(
            "[PAYMENT] Subscription already exists", subscription_id="sub_123"
        )

    async def test_a_subscription_belonging_to_nobody_is_not_written(self) -> None:
        with (
            patch(f"{ACTIVATION}.subscription_repository") as sub_repo,
            patch(f"{ACTIVATION}.user_repository") as users,
            patch(f"{ACTIVATION}.log") as mock_log,
        ):
            sub_repo.get_by_dodo_id = AsyncMock(return_value=None)
            sub_repo.create = AsyncMock()
            users.get_by_email = AsyncMock(return_value=None)
            result = await activate_subscription(_subscription_data(metadata={}))

        sub_repo.create.assert_not_awaited()
        assert result == SubscriptionActivation(user_id=None, created=False)
        mock_log.error.assert_called_once_with(
            "[PAYMENT] User not found for subscription", subscription_id="sub_123"
        )
