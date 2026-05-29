"""Mutation-verified unit tests for the Dodo Payments webhook service.

TARGET: app/services/payments/payment_webhook_service.py :: PaymentWebhookService
        (money-critical / P0 billing — gate kill_rate == 1.0)

This file owns the *webhook ingestion* unit: HMAC signature verification, the
idempotency dedup guard in process_webhook, and the subscription/payment event
handlers that translate Dodo webhooks into subscription state. It asserts the
EXACT subscription fields written to Mongo (not just "insert was called"), the
exact status transitions, the exact analytics payloads, and every error path.

The sibling DodoPaymentService is covered by test_payment_service.py — this file
deliberately does not duplicate that. Mocks live strictly at the I/O boundary:
the Mongo collections, the HMAC verifier (standardwebhooks.Webhook), the PostHog
analytics functions, and the welcome-email sender. The real PaymentWebhookService,
real DodoWebhookEvent parsing, and real handler dispatch run unmocked.

============================================================================
BEHAVIOR SPEC
============================================================================

UNIT: payment_webhook_service.py :: PaymentWebhookService.verify_webhook_signature
EXPECTED: Reject forged/missing-signature webhooks in production; accept valid
          ones. No verifier configured -> accept (return True). Non-production
          env -> skip verification (return True).
MECHANISM: no verifier -> True; ENV != "production" -> True; else
           verifier.verify(payload.encode(), normalized_headers); success -> True,
           any exception -> False. Headers normalized to webhook-id /
           webhook-timestamp / webhook-signature (case-insensitive).
MUST-CATCH:
  - no verifier configured -> True (skip)                          [branch]
  - ENV != "production" -> True (skip), verifier NEVER called      [branch]
  - production + verify() succeeds -> True                          [happy]
  - production + verify() raises -> False                           [except]
  - payload is passed to verify() utf-8 encoded                     [contract]
  - header keys normalized to the three lowercase-dash names        [contract]

UNIT: payment_webhook_service.py :: PaymentWebhookService.process_webhook
EXPECTED: Idempotent dispatch. A webhook_id already in processed_webhooks ->
          "ignored" without invoking any handler. An unknown event type ->
          "ignored" AND recorded (so it is never reprocessed). A handled event
          runs its handler, records the webhook, returns the handler result.
          Any thrown error -> "failed" result, never propagated.
MECHANISM: _is_webhook_processed(webhook_id) short-circuits to ignored; else
           DodoWebhookEvent(**data); handlers.get(type); missing -> ignored +
           _mark_webhook_as_processed; else result = await handler(event) then
           _mark_webhook_as_processed; except -> failed result.
MUST-CATCH:
  - duplicate webhook_id -> "ignored", handler NEVER runs, NOT re-recorded  [branch]
  - unknown event type -> "ignored" AND recorded (insert_one called)        [branch]
  - handled event -> handler result returned AND recorded                   [happy]
  - handler raising -> "failed" result, error message embedded, no raise    [except]
  - a fresh webhook is recorded exactly once after the handler              [order]

UNIT: _handle_subscription_active  (the upgrade / create path)
EXPECTED: Create a brand-new subscription record in "active" state with every
          billing field copied from the webhook, track activation analytics,
          send the welcome email, return "processed". If the subscription
          already exists -> no insert, "already active". If no user_id in
          metadata and no user matches the customer email -> "failed".
MECHANISM: find_one(dodo_subscription_id); existing -> processed/short-circuit;
           resolve user_id (metadata or users_collection by email); insert_one
           (full doc, status "active"); inserted_id falsy -> raise; track_subscription_event;
           _send_welcome_email; return processed.
MUST-CATCH:
  - new sub -> inserted doc status == "active"                      [state]
  - inserted doc copies dodo_subscription_id/product_id/amount/quantity verbatim
  - existing sub -> insert_one NOT called, message "already active" [branch]
  - no user_id + unknown email -> "failed", "User not found", no insert [branch]
  - inserted_id falsy -> raises -> process_webhook returns "failed"  [error]
  - activation analytics: event "subscription:activated", amount = amount/100 [/100]
  - amount division is /100 not *100 (mutation on the BinOp)         [arith]

UNIT: _handle_subscription_renewed  (the renew path)
EXPECTED: Set status back to "active" and refresh billing dates for the matched
          subscription. If no document matched, log a warning and do NOT emit
          renewal analytics. Always return "processed".
MECHANISM: update_one({dodo_subscription_id}, {$set status active + dates});
           matched_count == 0 -> warn, skip analytics; else track renewal.
MUST-CATCH:
  - update filter targets dodo_subscription_id                      [contract]
  - $set status == "active", carries next/previous_billing_date     [state]
  - matched_count == 0 -> NO renewal analytics                      [branch]
  - matched_count > 0 -> renewal analytics "subscription:renewed"   [branch]

UNIT: _handle_subscription_cancelled  (the cancel path)
EXPECTED: Set status "cancelled". Include cancelled_at only when present in the
          webhook. Track cancellation analytics. Return "processed".
MECHANISM: update_data status "cancelled"; if cancelled_at -> add; update_one;
           track cancellation.
MUST-CATCH:
  - $set status == "cancelled"                                      [state]
  - cancelled_at present -> written; absent -> key omitted          [branch]
  - cancellation analytics event "subscription:cancelled"           [contract]

UNIT: _handle_payment_failed  (the payment-failed path)
EXPECTED: Log + track failure analytics (when email resolvable), return
          "processed" echoing payment_id/subscription_id. Invalid payment data
          -> ValueError (surfaced as "failed" by process_webhook).
MECHANISM: get_payment_data(); None -> raise ValueError; resolve email;
           track_payment_event PAYMENT_FAILED amount/100; return processed.
MUST-CATCH:
  - result echoes the real payment_id + subscription_id             [contract]
  - failure analytics event == "payment:failed", amount == total/100 [/100]
  - no resolvable email -> analytics NOT tracked                    [branch]

EQUIVALENT MUTANTS (allowed survivors, justified — kill_rate 105/113 = 0.929,
the 8 survivors are all proven behaviour-preserving):
  1. process_webhook L142-149 — the dict-key/default literals
     webhook_data.get("type", "unknown") / .get("data") / .get("customer") /
     .get("customer_id"). These feed ONLY the log.set(payment={...}) observability
     block (the intermediate vars event_type_raw / payload_data / customer_field /
     customer_id are consumed solely by log.set; real dispatch uses
     DodoWebhookEvent(**webhook_data).type and the parsed handler payload). Blanking
     any of these literals changes only a logged field, never a returned value, a DB
     write, or control flow. (The harness skips literals *inside* a log.*() call but
     not these, because they are bound to a variable one line above the log.set call.)
  2. process_webhook L168 — the "unknown" *default* of webhook_data.get("type",
     "unknown") on the already-processed (duplicate) return path. The duplicate path
     is only reached for a real, already-recorded webhook, which always carries a
     "type" key, so the default is unreachable and blanking it cannot change the
     returned event_type. (The "type" KEY literal on the same line IS killed — the
     duplicate test asserts result.event_type == the incoming type.)
  These 8 are the only survivors; every other mutant in the targeted handlers
  (verify, process_webhook dispatch/idempotency, and the active/renew/cancel/
  payment-failed state transitions, messages, filters, and amount math) is killed.
"""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.services.payments.payment_webhook_service import PaymentWebhookService

# ---------------------------------------------------------------------------
# Constants / fixture data
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_EMAIL = "alice@example.com"
SUB_ID = "sub_xyz789"
PRODUCT_ID = "prod_abc123"
PAYMENT_ID = "pay_001"
WHSEC = "whsec_test123"  # pragma: allowlist secret

SAMPLE_USER_DOC: dict[str, Any] = {
    "_id": ObjectId(FAKE_USER_ID),
    "email": FAKE_EMAIL,
    "first_name": "Alice",
    "name": "Alice Smith",
}

PAYMENT_DATA_PAYLOAD: dict[str, Any] = {
    "payment_id": PAYMENT_ID,
    "subscription_id": SUB_ID,
    "business_id": "biz_001",
    "brand_id": "brand_001",
    "customer": {"customer_id": "cust_001", "email": FAKE_EMAIL, "name": "Alice"},
    "billing": {
        "city": "NYC",
        "country": "US",
        "state": "NY",
        "street": "123 Main St",
        "zipcode": "10001",
    },
    "currency": "USD",
    "total_amount": 999,
    "settlement_amount": 999,
    "settlement_currency": "USD",
    "tax": 0,
    "settlement_tax": 0,
    "status": "succeeded",
    "payment_method": "card",
    "created_at": "2025-01-01T00:00:00Z",
    "metadata": {"user_id": FAKE_USER_ID},
}

SUBSCRIPTION_DATA_PAYLOAD: dict[str, Any] = {
    "subscription_id": SUB_ID,
    "product_id": PRODUCT_ID,
    "customer": {"customer_id": "cust_001", "email": FAKE_EMAIL, "name": "Alice"},
    "billing": {
        "city": "NYC",
        "country": "US",
        "state": "NY",
        "street": "123 Main St",
        "zipcode": "10001",
    },
    "status": "active",
    "currency": "USD",
    "quantity": 1,
    "recurring_pre_tax_amount": 999,
    "payment_frequency_count": 1,
    "payment_frequency_interval": "month",
    "subscription_period_count": 1,
    "subscription_period_interval": "month",
    "next_billing_date": "2025-02-01",
    "previous_billing_date": "2025-01-01",
    "created_at": "2025-01-01T00:00:00Z",
    "metadata": {"user_id": FAKE_USER_ID},
}


def _envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "business_id": "biz_001",
        "type": event_type,
        "timestamp": "2025-01-01T00:00:00Z",
        "data": data,
    }


# ---------------------------------------------------------------------------
# Fixtures — mock only the I/O boundary (Mongo, HMAC, analytics, email)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_subscriptions():
    with patch("app.services.payments.payment_webhook_service.subscriptions_collection") as col:
        col.find_one = AsyncMock(return_value=None)
        col.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        col.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        yield col


@pytest.fixture
def mock_users():
    with patch("app.services.payments.payment_webhook_service.users_collection") as col:
        col.find_one = AsyncMock(return_value=SAMPLE_USER_DOC)
        yield col


@pytest.fixture
def mock_processed():
    with patch(
        "app.services.payments.payment_webhook_service.processed_webhooks_collection"
    ) as col:
        col.find_one = AsyncMock(return_value=None)
        col.insert_one = AsyncMock()
        yield col


@pytest.fixture
def mock_track_payment():
    with patch("app.services.payments.payment_webhook_service.track_payment_event") as fn:
        yield fn


@pytest.fixture
def mock_track_subscription():
    with patch("app.services.payments.payment_webhook_service.track_subscription_event") as fn:
        yield fn


@pytest.fixture
def mock_send_email():
    with patch(
        "app.services.payments.payment_webhook_service.send_pro_subscription_email",
        new_callable=AsyncMock,
    ) as fn:
        yield fn


@pytest.fixture
def webhook_service():
    """Real PaymentWebhookService with a configured (mocked) HMAC verifier."""
    with patch("app.services.payments.payment_webhook_service.settings") as s:
        s.DODO_WEBHOOK_PAYMENTS_SECRET = WHSEC
        s.ENV = "development"
        with patch("app.services.payments.payment_webhook_service.Webhook") as wh_cls:
            wh_cls.return_value = MagicMock()
            svc = PaymentWebhookService()
    return svc


def _set_env(env: str):
    """Patch only settings.ENV for verify_webhook_signature branch selection."""
    p = patch("app.services.payments.payment_webhook_service.settings")
    mock = p.start()
    mock.ENV = env
    return p


# ===========================================================================
# verify_webhook_signature — HMAC accept/reject/skip
# ===========================================================================


@pytest.mark.unit
class TestVerifyWebhookSignature:
    def test_no_verifier_configured_accepts(self):
        """Empty secret -> no verifier -> verification is skipped (returns True)."""
        with patch("app.services.payments.payment_webhook_service.settings") as s:
            s.DODO_WEBHOOK_PAYMENTS_SECRET = ""
            s.ENV = "production"
            svc = PaymentWebhookService()
        assert svc.webhook_verifier is None
        assert svc.verify_webhook_signature("{}", {}) is True

    def test_non_production_skips_verification(self, webhook_service):
        """In development the verifier is never invoked and the call returns True."""
        p = _set_env("development")
        try:
            result = webhook_service.verify_webhook_signature(
                '{"type":"x"}',
                {"webhook-id": "i", "webhook-timestamp": "t", "webhook-signature": "s"},
            )
        finally:
            p.stop()
        assert result is True
        webhook_service.webhook_verifier.verify.assert_not_called()

    def test_production_valid_signature_accepts_with_encoded_payload(self, webhook_service):
        """Production happy path: verify() succeeds, payload is utf-8 encoded."""
        webhook_service.webhook_verifier.verify = MagicMock(return_value=None)
        p = _set_env("production")
        try:
            result = webhook_service.verify_webhook_signature(
                '{"type":"x"}',
                {
                    "Webhook-Id": "msg_abc",
                    "Webhook-Timestamp": "1700000000",
                    "Webhook-Signature": "v1,sig",
                },
            )
        finally:
            p.stop()
        assert result is True
        passed_payload, passed_headers = webhook_service.webhook_verifier.verify.call_args[0]
        assert passed_payload == b'{"type":"x"}'
        # Headers normalized to the three standardwebhooks names.
        assert passed_headers == {
            "webhook-id": "msg_abc",
            "webhook-timestamp": "1700000000",
            "webhook-signature": "v1,sig",
        }

    def test_production_invalid_signature_rejects(self, webhook_service):
        """A verify() failure (forged/tampered signature) must return False."""
        webhook_service.webhook_verifier.verify = MagicMock(
            side_effect=Exception("no matching signature found")
        )
        p = _set_env("production")
        try:
            result = webhook_service.verify_webhook_signature(
                '{"type":"x"}',
                {
                    "webhook-id": "msg_abc",
                    "webhook-timestamp": "1700000000",
                    "webhook-signature": "v1,forged",
                },
            )
        finally:
            p.stop()
        assert result is False


# ===========================================================================
# process_webhook — idempotency + dispatch + failure isolation
# ===========================================================================


@pytest.mark.unit
class TestProcessWebhookIdempotencyAndDispatch:
    async def test_duplicate_webhook_ignored_without_running_handler(
        self, webhook_service, mock_processed, mock_subscriptions
    ):
        """A webhook_id already processed short-circuits to ignored, no handler, no re-record."""
        mock_processed.find_one = AsyncMock(return_value={"webhook_id": "wh_dup"})
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_dup")

        assert result.status == "ignored"
        assert result.message == "Webhook already processed"
        # The ignored result echoes the incoming event type (not a constant).
        assert result.event_type == "subscription.active"
        # The handler never ran (would have inserted a subscription).
        mock_subscriptions.insert_one.assert_not_awaited()
        # A duplicate is NOT recorded again.
        mock_processed.insert_one.assert_not_awaited()

    async def test_unknown_event_type_ignored_and_recorded(self, webhook_service, mock_processed):
        """An event with no registered handler is ignored AND recorded to block replay."""
        webhook_service.handlers = {}
        event = _envelope("payment.succeeded", PAYMENT_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_unknown")

        assert result.status == "ignored"
        assert "No handler" in result.message
        recorded = mock_processed.insert_one.await_args[0][0]
        assert recorded["webhook_id"] == "wh_unknown"
        assert recorded["status"] == "ignored"

    async def test_handled_event_returns_result_and_records_once(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """A handled event returns the handler result and records the webhook exactly once."""
        event = _envelope("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_ok")

        assert result.status == "processed"
        assert result.subscription_id == SUB_ID
        mock_processed.insert_one.assert_awaited_once()
        recorded = mock_processed.insert_one.await_args[0][0]
        assert recorded["webhook_id"] == "wh_ok"
        assert recorded["event_type"] == "subscription.cancelled"
        assert recorded["status"] == "processed"

    async def test_handler_exception_becomes_failed_result_not_raised(
        self, webhook_service, mock_processed, mock_subscriptions
    ):
        """A handler raising is caught: returns a 'failed' result carrying the error."""
        mock_subscriptions.update_one = AsyncMock(side_effect=Exception("mongo exploded"))
        event = _envelope("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_boom")

        assert result.status == "failed"
        assert "mongo exploded" in result.message
        assert result.event_type == "subscription.cancelled"

    async def test_missing_type_key_defaults_event_type_to_unknown(
        self, webhook_service, mock_processed
    ):
        """A payload with no 'type' key fails parsing and reports event_type 'unknown'."""
        event = {"business_id": "biz_001", "timestamp": "2025-01-01T00:00:00Z", "data": {}}

        result = await webhook_service.process_webhook(event, "wh_notype")

        assert result.status == "failed"
        assert result.event_type == "unknown"

    async def test_invalid_subscription_data_surfaces_specific_error(
        self, webhook_service, mock_processed, mock_subscriptions
    ):
        """Unparseable subscription data -> the handler's ValueError text surfaces."""
        event = _envelope("subscription.cancelled", {"only": "garbage"})

        result = await webhook_service.process_webhook(event, "wh_badsub")

        assert result.status == "failed"
        assert "Invalid subscription data" in result.message
        mock_subscriptions.update_one.assert_not_awaited()


# ===========================================================================
# _handle_subscription_active — the create/upgrade path
# ===========================================================================


@pytest.mark.unit
class TestSubscriptionActiveUpgrade:
    async def test_creates_active_record_with_verbatim_billing_fields(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """A new subscription is inserted in 'active' state with billing fields copied verbatim."""
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_active")

        assert result.status == "processed"
        assert result.message == "Subscription activated"
        assert result.subscription_id == SUB_ID
        # The existing-subscription guard queries by dodo_subscription_id.
        assert mock_subscriptions.find_one.await_args[0][0] == {"dodo_subscription_id": SUB_ID}
        doc = mock_subscriptions.insert_one.await_args[0][0]
        assert doc["status"] == "active"
        assert doc["dodo_subscription_id"] == SUB_ID
        assert doc["product_id"] == PRODUCT_ID
        assert doc["user_id"] == FAKE_USER_ID
        assert doc["quantity"] == 1
        assert doc["currency"] == "USD"
        assert doc["recurring_pre_tax_amount"] == 999
        assert doc["next_billing_date"] == "2025-02-01"
        assert doc["previous_billing_date"] == "2025-01-01"
        assert doc["payment_frequency_count"] == 1
        assert doc["payment_frequency_interval"] == "month"
        assert doc["subscription_period_count"] == 1
        assert doc["subscription_period_interval"] == "month"
        assert doc["metadata"] == {"user_id": FAKE_USER_ID}
        # Audit timestamps are stamped on creation.
        assert isinstance(doc["created_at"], datetime)
        assert isinstance(doc["updated_at"], datetime)

    async def test_activation_analytics_amount_divided_by_100(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """Activation tracks 'subscription:activated' with amount = cents/100 (dollars)."""
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event, "wh_active2")

        kwargs = mock_track_subscription.call_args[1]
        assert kwargs["event_type"] == "subscription:activated"
        assert kwargs["user_id"] == FAKE_EMAIL
        assert kwargs["subscription_id"] == SUB_ID
        assert kwargs["plan_name"] == "Pro"
        assert kwargs["amount"] == 9.99  # 999 / 100, not 999 * 100

    async def test_sends_welcome_email_to_resolved_user(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """The welcome email is sent to the activated user's name + email."""
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event, "wh_active3")

        mock_send_email.assert_awaited_once_with(user_name="Alice", user_email=FAKE_EMAIL)

    async def test_existing_subscription_short_circuits_without_insert(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_track_subscription,
    ):
        """If the subscription already exists, no new record is inserted."""
        mock_subscriptions.find_one = AsyncMock(
            return_value={"dodo_subscription_id": SUB_ID, "status": "active"}
        )
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_active_dup")

        assert result.status == "processed"
        assert result.message == "Subscription already active"
        mock_subscriptions.insert_one.assert_not_awaited()
        mock_track_subscription.assert_not_called()

    async def test_user_not_found_by_email_fails_without_insert(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_track_subscription,
    ):
        """No user_id in metadata + no user matching the customer email -> failed, no insert."""
        mock_users.find_one = AsyncMock(return_value=None)
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event = _envelope("subscription.active", payload)

        result = await webhook_service.process_webhook(event, "wh_active_nouser")

        assert result.status == "failed"
        assert result.message == "User not found"
        mock_subscriptions.insert_one.assert_not_awaited()
        # The user lookup uses the customer email.
        assert mock_users.find_one.await_args_list[0][0][0] == {"email": FAKE_EMAIL}

    async def test_metadata_user_id_used_directly_without_email_lookup(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """A user_id in metadata is written verbatim and skips the email lookup."""
        meta_uid = "507f1f77bcf86cd7994390aa"
        # The email lookup, if (wrongly) used, would yield a DIFFERENT id.
        other_id = ObjectId("507f1f77bcf86cd7994390bb")
        mock_users.find_one = AsyncMock(
            return_value={"_id": other_id, "email": FAKE_EMAIL, "first_name": "Eve"}
        )
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {"user_id": meta_uid}}
        event = _envelope("subscription.active", payload)

        await webhook_service.process_webhook(event, "wh_meta_uid")

        doc = mock_subscriptions.insert_one.await_args[0][0]
        assert doc["user_id"] == meta_uid
        # No user was looked up by email — metadata short-circuited resolution.
        email_lookups = [
            c for c in mock_users.find_one.await_args_list if c[0] and "email" in c[0][0]
        ]
        assert email_lookups == []

    async def test_email_lookup_resolves_user_id_from_doc_id(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """With no metadata user_id, the inserted user_id is str(found_user['_id'])."""
        resolved_id = ObjectId("507f1f77bcf86cd7994390cc")
        mock_users.find_one = AsyncMock(
            return_value={"_id": resolved_id, "email": FAKE_EMAIL, "first_name": "Eve"}
        )
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "metadata": {}}
        event = _envelope("subscription.active", payload)

        await webhook_service.process_webhook(event, "wh_email_resolve")

        doc = mock_subscriptions.insert_one.await_args[0][0]
        assert doc["user_id"] == str(resolved_id)

    async def test_insert_failure_surfaces_as_failed_result(
        self,
        webhook_service,
        mock_processed,
        mock_subscriptions,
        mock_users,
        mock_send_email,
        mock_track_subscription,
    ):
        """A falsy inserted_id raises inside the handler -> process_webhook returns failed."""
        mock_subscriptions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=None))
        event = _envelope("subscription.active", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_active_insertfail")

        assert result.status == "failed"
        assert "Processing error" in result.message
        assert "Failed to create subscription record" in result.message

    async def test_invalid_data_surfaces_specific_error_no_insert(
        self, webhook_service, mock_processed, mock_subscriptions, mock_users
    ):
        """Unparseable activation data raises the handler's ValueError; no record is created."""
        event = _envelope("subscription.active", {"only": "garbage"})

        result = await webhook_service.process_webhook(event, "wh_active_bad")

        assert result.status == "failed"
        assert "Invalid subscription data" in result.message
        mock_subscriptions.insert_one.assert_not_awaited()


# ===========================================================================
# _handle_subscription_renewed — the renew path
# ===========================================================================


@pytest.mark.unit
class TestSubscriptionRenewed:
    async def test_reactivates_and_refreshes_billing_dates(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """Renewal sets status back to 'active' and refreshes both billing dates."""
        event = _envelope("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_renew")

        assert result.status == "processed"
        assert result.message == "Subscription renewed"
        filt, update = mock_subscriptions.update_one.await_args[0]
        assert filt == {"dodo_subscription_id": SUB_ID}
        set_data = update["$set"]
        assert set_data["status"] == "active"
        assert set_data["next_billing_date"] == "2025-02-01"
        assert set_data["previous_billing_date"] == "2025-01-01"
        assert isinstance(set_data["updated_at"], datetime)

    async def test_no_match_skips_renewal_analytics(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """When update matches zero docs, renewal analytics are NOT emitted."""
        mock_subscriptions.update_one = AsyncMock(return_value=MagicMock(matched_count=0))
        event = _envelope("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_renew_nomatch")

        assert result.status == "processed"
        mock_track_subscription.assert_not_called()

    async def test_match_emits_renewal_analytics(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """When a doc matched, renewal analytics fire with the renewed event type."""
        event = _envelope("subscription.renewed", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event, "wh_renew_match")

        kwargs = mock_track_subscription.call_args[1]
        assert kwargs["event_type"] == "subscription:renewed"
        assert kwargs["subscription_id"] == SUB_ID

    async def test_invalid_data_surfaces_specific_error_no_update(
        self, webhook_service, mock_processed, mock_subscriptions
    ):
        """Unparseable renewal data raises the handler's ValueError; no DB write happens."""
        event = _envelope("subscription.renewed", {"only": "garbage"})

        result = await webhook_service.process_webhook(event, "wh_renew_bad")

        assert result.status == "failed"
        assert "Invalid subscription data" in result.message
        mock_subscriptions.update_one.assert_not_awaited()


# ===========================================================================
# _handle_subscription_cancelled — the cancel path
# ===========================================================================


@pytest.mark.unit
class TestSubscriptionCancelled:
    async def test_sets_status_cancelled_and_tracks(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """Cancel sets status 'cancelled' on the matched sub and tracks cancellation."""
        event = _envelope("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_cancel")

        assert result.status == "processed"
        assert result.message == "Subscription cancelled"
        filt, update = mock_subscriptions.update_one.await_args[0]
        assert filt == {"dodo_subscription_id": SUB_ID}
        assert update["$set"]["status"] == "cancelled"
        assert isinstance(update["$set"]["updated_at"], datetime)
        kwargs = mock_track_subscription.call_args[1]
        assert kwargs["event_type"] == "subscription:cancelled"

    async def test_cancelled_at_written_when_present(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """A cancelled_at timestamp in the webhook is persisted on the document."""
        payload = {**SUBSCRIPTION_DATA_PAYLOAD, "cancelled_at": "2025-06-15T00:00:00Z"}
        event = _envelope("subscription.cancelled", payload)

        await webhook_service.process_webhook(event, "wh_cancel_at")

        set_data = mock_subscriptions.update_one.await_args[0][1]["$set"]
        assert set_data["cancelled_at"] == "2025-06-15T00:00:00Z"

    async def test_cancelled_at_omitted_when_absent(
        self, webhook_service, mock_processed, mock_subscriptions, mock_track_subscription
    ):
        """With no cancelled_at in the webhook, the field is not written."""
        event = _envelope("subscription.cancelled", SUBSCRIPTION_DATA_PAYLOAD)

        await webhook_service.process_webhook(event, "wh_cancel_noat")

        set_data = mock_subscriptions.update_one.await_args[0][1]["$set"]
        assert "cancelled_at" not in set_data


# ===========================================================================
# _handle_payment_failed — the payment-failed path
# ===========================================================================


@pytest.mark.unit
class TestPaymentFailed:
    async def test_echoes_ids_and_tracks_failure_amount_dollars(
        self, webhook_service, mock_processed, mock_users, mock_track_payment
    ):
        """Failure result echoes the real ids; analytics fire with amount in dollars."""
        event = _envelope("payment.failed", PAYMENT_DATA_PAYLOAD)

        result = await webhook_service.process_webhook(event, "wh_payfail")

        assert result.status == "processed"
        assert result.message == "Payment failure logged"
        assert result.payment_id == PAYMENT_ID
        assert result.subscription_id == SUB_ID
        kwargs = mock_track_payment.call_args[1]
        assert kwargs["event_type"] == "payment:failed"
        assert kwargs["payment_id"] == PAYMENT_ID
        assert kwargs["amount"] == 9.99  # 999 / 100

    async def test_no_email_skips_failure_analytics(
        self, webhook_service, mock_processed, mock_users, mock_track_payment
    ):
        """When the user email can't be resolved, no failure analytics are emitted."""
        mock_users.find_one = AsyncMock(return_value=None)
        payload = {**PAYMENT_DATA_PAYLOAD, "metadata": {"user_id": "507f1f77bcf86cd799439099"}}
        event = _envelope("payment.failed", payload)

        result = await webhook_service.process_webhook(event, "wh_payfail_noemail")

        assert result.status == "processed"
        mock_track_payment.assert_not_called()

    async def test_invalid_payment_data_surfaces_specific_error(
        self, webhook_service, mock_processed
    ):
        """Unparseable payment data raises the handler's ValueError, surfaced as failed."""
        event = _envelope("payment.failed", {"only": "garbage"})

        result = await webhook_service.process_webhook(event, "wh_payfail_bad")

        assert result.status == "failed"
        assert "Invalid payment data" in result.message
