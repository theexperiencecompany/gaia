"""Unit tests for the payment request models and the checkout-source enum."""

from pydantic import ValidationError
import pytest

from app.models.payment_models import (
    CheckoutSource,
    CreateCheckoutSessionRequest,
    CreateSubscriptionRequest,
    PlanDuration,
    VerifyPaymentRequest,
)

# ---------------------------------------------------------------------------
# CheckoutSource.return_path
# ---------------------------------------------------------------------------


class TestCheckoutSourceReturnPath:
    def test_every_source_maps_to_its_return_path(self) -> None:
        """Only a checkout started in the wizard returns to the wizard."""
        assert {source: source.return_path for source in CheckoutSource} == {
            CheckoutSource.PAYWALL_MODAL: "/payment/success",
            CheckoutSource.PRICING_CARD: "/payment/success",
            CheckoutSource.PAYMENT_RETRY: "/payment/success",
            CheckoutSource.CHECKOUT_RESUME: "/payment/success",
            CheckoutSource.ONBOARDING: "/onboarding?checkout=returned",
        }

    def test_the_value_carried_over_the_wire_also_resolves(self) -> None:
        """The enum is rebuilt from the request body's string, not passed as a member."""
        assert CheckoutSource("onboarding").return_path == "/onboarding?checkout=returned"
        assert CheckoutSource("paywall_modal").return_path == "/payment/success"


# ---------------------------------------------------------------------------
# CreateSubscriptionRequest / CreateCheckoutSessionRequest
# ---------------------------------------------------------------------------


class TestCreateSubscriptionRequest:
    def test_source_is_optional_so_a_deployed_bundle_still_checks_out(self) -> None:
        request = CreateSubscriptionRequest(product_id="prod_abc123")

        assert request.source is None

    def test_source_is_coerced_from_its_wire_value(self) -> None:
        request = CreateSubscriptionRequest(product_id="prod_abc123", source="pricing_card")

        assert request.source is CheckoutSource.PRICING_CARD


class TestCreateCheckoutSessionRequest:
    def test_source_is_required(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateCheckoutSessionRequest()

        errors = exc_info.value.errors()
        assert [(error["loc"], error["type"]) for error in errors] == [(("source",), "missing")]

    def test_billing_cycle_defaults_to_monthly(self) -> None:
        request = CreateCheckoutSessionRequest(source=CheckoutSource.PAYWALL_MODAL)

        assert request.billing_cycle is PlanDuration.MONTHLY

    def test_an_unknown_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateCheckoutSessionRequest(source="carrier_pigeon")

        assert [error["loc"] for error in exc_info.value.errors()] == [("source",)]


# ---------------------------------------------------------------------------
# VerifyPaymentRequest
# ---------------------------------------------------------------------------


class TestVerifyPaymentRequest:
    def test_subscription_id_is_an_optional_hint(self) -> None:
        assert VerifyPaymentRequest().subscription_id is None

    def test_extra_fields_are_forbidden(self) -> None:
        """The client controls this body, so nothing beyond the hint is accepted."""
        with pytest.raises(ValidationError) as exc_info:
            VerifyPaymentRequest(subscription_id="sub_1", user_id="someone_else")

        assert [(error["loc"], error["type"]) for error in exc_info.value.errors()] == [
            (("user_id",), "extra_forbidden")
        ]
