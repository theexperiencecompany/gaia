"""The GAIA subscription plan catalogue — the single source of truth.

Both writers share it so they produce identical rows: scripts/payment_setup.py
provisions the full catalogue against Dodo product ids, and
services/bootstrap/plan_seeder.py seeds the Free row on instances that have no
payment provider.
"""

from datetime import UTC, datetime

from app.constants.memory import FREE_MEMORY_FACT_LIMIT
from app.models.payment_models import PlanDocument, PlanDuration


def build_plan_catalogue(monthly_product_id: str, yearly_product_id: str) -> list[PlanDocument]:
    """The subscription plans GAIA offers, as they should exist in the database."""
    now = datetime.now(UTC)
    # Ordered to line up row-for-row with the Free card's list below, so each
    # upgrade sits on the same line as the limit it replaces.
    pro_features = [
        "Chat on iMessage",
        "More powerful models",
        "Much higher usage limits",
        "Unlimited memories",
        "Priority support",
        "Long running tasks",
        "Early access to new features",
    ]

    return [
        PlanDocument(
            dodo_product_id="",  # Free plan doesn't need Dodo product ID
            name="Free",
            description="Start free. See what GAIA can do.",
            amount=0,
            currency="USD",
            duration=PlanDuration.MONTHLY,
            max_users=1,
            features=[
                "Chat on WhatsApp, Telegram, Discord & Slack",
                "Standard models",
                "Daily AI usage allowance",
                f"{FREE_MEMORY_FACT_LIMIT} saved memories",
                "Community support",
                "All tools & 100s of integrations",
            ],
            is_active=True,
            created_at=now,
            updated_at=now,
        ),
        PlanDocument(
            dodo_product_id=monthly_product_id,
            name="Pro",
            description="For serious users who want to save time.",
            amount=3000,  # $30.00 in cents
            currency="USD",
            duration=PlanDuration.MONTHLY,
            max_users=1,
            features=pro_features,
            is_active=True,
            created_at=now,
            updated_at=now,
        ),
        PlanDocument(
            dodo_product_id=yearly_product_id,
            name="Pro",
            description="For serious users who want to save time.",
            amount=30000,  # $300.00 in cents (2 months free, ~16.7% discount)
            currency="USD",
            duration=PlanDuration.YEARLY,
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
            description="For teams ready to roll GAIA out to every employee.",
            amount=0,  # Custom pricing, frontend shows 'Custom' label.
            currency="USD",
            duration=PlanDuration.MONTHLY,
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
