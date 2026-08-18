"""Unit tests for ``app.services.payments.payment_webhook_service`` — the
identity-binding paths of subscription activation and metadata lookups."""

from unittest.mock import AsyncMock, patch

from app.models.webhook_models import (
    DodoBillingData,
    DodoCustomerData,
    DodoSubscriptionData,
    DodoWebhookEvent,
    DodoWebhookEventType,
)
from app.services.payments.payment_webhook_service import PaymentWebhookService

USER_ID = "507f1f77bcf86cd799439011"


def _sub_data(**overrides: object) -> DodoSubscriptionData:
    defaults: dict[str, object] = {
        "subscription_id": "sub_1",
        "product_id": "prod_1",
        "customer": DodoCustomerData(customer_id="cus_1", email="alice@example.com", name="Alice"),
        "billing": DodoBillingData(
            city="SF", country="US", state="CA", street="1 Main", zipcode="94101"
        ),
        "status": "active",
        "currency": "USD",
        "quantity": 1,
        "recurring_pre_tax_amount": 2900,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "month",
        "subscription_period_count": 1,
        "subscription_period_interval": "month",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"user_id": USER_ID},
    }
    defaults.update(overrides)
    return DodoSubscriptionData.model_validate(defaults)


def _event(data: dict[str, object]) -> DodoWebhookEvent:
    return DodoWebhookEvent(
        business_id="biz_1",
        type=DodoWebhookEventType.SUBSCRIPTION_ACTIVE,
        timestamp="2026-01-01T00:00:00Z",
        data=data,
    )


class TestGetUserEmailFromMetadata:
    async def test_present_user_id_is_looked_up_verbatim(self) -> None:
        """The checkout-set metadata id is the lookup key."""
        service = PaymentWebhookService()

        class _User:
            email = "alice@example.com"

        user = _User()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=user,
        ) as mock_get:
            email = await service._get_user_email_from_metadata({"user_id": USER_ID})

        assert email == "alice@example.com"
        mock_get.assert_awaited_once_with(USER_ID)

    async def test_a_numeric_round_tripped_id_is_coerced_before_lookup(self) -> None:
        """Checkout writes str(user_id), but Dodo echoes provider-side JSON —
        a numeric echo must still hit the string-keyed repository."""
        service = PaymentWebhookService()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get:
            await service._get_user_email_from_metadata({"user_id": 12345})

        mock_get.assert_awaited_once_with("12345")

    async def test_an_unknown_user_id_yields_no_email(self) -> None:
        """A lookup miss returns None rather than raising or inventing an address."""
        service = PaymentWebhookService()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get:
            email = await service._get_user_email_from_metadata({"user_id": USER_ID})

        assert email is None
        mock_get.assert_awaited_once_with(USER_ID)

    async def test_missing_user_id_skips_lookup(self) -> None:
        service = PaymentWebhookService()
        with patch(
            "app.services.payments.payment_webhook_service.user_repository.get",
            new_callable=AsyncMock,
        ) as mock_get:
            email = await service._get_user_email_from_metadata({})

        assert email is None
        mock_get.assert_not_awaited()


class TestHandleSubscriptionActive:
    async def test_metadata_user_id_binds_without_an_email_lookup(self) -> None:
        """Metadata is the identity source — the subscription binds to it and
        never to whoever happens to own the customer email."""
        service = PaymentWebhookService()
        sub = _sub_data()
        event = _event(sub.model_dump())

        with (
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.create",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.services.payments.payment_webhook_service.user_repository.get_by_email",
                new_callable=AsyncMock,
            ) as mock_by_email,
            patch.object(service, "_send_welcome_email", new_callable=AsyncMock),
            patch("app.services.payments.payment_webhook_service.track_subscription_event"),
        ):
            result = await service._handle_subscription_active(event)

        assert result.status == "processed"
        mock_by_email.assert_not_awaited()
        created = mock_create.await_args.args[0]
        assert created.user_id == USER_ID

    async def test_missing_metadata_user_id_falls_back_to_email(self) -> None:
        service = PaymentWebhookService()
        sub = _sub_data(metadata={})
        event = _event(sub.model_dump())

        class _User:
            id = USER_ID

        with (
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.create",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.services.payments.payment_webhook_service.user_repository.get_by_email",
                new_callable=AsyncMock,
                return_value=_User(),
            ),
            patch.object(service, "_send_welcome_email", new_callable=AsyncMock),
            patch("app.services.payments.payment_webhook_service.track_subscription_event"),
        ):
            result = await service._handle_subscription_active(event)

        assert result.status == "processed"
        assert mock_create.await_args.args[0].user_id == USER_ID


class TestProcessWebhook:
    """The webhook envelope reads: event type echoed back, payload unwrapped.

    ``process_webhook`` had no test at all, so every read the strictness pass
    rewrote here — the ``type`` echo on both early-return paths and the nested
    ``data`` unwrap — ran unasserted.
    """

    @staticmethod
    def _service() -> PaymentWebhookService:
        return PaymentWebhookService()

    async def test_an_already_processed_webhook_echoes_its_event_type(self) -> None:
        """The idempotent return carries the real type, not a placeholder."""
        service = self._service()
        payload: dict[str, object] = {"type": "subscription.active", "data": {}}

        with patch.object(service, "_is_webhook_processed", AsyncMock(return_value=True)):
            result = await service.process_webhook(payload, "wh_1")

        assert result.status == "ignored"
        assert result.event_type == "subscription.active"

    async def test_an_already_processed_webhook_without_a_type_reports_unknown(self) -> None:
        """Absent type falls back to the sentinel rather than an empty string."""
        service = self._service()

        with patch.object(service, "_is_webhook_processed", AsyncMock(return_value=True)):
            result = await service.process_webhook({"data": {}}, "wh_2")

        assert result.event_type == "unknown"

    async def test_a_non_string_type_reports_unknown(self) -> None:
        """A provider-side type mangle must not propagate a non-string through."""
        service = self._service()

        with patch.object(service, "_is_webhook_processed", AsyncMock(return_value=True)):
            result = await service.process_webhook({"type": 42, "data": {}}, "wh_3")

        assert result.event_type == "unknown"

    async def test_a_processing_failure_still_echoes_the_event_type(self) -> None:
        """The failure path reports which event failed — the other text_bag read."""
        service = self._service()
        payload: dict[str, object] = {"type": "subscription.active", "data": {}}

        with patch.object(
            service, "_is_webhook_processed", AsyncMock(side_effect=RuntimeError("db down"))
        ):
            result = await service.process_webhook(payload, "wh_4")

        assert result.status == "failed"
        assert result.event_type == "subscription.active"
        assert "db down" in result.message

    async def test_financial_fields_are_read_from_the_nested_data_envelope(self) -> None:
        """Dodo wraps the payload under ``data``; the customer id comes from there."""
        service = self._service()
        payload: dict[str, object] = {
            "type": "subscription.active",
            "data": {"customer": {"customer_id": "cus_nested"}, "currency": "eur"},
        }
        captured: dict[str, object] = {}

        with (
            patch.object(service, "_is_webhook_processed", AsyncMock(return_value=True)),
            patch(
                "app.services.payments.payment_webhook_service.log.set",
                side_effect=lambda **kw: captured.update(kw),
            ),
        ):
            await service.process_webhook(payload, "wh_5")

        assert captured["payment"]["customer_id"] == "cus_nested"
        assert captured["payment"]["currency"] == "eur"

    async def test_a_payload_with_no_data_envelope_is_read_flat(self) -> None:
        """Without a ``data`` object the top level IS the payload — not an empty one."""
        service = self._service()
        payload: dict[str, object] = {"type": "subscription.active", "customer_id": "cus_flat"}
        captured: dict[str, object] = {}

        with (
            patch.object(service, "_is_webhook_processed", AsyncMock(return_value=True)),
            patch(
                "app.services.payments.payment_webhook_service.log.set",
                side_effect=lambda **kw: captured.update(kw),
            ),
        ):
            await service.process_webhook(payload, "wh_6")

        assert captured["payment"]["customer_id"] == "cus_flat"


class TestProcessWebhookUnknownType:
    """A payload with no "type" reports event_type "unknown" — the caller's
    only clue which webhook family misbehaved."""

    async def test_a_replayed_typeless_webhook_reports_unknown(self) -> None:
        service = PaymentWebhookService()
        with patch.object(service, "_is_webhook_processed", new=AsyncMock(return_value=True)):
            result = await service.process_webhook({"data": {}}, "wh-1")

        assert result.event_type == "unknown"
        assert result.status == "ignored"
        assert result.message == "Webhook already processed"

    async def test_a_failing_typeless_webhook_reports_unknown(self) -> None:
        # No "type" key: DodoWebhookEvent validation raises, taking the
        # failure path.
        service = PaymentWebhookService()
        with (
            patch.object(service, "_is_webhook_processed", new=AsyncMock(return_value=False)),
            patch("app.services.payments.payment_webhook_service.log") as mock_log,
        ):
            result = await service.process_webhook({"data": {}}, "wh-1")

        assert result.event_type == "unknown"
        assert result.status == "failed"
        # The failure names its exception class — "NoneType" here would mean
        # the error report lost the thing it reports.
        assert mock_log.error.call_args.kwargs["error_type"] == "ValidationError"

    async def test_an_unmatched_subscription_user_fails_with_a_named_reason(self) -> None:
        service = PaymentWebhookService()
        sub = _sub_data()
        sub.metadata = {}
        event = _event(sub.model_dump())

        with (
            patch(
                "app.services.payments.payment_webhook_service.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.payments.payment_webhook_service.user_repository.get_by_email",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await service._handle_subscription_active(event)

        assert result.status == "failed"
        assert result.message == "User not found"
