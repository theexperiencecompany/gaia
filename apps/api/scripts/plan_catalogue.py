"""GAIA's subscription plan catalogue as rows: what payment_setup syncs from Dodo and the dev seed writes.

Imports only the plan model, so a seed can build the rows without the app's settings.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files

from app.models.payment_models import PlanDocument, PlanTier

# Quoted by the team, never checked out, so it carries no Dodo price.
ENTERPRISE_CURRENCY = "USD"

# The Pro monthly price the static marketing pages quote; the web reads the same file.
ADVERTISED_PRO_MONTHLY_PRICE = files("shared") / "assets" / "pricing" / "pro-monthly-price.json"


@dataclass(frozen=True)
class ProductPrice:
    """What Dodo charges for one product, in the currency's minor unit."""

    product_id: str
    amount: int
    currency: str


def build_plan_catalogue(monthly: ProductPrice, yearly: ProductPrice) -> list[PlanDocument]:
    """Return the subscription plans GAIA offers, as they should exist in the database."""
    now = datetime.now(UTC)
    # GAIA is paid-only: these read as what Pro includes, never as a step up
    # from a free tier. Re-run this script after editing so the live rows match.
    pro_features = [
        "Chat on iMessage, WhatsApp, Telegram, Slack and Discord",
        "Inbox triage and drafted replies every morning",
        "Meeting briefs and reminders from your calendar",
        "Todos GAIA works on, not just tracks",
        "Workflows that run without you",
        "Long jobs it keeps working on while you are away",
        "Remembers what you tell it, once",
        "Priority support",
    ]

    return [
        PlanDocument(
            dodo_product_id=monthly.product_id,
            name="Pro",
            plan_type=PlanTier.PRO,
            description="Everything GAIA does, in one plan.",
            amount=monthly.amount,
            currency=monthly.currency,
            duration="monthly",
            max_users=1,
            features=pro_features,
            is_active=True,
            created_at=now,
            updated_at=now,
        ),
        PlanDocument(
            dodo_product_id=yearly.product_id,
            name="Pro",
            plan_type=PlanTier.PRO,
            description="Everything GAIA does, in one plan.",
            amount=yearly.amount,
            currency=yearly.currency,
            duration="yearly",
            max_users=1,
            features=pro_features,
            is_active=True,
            created_at=now,
            updated_at=now,
        ),
        PlanDocument(
            # Enterprise — lead capture only, no Dodo product.
            dodo_product_id="",
            name="Enterprise",
            plan_type=PlanTier.ENTERPRISE,
            description="For teams ready to roll GAIA out to every employee.",
            amount=0,  # Custom pricing, frontend shows 'Custom' label.
            currency=ENTERPRISE_CURRENCY,
            duration="monthly",
            max_users=0,  # 0 == unlimited, contact sales
            features=[
                "Everything in Pro",
                "SSO, SCIM & audit logs",
                "Custom integrations",
                "Self-host or private cloud",
                "Private Slack support",
                "Dedicated engineer & SLA",
            ],
            is_active=True,
            created_at=now,
            updated_at=now,
        ),
    ]
