"""Pins every price, currency and plan label the API hands a user, end to end.

Written before the money single-source refactor and kept unchanged through it:
the catalogue, the agent's billing answers and the subscription status must
read identically after the refactor. Only the database, Redis and Dodo are
stubbed; every derivation between them and the text runs for real.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.subscription_tool import create_upgrade_link, get_subscription_details
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PlanDocument,
    PlanDuration,
    SubscriptionDocument,
)
from app.services.payments.payment_service import DodoPaymentService

SERVICE = "app.services.payments.payment_service"
TOOL = "app.agents.tools.subscription_tool"
USER_ID = "507f1f77bcf86cd799439011"
CREATED = datetime(2025, 11, 19, 9, 34, 47, tzinfo=UTC)

PRO_FEATURES = [
    "Chat on iMessage, WhatsApp, Telegram, Slack and Discord",
    "Inbox triage and drafted replies every morning",
    "Meeting briefs and reminders from your calendar",
    "Todos GAIA works on, not just tracks",
    "Workflows that run without you",
    "Long jobs it keeps working on while you are away",
    "Remembers what you tell it, once",
    "Priority support",
]

# The live catalogue (GET /payments/plans, 2026-10-08) plus the inactive legacy
# Free row. plan_type is what the catalogue rows carry once they are tagged; a
# model that does not know the field ignores it.
CATALOGUE_ROWS: list[dict[str, Any]] = [
    {
        "id": "6a158f054e866965fdac9ddd",
        "dodo_product_id": "",
        "name": "Enterprise",
        "description": "For teams ready to roll GAIA out to every employee.",
        "amount": 0,
        "currency": "USD",
        "duration": "monthly",
        "max_users": 0,
        "features": [
            "Everything in Pro",
            "SSO, SCIM & audit logs",
            "Custom integrations",
            "Self-host or private cloud",
            "Private Slack support",
            "Dedicated engineer & SLA",
        ],
        "plan_type": "enterprise",
    },
    {
        "id": "691d8f37091c87af56990f65",
        "dodo_product_id": "pdt_monthly",
        "name": "Pro",
        "description": "Everything GAIA does, in one plan.",
        "amount": 3000,
        "currency": "USD",
        "duration": "monthly",
        "max_users": 1,
        "features": PRO_FEATURES,
        "plan_type": "pro",
    },
    {
        "id": "691d8f38091c87af56990f66",
        "dodo_product_id": "pdt_yearly",
        "name": "Pro",
        "description": "Everything GAIA does, in one plan.",
        "amount": 30000,
        "currency": "USD",
        "duration": "yearly",
        "max_users": 1,
        "features": PRO_FEATURES,
        "plan_type": "pro",
    },
    {
        "id": "691d8f36091c87af56990f64",
        "dodo_product_id": "",
        "name": "Free",
        "description": "Legacy free row, inactive since the paid-only cutover.",
        "amount": 0,
        "currency": "USD",
        "duration": "monthly",
        "max_users": 1,
        "features": [],
        "plan_type": "free",
    },
]

# A Dodo-localised subscriber: the catalogue is USD, the subscription is ZAR.
ZAR_SUBSCRIPTION = SubscriptionDocument(
    id="sub_row_1",
    dodo_subscription_id="sub_zar",
    user_id=USER_ID,
    product_id="pdt_monthly",
    status="active",
    quantity=1,
    currency="ZAR",
    recurring_pre_tax_amount=57284,
    next_billing_date="2026-11-01T00:00:00Z",
    cancel_at_next_billing_date=False,
)

# One charge per currency real subscribers pay in, including a fully discounted INR one.
CHARGES = [
    SimpleNamespace(
        payment_id="pay_zar",
        status="succeeded",
        total_amount=59244,
        currency="ZAR",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        payment_method="card",
    ),
    SimpleNamespace(
        payment_id="pay_eur",
        status="succeeded",
        total_amount=2584,
        currency="EUR",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        payment_method="card",
    ),
    SimpleNamespace(
        payment_id="pay_inr",
        status="succeeded",
        total_amount=0,
        currency="INR",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        payment_method="upi",
    ),
]


def _catalogue(active_only: bool) -> list[PlanDocument]:
    rows = [
        {**row, "is_active": row["name"] != "Free", "created_at": CREATED, "updated_at": CREATED}
        for row in CATALOGUE_ROWS
    ]
    return [PlanDocument.model_validate(row) for row in rows if row["is_active"] or not active_only]


@pytest.fixture
def payment_service() -> DodoPaymentService:
    """Build a fresh service; the suite-wide paywall fence stubs the shared one."""
    return DodoPaymentService()


@pytest.fixture
def billing_backends(payment_service: DodoPaymentService) -> Iterator[MagicMock]:
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    plans = MagicMock()
    plans.list_plans = AsyncMock(side_effect=lambda active_only=True: _catalogue(active_only))
    subscriptions = MagicMock()
    subscriptions.get_active_for_user = AsyncMock(return_value=None)
    subscriptions.has_any_for_user = AsyncMock(return_value=False)
    subscriptions.list_for_user = AsyncMock(return_value=[])
    dodo = MagicMock()
    dodo.payments.list = MagicMock(return_value=SimpleNamespace(items=[]))
    with (
        patch(f"{SERVICE}.redis_cache", cache),
        patch(f"{SERVICE}.plan_repository", plans),
        patch(f"{SERVICE}.subscription_repository", subscriptions),
        patch.object(payment_service, "client", dodo, create=True),
        patch(f"{TOOL}.payment_service", payment_service),
    ):
        yield subscriptions


def _subscribe(subscriptions: MagicMock, payment_service: DodoPaymentService) -> None:
    subscriptions.get_active_for_user.return_value = ZAR_SUBSCRIPTION
    subscriptions.has_any_for_user.return_value = True
    subscriptions.list_for_user.return_value = [ZAR_SUBSCRIPTION]
    payment_service.client.payments.list.return_value = SimpleNamespace(items=CHARGES)


def _cfg() -> dict[str, dict[str, str]]:
    return {"configurable": {"user_id": USER_ID}}


class TestServedCatalogue:
    async def test_the_web_is_served_the_live_rows_without_the_free_row(
        self, billing_backends: MagicMock, payment_service: DodoPaymentService
    ) -> None:
        plans = await payment_service.get_plans(active_only=False)

        assert [
            (p.name, p.description, p.amount, p.currency, p.duration.value, p.features)
            for p in plans
        ] == [
            (
                "Enterprise",
                "For teams ready to roll GAIA out to every employee.",
                0,
                "USD",
                "monthly",
                CATALOGUE_ROWS[0]["features"],
            ),
            ("Pro", "Everything GAIA does, in one plan.", 3000, "USD", "monthly", PRO_FEATURES),
            ("Pro", "Everything GAIA does, in one plan.", 30000, "USD", "yearly", PRO_FEATURES),
        ]


class TestSubscriptionStatus:
    async def test_a_zar_subscriber_is_shown_the_usd_catalogue_plan(
        self, billing_backends: MagicMock, payment_service: DodoPaymentService
    ) -> None:
        _subscribe(billing_backends, payment_service)

        status = await payment_service.get_user_subscription_status(USER_ID)

        assert status.current_plan is not None
        assert (
            status.current_plan.name,
            status.current_plan.amount,
            status.current_plan.currency,
            status.current_plan.duration.value,
        ) == ("Pro", 3000, "USD", "monthly")
        assert status.subscription is not None
        assert (status.subscription.recurring_pre_tax_amount, status.subscription.currency) == (
            57284,
            "ZAR",
        )
        assert (status.is_subscribed, status.plan_type) == (True, "pro")

    async def test_a_non_subscriber_reads_as_free(
        self, billing_backends: MagicMock, payment_service: DodoPaymentService
    ) -> None:
        status = await payment_service.get_user_subscription_status(USER_ID)

        assert (status.is_subscribed, status.plan_type, status.current_plan) == (
            False,
            "free",
            None,
        )


class TestAgentBillingAnswers:
    async def test_a_zar_subscriber_hears_the_catalogue_price_and_local_charges(
        self, billing_backends: MagicMock, payment_service: DodoPaymentService
    ) -> None:
        _subscribe(billing_backends, payment_service)

        result = await get_subscription_details.ainvoke({}, config=_cfg())

        assert result == (
            "Plan: Pro\n"
            "Subscribed: yes (status: active)\n"
            "Price: 30.00 USD per month\n"
            "Renews on: 2026-11-01T00:00:00Z\n"
            "Recent charges (3):\n"
            "  - 2026-10-01 592.44 ZAR (succeeded)\n"
            "  - 2026-09-01 25.84 EUR (succeeded)\n"
            "  - 2026-08-01 0.00 INR (succeeded)"
        )

    async def test_a_non_subscriber_hears_the_free_tier_line(
        self, billing_backends: MagicMock, payment_service: DodoPaymentService
    ) -> None:
        result = await get_subscription_details.ainvoke({}, config=_cfg())

        assert result == "Plan: Free\nSubscribed: no, this user is on the free tier."

    @pytest.mark.parametrize(
        ("cycle", "price_line"),
        [
            (PlanDuration.MONTHLY, "GAIA Pro: 30.00 USD per month."),
            (PlanDuration.YEARLY, "GAIA Pro: 300.00 USD per year."),
        ],
    )
    async def test_the_upgrade_pitch_quotes_the_catalogue_price(
        self,
        billing_backends: MagicMock,
        payment_service: DodoPaymentService,
        cycle: PlanDuration,
        price_line: str,
    ) -> None:
        checkout = CreateSubscriptionResponse(
            subscription_id="cs_1",
            payment_link="https://checkout.dodopayments.com/s/cs_1",
            status="payment_link_created",
        )
        with patch.object(
            payment_service, "create_subscription", AsyncMock(return_value=checkout)
        ) as minted:
            result = await create_upgrade_link.ainvoke({"billing_cycle": cycle}, config=_cfg())

        assert minted.await_args is not None
        assert minted.await_args.args[1] == f"pdt_{cycle.value}"
        assert result == (
            f"{price_line}\n"
            "Includes: " + "; ".join(PRO_FEATURES) + "\n"
            "Checkout link (already tied to this user's account): "
            "https://checkout.dodopayments.com/s/cs_1\n"
            "Give them the link as-is. It stays valid for about an hour."
        )
