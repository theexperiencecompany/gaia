"""``PaymentWebhookService`` — signature verification, the once-only claim,
and what each delivery is owed: acknowledge, retry, or give up.

The subscription state changes themselves are the reducer's
(``test_subscription_events.py``); these tests pin how a delivery reaches it
and what comes back.
"""

from datetime import UTC, datetime
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, patch

from dodopayments.types import WebhookEventType
from pydantic import ValidationError
import pytest

from app.constants.log_tags import LogTag
from app.constants.payments import WEBHOOK_ROW_WAIT_MAX
from app.models.payment_models import ProcessedWebhookUpdate, SubscriptionDocument
from app.models.webhook_models import (
    DodoWebhookEvent,
    DodoWebhookEventType,
    DodoWebhookProcessingResult,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.payments.payment_webhook_service import PaymentWebhookService
from app.services.payments.subscription_events import (
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    SubscriptionEventResult,
)
from tests.helpers import captured_wide_event
from tests.unit.services.conftest import (
    FAKE_EMAIL,
    FAKE_USER_ID,
    PAYMENT_DATA_PAYLOAD,
    SAMPLE_SUBSCRIPTION,
    SAMPLE_USER_DOC,
    SUBSCRIPTION_DATA_PAYLOAD,
    _make_webhook_event,
    _set_user,
)

MODULE = "app.services.payments.payment_webhook_service"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(**overrides: object) -> SubscriptionDocument:
    return SAMPLE_SUBSCRIPTION.model_copy(update=overrides)


# The reducer's side effects every webhook test wants kept in memory — opted
# in here rather than made autouse in the shared conftest, which every other
# unit/services test file also uses.
pytestmark = pytest.mark.usefixtures(
    "mock_activation_workflow_reactivation", "mock_subscription_plan_cache_drop"
)


# ============================================================================
# PaymentWebhookService — moved from test_payment_service.py
# ============================================================================


class TestVerifyWebhookSignature:
    """Tests for PaymentWebhookService.verify_webhook_signature."""

    def test_returns_false_when_no_verifier_configured(self) -> None:
        """When no verifier is configured, fail closed and reject the webhook."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "production"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None
        result = svc.verify_webhook_signature("{}", {})
        assert result is False

    def test_production_valid_signature(self):
        """In production with valid signature, returns True."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            result = svc.verify_webhook_signature(
                '{"type":"test"}',
                {
                    "webhook-id": "msg_abc",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,valid_sig",
                },
            )

        assert result is True
        mock_verifier.verify.assert_called_once()

    def test_production_invalid_signature_returns_false(self):
        """In production with invalid signature, returns False."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(side_effect=Exception("Invalid signature"))
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            result = svc.verify_webhook_signature(
                '{"type":"test"}',
                {
                    "webhook-id": "msg_abc",
                    "webhook-timestamp": "1234567890",
                    "webhook-signature": "v1,bad_sig",
                },
            )

        assert result is False

    def test_header_normalization(self):
        """Headers are normalized to lowercase-with-dashes format."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "whsec_test123"
            mock_settings.ENV = "production"
            with patch("app.services.payments.payment_webhook_service.Webhook") as mock_wh_cls:
                mock_verifier = MagicMock()
                mock_verifier.verify = MagicMock(return_value=None)
                mock_wh_cls.return_value = mock_verifier
                svc = PaymentWebhookService()

        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.ENV = "production"
            svc.verify_webhook_signature(
                '{"data":"test"}',
                {
                    "Webhook-Id": "msg_abc",
                    "Webhook-Timestamp": "1234567890",
                    "Webhook-Signature": "v1,sig",
                },
            )

        call_args = mock_verifier.verify.call_args
        headers_passed = call_args[0][1]
        assert "webhook-id" in headers_passed
        assert "webhook-timestamp" in headers_passed
        assert "webhook-signature" in headers_passed

    def test_verifier_init_failure_sets_verifier_to_none(self):
        """If Webhook() constructor fails, verifier is None."""
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = "bad_secret"
            mock_settings.ENV = "production"
            with patch(
                "app.services.payments.payment_webhook_service.Webhook",
                side_effect=Exception("Bad secret format"),
            ):
                svc = PaymentWebhookService()

        assert svc.webhook_verifier is None


class TestProcessWebhookIdempotency:
    """Tests for idempotency / deduplication in process_webhook."""

    async def test_already_processed_webhook_is_skipped(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """A delivery whose id is already claimed returns 'ignored' before any handler runs."""
        mock_processed_webhook_repository.claim = AsyncMock(return_value=False)

        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_dup")

        assert result.status == "ignored"
        assert result.message == "Webhook already processed"
        # The claim is on this delivery id, under the event type Dodo sent.
        mock_processed_webhook_repository.claim.assert_awaited_once_with(
            "wh_dup", event_type="payment.succeeded"
        )
        mock_processed_webhook_repository.record_outcome.assert_not_awaited()

    async def test_a_delivery_without_a_type_is_claimed_as_unknown(
        self, webhook_service, mock_processed_webhook_repository
    ):
        mock_processed_webhook_repository.claim = AsyncMock(return_value=False)

        result = await webhook_service.process_webhook({"data": {}}, "wh_typeless")

        assert result.event_type == "unknown"
        mock_processed_webhook_repository.claim.assert_awaited_once_with(
            "wh_typeless", event_type="unknown"
        )

    async def test_a_replayed_cancellation_deactivates_workflows_only_once(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """Dodo can redeliver the same webhook id. The idempotency check must stop
        the second delivery before it deactivates the user's workflows again."""
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        first = await webhook_service.process_webhook(event_data, "wh_cancel_replay")
        assert first.status == "processed"
        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)

        # Second delivery of the identical webhook id: the claim is taken.
        mock_processed_webhook_repository.claim = AsyncMock(return_value=False)
        second = await webhook_service.process_webhook(event_data, "wh_cancel_replay")

        assert second.status == "ignored"
        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)

    async def test_unknown_event_type_is_ignored_and_recorded(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """Unhandled event types are recorded to prevent re-processing."""
        event_data = {
            "business_id": "biz_001",
            "type": "payment.succeeded",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": PAYMENT_DATA_PAYLOAD,
        }
        # Simulate unknown event by removing the handler
        original_handlers = webhook_service.handlers.copy()
        webhook_service.handlers = {}

        result = await webhook_service.process_webhook(event_data, "wh_unknown")

        assert result.status == "ignored"
        assert "No handler" in result.message
        mock_processed_webhook_repository.record_outcome.assert_awaited_once_with(
            "wh_unknown",
            ProcessedWebhookUpdate(
                status="ignored", message=result.message, payment_id=None, subscription_id=None
            ),
        )
        webhook_service.handlers = original_handlers

    async def test_a_handled_delivery_records_the_handlers_full_outcome(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_cancel_outcome")

        assert result.status == "processed"
        mock_processed_webhook_repository.record_outcome.assert_awaited_once_with(
            "wh_cancel_outcome",
            ProcessedWebhookUpdate(
                status=result.status,
                message=result.message,
                payment_id=result.payment_id,
                subscription_id=result.subscription_id,
            ),
        )

    def test_the_recorded_outcome_carries_every_field_of_the_result(self):
        from app.services.payments.payment_webhook_service import _outcome_of

        result = DodoWebhookProcessingResult(
            event_type="payment.succeeded",
            status="processed",
            message="ok",
            payment_id="pay_1",
            subscription_id="sub_1",
        )

        assert _outcome_of(result) == ProcessedWebhookUpdate(
            status="processed", message="ok", payment_id="pay_1", subscription_id="sub_1"
        )

    async def test_every_event_type_dodo_can_send_parses(self) -> None:
        """Drift guard against the SDK: a real Dodo event outside our enum failed
        validation and was logged as a processing error (seen live with
        subscription.updated on 2026-09-06). The SDK's literal is the contract."""
        sdk_types = set(get_args(WebhookEventType))
        ours = {member.value for member in DodoWebhookEventType}
        assert ours == sdk_types

    async def test_an_event_we_do_not_act_on_is_ignored_not_failed(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """subscription.updated fires on every Dodo-side edit; we neither act on
        it nor treat it as an error, and it is recorded so a redelivery is a no-op."""
        event_data = _make_webhook_event("subscription.updated", {})
        result = await webhook_service.process_webhook(event_data, "wh_updated")
        assert result.status == "ignored"
        assert "No handler" in result.message
        mock_processed_webhook_repository.record_outcome.assert_awaited()

    async def test_an_envelope_that_does_not_validate_is_abandoned(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """An envelope missing its required fields is abandoned — it will not
        validate any better on a retry — and the claim is handed back so a
        corrected manual redelivery is not turned away as a replay."""
        bad_data = {"type": "payment.succeeded", "data": {}}
        with pytest.raises(ValidationError) as rejected:
            DodoWebhookEvent(**bad_data)

        async with captured_wide_event() as wide:
            result = await webhook_service.process_webhook(bad_data, "wh_bad")

        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_bad")
        mock_processed_webhook_repository.record_outcome.assert_not_awaited()

        assert result.status == "abandoned"
        assert result.message == f"Invalid payload: {rejected.value!s}"
        # The entry is the only record of why a delivery was given up on:
        # which one, and what the body was missing.
        assert wide["errors"] == [
            {
                "msg": f"{LogTag.PAYMENT} Webhook payload rejected; abandoning the delivery",
                "error": str(rejected.value),
                "error_type": "ValidationError",
                "webhook_id": "wh_bad",
            }
        ]


# ============================================================================
# Payment Event Handlers
# ============================================================================


class TestHandlePaymentSucceeded:
    """Tests for _handle_payment_succeeded via process_webhook."""

    async def test_processes_valid_payment_success(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_pay_001")

        assert result.status == "processed"
        assert result.payment_id == "pay_001"
        assert result.subscription_id == "sub_xyz789"
        assert "success" in result.message.lower()

    async def test_tracks_analytics_event(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_pay_002")

        # Every argument, not just the ids. Dodo bills in minor units, so the
        # money that reaches PostHog is a division this is the only test of:
        # turning it into a multiplication reports $999.00 for a $9.99 charge
        # and every revenue number downstream is wrong by 10,000x, with nothing
        # failing. The currency has to be asserted for the same reason — dropped
        # or blanked, the amount is a bare number and the dashboards silently
        # add dollars to rupees.
        mock_track_payment.assert_called_once_with(
            user_id=FAKE_USER_ID,
            event_type=AnalyticsEvents.PAYMENT_SUCCEEDED,
            payment_id="pay_001",
            amount=PAYMENT_DATA_PAYLOAD["total_amount"] / 100,
            currency=PAYMENT_DATA_PAYLOAD["currency"],
        )

    async def test_analytics_uses_metadata_user_id_without_db_lookup(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """The metadata user id is the PostHog distinct id — no user lookup."""
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": "unresolved-user-id"}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        await webhook_service.process_webhook(event_data, "wh_pay_003")

        mock_track_payment.assert_called_once()
        assert mock_track_payment.call_args[1]["user_id"] == "unresolved-user-id"

    async def test_no_analytics_when_no_user_id_in_metadata(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        await webhook_service.process_webhook(event_data, "wh_pay_004")

        mock_track_payment.assert_not_called()

    async def test_invalid_payment_data_is_abandoned(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        """Payment data that can't be parsed raises ValueError in the handler;
        process_webhook abandons the delivery rather than asking for a retry
        that would fail the same way."""
        bad_payload = {"incomplete": True}
        event_data = _make_webhook_event("payment.succeeded", bad_payload)

        result = await webhook_service.process_webhook(event_data, "wh_pay_bad")

        assert result.status == "abandoned"
        assert "Invalid payload" in result.message


class TestHandlePaymentFailed:
    """Tests for _handle_payment_failed."""

    async def test_processes_payment_failure(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.failed", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_fail_001")

        assert result.status == "processed"
        assert "failure" in result.message.lower()
        assert result.payment_id == "pay_001"

    async def test_tracks_failure_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        event_data = _make_webhook_event("payment.failed", PAYMENT_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_fail_002")

        mock_track_payment.assert_called_once()
        call_kwargs = mock_track_payment.call_args[1]
        assert call_kwargs["event_type"] == "payment:failed"


class TestHandlePaymentProcessing:
    """Tests for _handle_payment_processing."""

    async def test_processes_payment_processing_event(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        event_data = _make_webhook_event("payment.processing", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_proc_001")

        assert result.status == "processed"
        assert "processing" in result.message.lower()


class TestHandlePaymentCancelled:
    """Tests for _handle_payment_cancelled."""

    async def test_processes_payment_cancellation(
        self,
        webhook_service,
        mock_processed_webhook_repository,
    ):
        event_data = _make_webhook_event("payment.cancelled", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cancel_001")

        assert result.status == "processed"
        assert "cancellation" in result.message.lower()


# ============================================================================
# Subscription Event Handlers
# ============================================================================


class TestHandleSubscriptionActive:
    """``subscription.active`` through process_webhook: the one event that
    may create the row."""

    @pytest.fixture(autouse=True)
    def _no_row_yet(self, mock_webhook_subscription_repository):
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)

    async def test_creates_subscription_record(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sub_001")

        assert result.status == "processed"
        assert result.message == "Subscription activated"
        assert result.subscription_id == "sub_xyz789"
        mock_webhook_subscription_repository.create.assert_awaited_once()

    async def test_a_redelivery_for_the_recorded_state_writes_nothing(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(
                next_billing_date=SUBSCRIPTION_DATA_PAYLOAD["next_billing_date"],
                previous_billing_date=SUBSCRIPTION_DATA_PAYLOAD["previous_billing_date"],
            )
        )

        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sub_002")

        assert result.status == "processed"
        assert result.message == "Subscription already in this state"
        mock_webhook_subscription_repository.create.assert_not_awaited()
        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_not_awaited()

    async def test_finds_user_by_email_when_user_id_missing(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        """When metadata has no user_id, looks up user by customer email."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        _set_user(mock_webhook_users_collection, SAMPLE_USER_DOC)

        result = await webhook_service.process_webhook(event_data, "wh_sub_003")

        assert result.status == "processed"
        # No user_id in metadata → user is looked up by email through the repo.
        mock_webhook_users_collection.get_by_email.assert_awaited_with(FAKE_EMAIL)

    async def test_abandons_when_user_not_found_by_email(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """A subscription nobody owns cannot be activated by a retry either."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)
        _set_user(mock_webhook_users_collection, None)

        result = await webhook_service.process_webhook(event_data, "wh_sub_004")

        assert result.status == "abandoned"
        assert result.message == "User not found"

    async def test_sends_welcome_email(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        # For welcome email, _send_welcome_email does a separate find_one
        _set_user(mock_webhook_users_collection, SAMPLE_USER_DOC)

        await webhook_service.process_webhook(event_data, "wh_sub_005")

        mock_webhook_send_email.assert_awaited_once()

    async def test_tracks_analytics_on_activation(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_webhook_send_email,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_sub_006")

        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["event_type"] == "subscription:activated"

    async def test_insert_failure_raises(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
        mock_track_subscription,
    ):
        """If the repository create fails, the webhook returns a failed result."""
        mock_webhook_subscription_repository.create = AsyncMock(
            side_effect=Exception("insert failed")
        )
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_sub_007")

        assert result.status == "failed"
        assert "Processing error" in result.message

    @pytest.mark.usefixtures(
        "mock_processed_webhook_repository",
        "mock_webhook_subscription_repository",
        "mock_webhook_users_collection",
        "mock_webhook_send_email",
        "mock_track_subscription",
    )
    async def test_does_not_deactivate_workflows(
        self,
        webhook_service,
        mock_deactivate_workflows,
    ):
        """A user going Pro must never have their automation turned off."""
        event_data = _make_webhook_event("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_sub_008")

        mock_deactivate_workflows.assert_not_awaited()


class TestHandleSubscriptionRenewed:
    """Tests for _handle_subscription_renewed."""

    async def test_updates_billing_dates(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_renew_001")

        assert result.status == "processed"
        assert result.message == "Subscription renewed"
        mock_webhook_subscription_repository.apply_update_by_dodo_id.assert_awaited_once()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["next_billing_date"] == SUBSCRIPTION_DATA_PAYLOAD["next_billing_date"]
        assert (
            set_data["previous_billing_date"]
            == (SUBSCRIPTION_DATA_PAYLOAD["previous_billing_date"])
        )
        # The row was already active; only what changed is written.
        assert "status" not in set_data

    async def test_omitted_billing_dates_are_not_written_as_null(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """A renewal that omits the billing dates must leave the stored ones alone.

        Passing them to SubscriptionUpdate marks them in model_fields_set even
        when None, so the repository's model_dump(exclude_unset=True) emits
        ``next_billing_date: None`` and the $set overwrites good stored values
        with null.
        """
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(status="on_hold")
        )
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "next_billing_date": None,
            "previous_billing_date": None,
        }
        event_data = _make_webhook_event("subscription.renewed", payload)

        result = await webhook_service.process_webhook(event_data, "wh_renew_nulls")

        assert result.status == "processed"
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "active"
        assert "next_billing_date" not in set_data
        assert "previous_billing_date" not in set_data

    async def test_a_renewal_that_matched_no_row_is_not_reported_as_renewed(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        """Nothing was renewed, so nothing is captured — a renewal event for a
        subscription GAIA has no row for is a failure to mirror, not a renewal.
        ``TestAFailedHandlerReleasesItsClaim`` covers what that failure costs
        the delivery."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = _now_iso()

        result = await webhook_service.process_webhook(event_data, "wh_renew_002")

        assert result.status == "failed"
        mock_track_subscription.assert_not_called()

    async def test_tracks_renewal_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event_data, "wh_renew_003")

        # WHICH subscription was read: the owner comes off that row, so a lost
        # id would attribute the renewal to whatever a None lookup returns.
        mock_webhook_subscription_repository.get_by_dodo_id.assert_awaited_once_with("sub_xyz789")
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:renewed"
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["subscription_id"] == "sub_xyz789"


class TestHandleSubscriptionCancelled:
    """Tests for _handle_subscription_cancelled."""

    async def test_sets_status_to_cancelled(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cancel_sub_001")

        assert result.status == "processed"
        assert "cancelled" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "cancelled"

    async def test_includes_cancelled_at_when_present(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "cancelled_at": "2025-06-15T00:00:00Z",
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_002")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["cancelled_at"] == "2025-06-15T00:00:00Z"

    async def test_no_cancelled_at_when_absent(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "cancelled_at": None}
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_003")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert "cancelled_at" not in set_data

    async def test_tracks_cancellation_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_cancel_sub_004")

        mock_webhook_subscription_repository.get_by_dodo_id.assert_awaited_once_with("sub_xyz789")
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:cancelled"
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["properties"] == {
            "product_id": "prod_abc123",
            "billing_interval": "month",
        }

    async def test_scheduled_cancel_keeps_status_and_sets_flag(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """A cancel-at-next-billing-date keeps the subscription active and just
        records the flag — the user retains Pro access until the period ends."""
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "status": "active",
            "cancel_at_next_billing_date": True,
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_005")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        # Status is deliberately NOT in the update — only the flag records the
        # scheduled cancellation. A later `subscription.expired` flips status.
        assert "status" not in set_data
        assert set_data["cancel_at_next_billing_date"] is True

    async def test_scheduled_cancel_ignores_payload_status(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """Even if Dodo ever reported status "cancelled" in a scheduled-cancel
        payload, the user is not downgraded early — status stays untouched."""
        payload = {
            **SUBSCRIPTION_DATA_PAYLOAD,
            "status": "cancelled",
            "cancel_at_next_billing_date": True,
        }
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_006")

        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert "status" not in set_data
        assert set_data["cancel_at_next_billing_date"] is True

    async def test_immediate_cancel_deactivates_this_users_workflows(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """An immediate cancellation (no cancel_at_next_billing_date) drops the
        user from Pro right away, so their workflows must be turned off now."""
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_007")

        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)

    async def test_scheduled_cancel_does_not_deactivate_workflows(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """A cancel scheduled for period end keeps the user on Pro (and their
        workflows running) until `subscription.expired` actually fires."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "cancel_at_next_billing_date": True}
        event_data = _make_webhook_event("subscription.cancelled", payload)

        await webhook_service.process_webhook(event_data, "wh_cancel_sub_008")

        mock_deactivate_workflows.assert_not_awaited()

    async def test_deactivation_failure_does_not_fail_the_webhook(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """A broken workflow deactivation must not turn an otherwise-successful
        billing webhook into a "failed" result that Dodo would retry forever."""
        mock_deactivate_workflows.side_effect = RuntimeError("mongo down")
        event_data = _make_webhook_event("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_cancel_sub_009")

        assert result.status == "processed"


class TestHandleSubscriptionExpired:
    """Tests for _handle_subscription_expired."""

    async def test_sets_status_to_expired(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
    ):
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_expire_001")

        assert result.status == "processed"
        assert "expired" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "expired"

    async def test_tracks_expiry_analytics(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_expire_002")

        mock_webhook_subscription_repository.get_by_dodo_id.assert_awaited_once_with("sub_xyz789")
        mock_track_subscription.assert_called_once()
        call_kwargs = mock_track_subscription.call_args[1]
        assert call_kwargs["event_type"] == "subscription:expired"
        assert call_kwargs["user_id"] == FAKE_USER_ID

    async def test_deactivates_this_users_workflows(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_expire_003")

        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)

    async def test_no_row_means_no_deactivation_call(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_track_subscription,
        mock_deactivate_workflows,
    ):
        """No local subscription row matched the Dodo id: there is no user to
        resolve, so nothing is deactivated instead of raising on a None id."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        event_data = _make_webhook_event("subscription.expired", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event_data, "wh_expire_004")

        mock_deactivate_workflows.assert_not_awaited()


class TestHandleSubscriptionFailed:
    """Tests for _handle_subscription_failed."""

    async def test_sets_status_to_failed(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.failed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_sfail_001")

        assert result.status == "processed"
        assert "failed" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "failed"

    async def test_deactivates_this_users_workflows(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.failed", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_sfail_002")

        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)


class TestHandleSubscriptionOnHold:
    """Tests for _handle_subscription_on_hold."""

    async def test_sets_status_to_on_hold(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_hold_001")

        assert result.status == "processed"
        assert "on hold" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["status"] == "on_hold"

    async def test_deactivates_this_users_workflows(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_deactivate_workflows,
    ):
        event_data = _make_webhook_event("subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD)
        await webhook_service.process_webhook(event_data, "wh_hold_002")

        mock_deactivate_workflows.assert_awaited_once_with(FAKE_USER_ID)


class TestHandleSubscriptionPlanChanged:
    """Tests for _handle_subscription_plan_changed."""

    async def test_updates_product_and_amount(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ):
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            return_value=_row(product_id="prod_old", quantity=2, recurring_pre_tax_amount=1)
        )
        event_data = _make_webhook_event("subscription.plan_changed", SUBSCRIPTION_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_change_001")

        assert result.status == "processed"
        assert "plan changed" in result.message.lower()
        update_call = mock_webhook_subscription_repository.apply_update_by_dodo_id.call_args
        set_data = update_call.args[1].model_dump(exclude_unset=True)
        assert set_data["product_id"] == "prod_abc123"
        assert set_data["quantity"] == 1
        assert set_data["recurring_pre_tax_amount"] == 999


# ============================================================================
# Webhook Helper Methods
# ============================================================================


class TestGetUserIdFromMetadata:
    """Tests for _get_user_id_from_metadata."""

    async def test_returns_user_id_when_present(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({"user_id": FAKE_USER_ID})
        assert user_id == FAKE_USER_ID

    async def test_returns_none_when_no_user_id(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({})
        assert user_id is None

    async def test_stringifies_non_string_user_id(self, webhook_service):
        user_id = await webhook_service._get_user_id_from_metadata({"user_id": 12345})
        assert user_id == "12345"


# ============================================================================
# PaymentWebhookService Initialization Tests
# ============================================================================


class TestPaymentWebhookServiceInit:
    """Tests for PaymentWebhookService.__init__."""

    def test_no_secret_disables_verifier(self):
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_none_secret_disables_verifier(self):
        with patch("app.services.payments.payment_webhook_service.settings") as mock_settings:
            mock_settings.DODO_WEBHOOK_PAYMENTS_SECRET = None
            mock_settings.ENV = "development"
            svc = PaymentWebhookService()

        assert svc.webhook_verifier is None

    def test_every_handler_is_for_an_event_dodo_sends_and_the_acted_on_set_is_explicit(
        self, webhook_service
    ):
        """The enum is everything Dodo can send (drift-guarded against the SDK);
        the handlers are the subset GAIA acts on. Anything else is acknowledged
        and ignored, never a processing error."""
        assert set(webhook_service.handlers) <= set(DodoWebhookEventType)
        assert set(webhook_service.handlers) == {
            DodoWebhookEventType.PAYMENT_SUCCEEDED,
            DodoWebhookEventType.PAYMENT_FAILED,
            DodoWebhookEventType.PAYMENT_PROCESSING,
            DodoWebhookEventType.PAYMENT_CANCELLED,
            DodoWebhookEventType.SUBSCRIPTION_ACTIVE,
            DodoWebhookEventType.SUBSCRIPTION_RENEWED,
            DodoWebhookEventType.SUBSCRIPTION_CANCELLED,
            DodoWebhookEventType.SUBSCRIPTION_EXPIRED,
            DodoWebhookEventType.SUBSCRIPTION_FAILED,
            DodoWebhookEventType.SUBSCRIPTION_ON_HOLD,
            DodoWebhookEventType.SUBSCRIPTION_PLAN_CHANGED,
        }


class TestWebhookAccountSync:
    """process_webhook schedules a workspace account sync for the metadata user
    after an event is processed — and only then."""

    @pytest.fixture
    def mock_schedule_sync(self):
        with patch(
            "app.services.payments.payment_webhook_service.schedule_account_sync"
        ) as mock_fn:
            yield mock_fn

    async def test_processed_event_schedules_sync_for_the_metadata_user(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_sync_001")

        assert result.status == "processed"
        # The sync must target the user named in the payload's metadata.
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)

    async def test_failed_result_does_not_schedule_sync(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        """Only processed billing changes refresh the projection — a failed
        handler must not, even when the payload carries a user id."""
        failed = DodoWebhookProcessingResult(
            event_type=DodoWebhookEventType.PAYMENT_SUCCEEDED.value,
            status="failed",
            message="handler declined",
        )
        original_handlers = webhook_service.handlers.copy()
        webhook_service.handlers[DodoWebhookEventType.PAYMENT_SUCCEEDED] = AsyncMock(
            return_value=failed
        )
        try:
            event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
            result = await webhook_service.process_webhook(event_data, "wh_sync_002")
        finally:
            webhook_service.handlers = original_handlers

        assert result.status == "failed"
        mock_schedule_sync.assert_not_called()

    async def test_non_string_metadata_user_id_is_never_scheduled(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_track_payment,
        mock_schedule_sync,
    ):
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": 12345}}
        event_data = _make_webhook_event("payment.succeeded", payload)

        result = await webhook_service.process_webhook(event_data, "wh_sync_003")

        assert result.status == "processed"
        mock_schedule_sync.assert_not_called()


# ============================================================================
# The gaps that used to close silently
# ============================================================================


class TestASilentSkipIsOnTheRecord:
    """The payment's analytics id simply does nothing when it misses. A miss
    produced no event and no log — so the only visible symptom was a metric
    that looked healthy while a real payment went unrecorded."""

    async def test_a_payment_with_no_user_id_is_not_captured_anonymously(
        self,
        webhook_service,
        mock_track_payment,
    ):
        """Attributing it to anyone else would split the user's funnel in two,
        so it is not sent — and that gap is the thing worth logging."""
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {}}
        event = DodoWebhookEvent(**_make_webhook_event("payment.succeeded", payload))

        async with captured_wide_event() as wide:
            result = await webhook_service._handle_payment_succeeded(event)

        assert result.status == "processed"
        mock_track_payment.assert_not_called()
        assert wide["warnings"] == [
            {
                "msg": f"{LogTag.PAYMENT} Payment carries no GAIA user id; analytics not captured",
                "failure_reason": "unattributable_payment",
                "analytics_event": AnalyticsEvents.PAYMENT_SUCCEEDED.value,
                "payment_id": PAYMENT_DATA_PAYLOAD["payment_id"],
            }
        ]


# ============================================================================
# A failed handler is a state change still owed
# ============================================================================


class TestAFailedHandlerReleasesItsClaim:
    """The bug: ``record_outcome`` is an update, so a handler that *returned*
    ``failed`` (rather than raising) kept its webhook-id claim while the
    endpoint answered 200. Dodo does not resend a 200, and a manual redelivery
    of the same id is turned away at the claim — so a state change that never
    landed had no way left to be re-driven."""

    @pytest.mark.parametrize(
        "event_type",
        [
            "subscription.renewed",
            "subscription.cancelled",
            "subscription.expired",
            "subscription.failed",
            "subscription.on_hold",
            "subscription.plan_changed",
        ],
    )
    async def test_a_state_change_with_no_local_row_hands_the_claim_back(
        self,
        event_type: str,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_deactivate_workflows,
        webhook_side_effects_stubbed,
    ):
        """No row matched means Dodo's state was never mirrored. The row may
        still be on its way — ``subscription.active`` is a separate delivery
        with its own retries — so acknowledging drops the change for good and
        leaves the user on a tier they no longer have.

        Asserted down to the two error entries and every field of the result,
        not just ``status == "failed"``. Whoever picks this up in Grafana has
        only the wide event: which delivery, which subscription, and why it was
        handed back. Nineteen mutants lived in exactly those fields — blanking
        the reason to ``None``, dropping ``subscription_id`` from the log, or
        rewriting the message — because a status-only assertion cannot see any
        of it. Both entries land on one event: the handler reports the miss,
        then ``process_webhook`` records that it is releasing the claim.
        """
        webhook_id = f"wh_{event_type}_unmatched"
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        event_data = _make_webhook_event(event_type, SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = _now_iso()

        async with captured_wide_event() as wide:
            result = await webhook_service.process_webhook(event_data, webhook_id)

        assert result.status == "failed"
        assert result.event_type == event_type
        assert result.message == "Subscription not found"
        assert result.subscription_id == SUBSCRIPTION_DATA_PAYLOAD["subscription_id"]
        assert wide["errors"] == [
            {
                "msg": f"{LogTag.PAYMENT} No local subscription matched the Dodo id",
                "event_kind": event_type.removeprefix("subscription."),
                "subscription_id": SUBSCRIPTION_DATA_PAYLOAD["subscription_id"],
            },
            {
                "msg": f"{LogTag.PAYMENT} Webhook handler did not complete; releasing the claim",
                "webhook_id": webhook_id,
                "event_type": event_type,
                "failure_reason": "Subscription not found",
            },
        ]
        mock_processed_webhook_repository.release.assert_awaited_once_with(webhook_id)
        mock_processed_webhook_repository.record_outcome.assert_not_awaited()
        mock_deactivate_workflows.assert_not_awaited()


# ============================================================================
# process_webhook customer_id extraction
# ============================================================================


class TestProcessWebhookCustomerIdExtraction:
    """Verify customer_id is correctly extracted from nested and flat payloads."""

    async def test_extracts_customer_id_from_nested_customer_dict(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """customer_id is extracted from data.customer.customer_id."""
        event_data = _make_webhook_event("payment.succeeded", PAYMENT_DATA_PAYLOAD)
        result = await webhook_service.process_webhook(event_data, "wh_cid_001")

        assert result.status == "processed"

    async def test_extracts_customer_id_from_flat_payload(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_users_collection,
        mock_track_payment,
    ):
        """Falls back to data.customer_id when customer is not a dict."""
        payload = {
            **PAYMENT_DATA_PAYLOAD,
            "customer_id": "flat_cust_001",
        }
        # Replace customer with a non-dict to trigger fallback
        payload["customer"] = {
            "customer_id": "cust_001",
            "email": FAKE_EMAIL,
            "name": "Alice",
        }
        event_data = _make_webhook_event("payment.succeeded", payload)
        result = await webhook_service.process_webhook(event_data, "wh_cid_002")

        assert result.status == "processed"


# ============================================================================
# What a delivery is owed: retry, acknowledge, or give up
# ============================================================================


class TestTheHandlerHandsTheReducerTheEventAsDodoSentIt:
    async def test_the_reducer_receives_the_events_own_timestamp(
        self, webhook_service, mock_processed_webhook_repository
    ) -> None:
        """Ordering is by Dodo's clock; a handler stamping its own time would
        let a late redelivery look newer than the state it should not undo."""
        applied = SubscriptionEventResult(SubscriptionEventOutcome.APPLIED, FAKE_USER_ID)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = "2025-03-04T05:06:07Z"

        with patch(
            f"{MODULE}.apply_subscription_event", AsyncMock(return_value=applied)
        ) as apply_event:
            result = await webhook_service.process_webhook(event_data, "wh_stamped")

        event = apply_event.await_args.args[0]
        assert event.kind is SubscriptionEventKind.RENEWED
        assert event.occurred_at == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
        assert event.data.subscription_id == SUBSCRIPTION_DATA_PAYLOAD["subscription_id"]
        assert (result.status, result.message) == ("processed", "Subscription renewed")

    async def test_a_stale_event_is_acknowledged_as_ignored(
        self, webhook_service, mock_processed_webhook_repository
    ) -> None:
        stale = SubscriptionEventResult(SubscriptionEventOutcome.STALE, FAKE_USER_ID)
        event_data = _make_webhook_event("subscription.on_hold", SUBSCRIPTION_DATA_PAYLOAD)

        with patch(f"{MODULE}.apply_subscription_event", AsyncMock(return_value=stale)):
            result = await webhook_service.process_webhook(event_data, "wh_stale")

        assert (result.status, result.message) == ("ignored", "Stale event")
        assert result.subscription_id == SUBSCRIPTION_DATA_PAYLOAD["subscription_id"]
        mock_processed_webhook_repository.record_outcome.assert_awaited_once()
        mock_processed_webhook_repository.release.assert_not_awaited()


class TestAnUnlistedEventTypeIsAcknowledged:
    async def test_a_type_outside_the_enum_is_ignored_with_a_warning_not_failed(
        self, webhook_service, mock_processed_webhook_repository
    ) -> None:
        """Dodo adds event types without asking. The strict enum turned an
        unknown one into a validation error, the blanket handler into
        ``failed``, and the endpoint into a 503 — so Dodo redelivered an event
        GAIA would never act on, on every retry, until it gave up."""
        event_data = _make_webhook_event("subscription.brand_new_thing", {})

        async with captured_wide_event() as wide:
            result = await webhook_service.process_webhook(event_data, "wh_unlisted")

        assert result.status == "ignored"
        assert result.event_type == "subscription.brand_new_thing"
        mock_processed_webhook_repository.record_outcome.assert_awaited_once()
        mock_processed_webhook_repository.release.assert_not_awaited()
        assert wide["warnings"] == [
            {
                "msg": f"{LogTag.PAYMENT} Unlisted Dodo event type acknowledged and ignored",
                "event_type": "subscription.brand_new_thing",
                "webhook_id": "wh_unlisted",
            }
        ]


class TestAPermanentFailureIsAbandonedNotRetried:
    """``failed`` asks Dodo to redeliver, which only helps when a retry can
    succeed. An activation for a subscription no GAIA user owns, or a lifecycle
    event for a row that has had an hour to arrive and never did, fails the
    same way on every redelivery — so it is abandoned: acknowledged, claim
    released so a human can re-drive it, and on the wide event at error level."""

    async def test_an_ownerless_activation_is_abandoned(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
        mock_webhook_users_collection,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        mock_webhook_users_collection.get_by_email = AsyncMock(return_value=None)
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event_data = _make_webhook_event("subscription.active", payload)

        result = await webhook_service.process_webhook(event_data, "wh_active_nobody")

        assert result.status == "abandoned"
        assert result.message == "User not found"
        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_active_nobody")
        mock_processed_webhook_repository.record_outcome.assert_not_awaited()

    async def test_a_young_lifecycle_event_with_no_row_still_asks_for_a_retry(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ) -> None:
        """``subscription.active`` is its own delivery with its own retries;
        while it may still be on its way, the row-less renewal is owed one."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = _now_iso()

        result = await webhook_service.process_webhook(event_data, "wh_renew_young")

        assert result.status == "failed"
        assert result.message == "Subscription not found"
        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_renew_young")

    async def test_an_event_exactly_at_the_wait_limit_is_still_retried(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ) -> None:
        """The bound is "older than"; an event exactly one hour old still gets
        its retry — the boundary is where a one-character slip would abandon
        a delivery an hour early."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = (now - WEBHOOK_ROW_WAIT_MAX).strftime("%Y-%m-%dT%H:%M:%SZ")

        with patch(f"{MODULE}.datetime") as frozen:
            frozen.now.return_value = now
            result = await webhook_service.process_webhook(event_data, "wh_renew_edge")

        assert result.status == "failed"

    async def test_a_lifecycle_event_older_than_an_hour_with_no_row_is_abandoned(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ) -> None:
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(return_value=None)
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)
        event_data["timestamp"] = "2025-01-01T00:00:00Z"

        async with captured_wide_event() as wide:
            result = await webhook_service.process_webhook(event_data, "wh_renew_old")

        assert result.status == "abandoned"
        assert result.message == "Subscription not found"
        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_renew_old")
        assert wide["errors"] == [
            {
                "msg": f"{LogTag.PAYMENT} No local subscription matched the Dodo id",
                "event_kind": "renewed",
                "subscription_id": SUBSCRIPTION_DATA_PAYLOAD["subscription_id"],
            },
            {
                "msg": f"{LogTag.PAYMENT} Webhook abandoned; releasing the claim for manual redelivery",
                "webhook_id": "wh_renew_old",
                "event_type": "subscription.renewed",
                "failure_reason": "Subscription not found",
            },
        ]

    async def test_a_payload_that_does_not_validate_is_abandoned(
        self, webhook_service, mock_processed_webhook_repository
    ) -> None:
        """A body that fails validation fails validation on every retry."""
        event_data = _make_webhook_event("subscription.active", {"incomplete": True})

        result = await webhook_service.process_webhook(event_data, "wh_bad_body")

        assert result.status == "abandoned"
        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_bad_body")

    async def test_an_infrastructure_error_is_still_a_retry(
        self,
        webhook_service,
        mock_processed_webhook_repository,
        mock_webhook_subscription_repository,
    ) -> None:
        """Mongo being down is the one failure a retry does fix."""
        mock_webhook_subscription_repository.get_by_dodo_id = AsyncMock(
            side_effect=ConnectionError("mongo down")
        )
        event_data = _make_webhook_event("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event_data, "wh_mongo_down")

        assert result.status == "failed"
        mock_processed_webhook_repository.release.assert_awaited_once_with("wh_mongo_down")
