"""Revenue properties on payment and subscription analytics events.

One tax rule, named in every property: amounts are pre-tax. A charge carries
what the customer paid in their own currency and, when Dodo settles in USD,
the USD that reached GAIA. A subscription event has no settlement, so it
carries only the local recurring price. A zero amount is a real
discount-code charge and is reported as 0, never dropped.
"""

from dataclasses import dataclass

from app.constants.log_tags import LogTag
from app.models.webhook_models import DodoPaymentData, DodoSubscriptionData
from app.utils.money import to_major_units
from shared.py.wide_events import log

USD = "USD"


@dataclass(frozen=True)
class PaymentRevenue:
    """A charge's pre-tax amount in its own currency, and the pre-tax USD when Dodo settled in USD."""

    amount_charged_pre_tax: float
    currency_charged: str
    amount_usd_pre_tax: float | None


@dataclass(frozen=True)
class SubscriptionRevenue:
    """A subscription's pre-tax recurring price in its own currency."""

    amount_charged_pre_tax: float
    currency_charged: str


def payment_revenue_properties(payment: DodoPaymentData) -> PaymentRevenue:
    """Pre-tax charged amount and currency, plus the pre-tax USD settlement."""
    amount_usd_pre_tax: float | None = None
    if payment.settlement_currency.upper() == USD:
        amount_usd_pre_tax = float(
            to_major_units(payment.settlement_amount - payment.settlement_tax, USD)
        )
    else:
        log.error(
            f"{LogTag.PAYMENT} Payment settled in a currency other than USD; amount_usd_pre_tax not sent",
            payment_id=payment.payment_id,
            settlement_currency=payment.settlement_currency,
        )
    return PaymentRevenue(
        amount_charged_pre_tax=float(
            to_major_units(payment.total_amount - payment.tax, payment.currency)
        ),
        currency_charged=payment.currency,
        amount_usd_pre_tax=amount_usd_pre_tax,
    )


def subscription_revenue_properties(data: DodoSubscriptionData) -> SubscriptionRevenue:
    """Pre-tax recurring price in the subscription's own currency."""
    return SubscriptionRevenue(
        amount_charged_pre_tax=float(to_major_units(data.recurring_pre_tax_amount, data.currency)),
        currency_charged=data.currency,
    )
