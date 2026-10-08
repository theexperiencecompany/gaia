#!/usr/bin/env python3
"""Sync GAIA's subscription plan catalogue in the database from the Dodo products.

Dodo is the price: each Pro row's amount and currency are read back from its
Dodo product, and every row is tagged with the tier it sells. Run from apps/api/:
python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>
(also works via PYTHONPATH=/app, or python -m scripts.payment_setup). By default
it only prints the per-field diff against Mongo; pass --apply to write it.

docker exec skips the image entrypoint, so Infisical's machine-identity
vars from Docker Swarm secrets are missing in an exec shell; export them
from /run/secrets/gaia_infisical_* first, like docker-entrypoint.sh does.

Needs DODO_PAYMENTS_API_KEY (Infisical or env var) and MONGO_DB configured.
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import sys
from typing import Any, Literal

# Ensure Infisical secrets are injected before importing settings
try:
    from app.config.secrets import inject_infisical_secrets

    inject_infisical_secrets()
    # Presence only — this script is run against production, so its stdout must
    # never carry the machine-identity credentials or the Dodo API key.
    print(f"[DEBUG] ENV: {os.environ.get('ENV')}")
    for key in ("INFISICAL_PROJECT_ID", "DODO_PAYMENTS_API_KEY"):
        print(f"[DEBUG] {key}: {'present' if os.environ.get(key) else 'MISSING'} after injection")
except Exception as e:
    print(f"[WARN] Could not inject Infisical secrets: {e}")

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


from dodopayments import DodoPayments
from dodopayments.types.price import RecurringPrice
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.config.settings import settings
from app.constants.cache import PLANS_CACHE_KEYS
from app.db.redis import redis_cache
from app.models.payment_models import PlanDocument, PlanDuration, PlanTier
from app.services.payments.payment_service import payment_service

# Timestamps are bookkeeping, not catalogue content: a run that changes none of
# these fields is a no-op, so they are what the diff compares.
_TIMESTAMP_FIELDS = {"created_at", "updated_at"}

Outcome = Literal["created", "updated", "unchanged"]

# The Dodo billing interval each catalogue duration must be charged on.
DODO_INTERVAL: dict[PlanDuration, str] = {
    PlanDuration.MONTHLY: "Month",
    PlanDuration.YEARLY: "Year",
}

# Quoted by the team, never checked out, so it carries no Dodo price.
ENTERPRISE_CURRENCY = "USD"


@dataclass(frozen=True)
class ProductPrice:
    """What Dodo charges for one product, in the currency's minor unit."""

    product_id: str
    amount: int
    currency: str


def fetch_product_price(
    client: DodoPayments, product_id: str, duration: PlanDuration
) -> ProductPrice:
    """Read a Pro product's recurring price from Dodo, refusing one billed on another cycle."""
    price = client.products.retrieve(product_id).price
    if not isinstance(price, RecurringPrice):
        raise ValueError(f"Dodo product {product_id} is not a subscription ({price.type})")
    if price.payment_frequency_interval != DODO_INTERVAL[duration]:
        raise ValueError(
            f"Dodo product {product_id} bills every {price.payment_frequency_interval}, "
            f"not the {duration} plan's {DODO_INTERVAL[duration]}"
        )
    return ProductPrice(product_id=product_id, amount=price.price, currency=price.currency)


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


async def deactivate_free_plan(
    collection: AsyncIOMotorCollection[dict[str, Any]], dry_run: bool
) -> bool:
    """Retire a leftover Free row: inactive and tagged free, kept as the historical record.

    GAIA is paid-only and the catalogue no longer seeds a Free row, but the API
    still reads inactive rows, so the row must carry its tier.
    Idempotent: a no-op once the row is retired or was never seeded.
    """
    retired = {"is_active": False, "plan_type": PlanTier.FREE.value}
    existing = await collection.find_one(
        {"name": "Free", "$or": [{"is_active": True}, {"plan_type": {"$ne": PlanTier.FREE.value}}]}
    )
    if existing is None:
        return False

    if dry_run:
        print("   📝 Would retire the Free plan (inactive, tagged free)")
    else:
        await collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {**retired, "updated_at": datetime.now(UTC)}},
        )
        print("   🚫 Retired the Free plan (inactive, tagged free)")
    return True


async def count_untagged_plans(collection: AsyncIOMotorCollection[dict[str, Any]]) -> int:
    """Rows the API cannot read: every plan row must name the tier it sells."""
    return await collection.count_documents({"plan_type": {"$exists": False}})


async def cleanup_old_indexes(collection: AsyncIOMotorCollection[dict[str, Any]]) -> None:
    """Remove old payment gateway indexes that might conflict."""
    try:
        # List all indexes
        indexes = await collection.list_indexes().to_list(length=None)

        # Find and drop old payment gateway indexes
        old_indexes = ["razorpay_plan_id_1", "stripe_plan_id_1", "paypal_plan_id_1"]

        for index in indexes:
            index_name = index.get("name")
            if index_name in old_indexes:
                print(f"🗑️  Dropping old index: {index_name}")
                await collection.drop_index(index_name)

    except Exception as e:
        print(f"⚠️  Warning: Could not clean up old indexes: {e}")


def catalogue_fields(plan: PlanDocument) -> dict[str, Any]:
    """Return the plan's content, without the id and the timestamps that always move."""
    return plan.model_dump(by_alias=True, exclude={"id"} | _TIMESTAMP_FIELDS)


def diff_plan(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Fields whose stored value differs from what the setup would write."""
    return {
        field: (existing.get(field), value)
        for field, value in desired.items()
        if existing.get(field) != value
    }


async def reconcile_plan(
    collection: AsyncIOMotorCollection[dict[str, Any]], plan: PlanDocument, dry_run: bool
) -> Outcome:
    """Bring one plan to its desired state, or report what that would take."""
    print(f"⚙️  Processing: {plan.name} ({plan.duration.capitalize()})")

    existing_plan = await collection.find_one({"name": plan.name, "duration": plan.duration})
    desired = catalogue_fields(plan)

    if existing_plan is None:
        if dry_run:
            print("   📝 Would create new plan")
        else:
            await collection.insert_one(plan.model_dump(by_alias=True, exclude={"id"}))
            print("   ✅ Created new plan")
        return "created"

    changes = diff_plan(existing_plan, desired)
    if not changes:
        # Nothing but the timestamps would move, so writing would only churn
        # updated_at — leave the document alone so the dry run stays honest.
        print("   ➖ Existing plan already up to date")
        return "unchanged"

    if dry_run:
        print("   📝 Would update existing plan:")
        for field, (before, after) in changes.items():
            print(f"      - {field}: {before!r} → {after!r}")
    else:
        await collection.update_one(
            {"_id": existing_plan["_id"]},
            {"$set": {**desired, "updated_at": datetime.now(UTC)}},
        )
        print("   ✅ Updated existing plan")
    return "updated"


def print_plan_details(plan: PlanDocument) -> None:
    """Print the human-readable summary under each processed plan."""
    print(f"   💰 Amount: ${plan.amount / 100:.2f} {plan.currency}")
    print(f"   📅 Duration: {plan.duration.capitalize()}")
    print(f"   👥 Max Users: {plan.max_users}")
    print(f"   🏷️  Dodo Product ID: {plan.dodo_product_id or 'Free Plan (No Product ID)'}")
    print(f"   🎯 Features: {len(plan.features)} features")
    print()


def print_summary(outcomes: list[Outcome], dry_run: bool) -> None:
    """Print counts per outcome, worded for whichever mode the run was in."""
    print("=" * 50)
    print("📈 Setup Summary:")
    print(f"   • {'Would create' if dry_run else 'Created'}: {outcomes.count('created')} plans")
    print(f"   • {'Would update' if dry_run else 'Updated'}: {outcomes.count('updated')} plans")
    print(f"   • Unchanged: {outcomes.count('unchanged')} plans")
    print(f"   • Total: {len(outcomes)} plans processed")
    print()


async def print_active_plans(
    collection: AsyncIOMotorCollection[dict[str, Any]], dry_run: bool
) -> None:
    """List the active plans as they currently stand in the database."""
    plans = await collection.find({"is_active": True}).sort("amount", 1).to_list(length=None)

    print("📋 Active Plans (current state, before any write):" if dry_run else "📋 Active Plans:")
    for plan in plans:
        print(f"   • {plan['name']} ({plan['duration']}) - ${plan['amount'] / 100:.2f}")
        print(f"     Dodo Product ID: {plan.get('dodo_product_id') or 'N/A'}")
    print()


async def invalidate_plan_cache() -> None:
    """Drop the cached plan catalogue so the API re-reads the new prices."""
    # Deliberately the raw client: RedisCache.delete logs its failures and
    # returns, which here would print a success message while the API keeps
    # serving the prices we just replaced. The command raises instead.
    await redis_cache.client.delete(*PLANS_CACHE_KEYS)
    print(f"🧹 Cleared cached plan catalogue: {', '.join(PLANS_CACHE_KEYS)}")


async def setup_payment_plans(
    monthly_product_id: str, yearly_product_id: str, dry_run: bool = True
) -> bool:
    """Sync the subscription plan catalogue from the Dodo products; dry_run only prints the diff."""
    print("🚀 GAIA Payment Setup" + (" (DRY RUN — no writes)" if dry_run else ""))
    print("=" * 50)

    # Try to fetch DODO_PAYMENTS_API_KEY from Infisical-injected env, fallback to settings
    dodo_payments_api_key = os.environ.get("DODO_PAYMENTS_API_KEY") or getattr(
        settings, "DODO_PAYMENTS_API_KEY", None
    )
    if not dodo_payments_api_key:
        print("❌ DODO_PAYMENTS_API_KEY not found in Infisical or environment variables/settings")
        return False

    print("🔗 Dodo Payments API key resolved")
    monthly, yearly = await asyncio.gather(
        asyncio.to_thread(
            fetch_product_price, payment_service.client, monthly_product_id, PlanDuration.MONTHLY
        ),
        asyncio.to_thread(
            fetch_product_price, payment_service.client, yearly_product_id, PlanDuration.YEARLY
        ),
    )
    print(
        f"📦 Monthly Product ID: {monthly_product_id} (Dodo: {monthly.amount} {monthly.currency})"
    )
    print(f"📦 Yearly Product ID: {yearly_product_id} (Dodo: {yearly.amount} {yearly.currency})")
    print()

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.MONGO_DB)
    try:
        collection = client["GAIA"]["subscription_plans"]

        # Clean up old payment gateway indexes first
        if not dry_run:
            await cleanup_old_indexes(collection)

        print("📊 Setting up subscription plans...")
        print()

        outcomes: list[Outcome] = []
        for plan in build_plan_catalogue(monthly, yearly):
            outcomes.append(await reconcile_plan(collection, plan, dry_run))
            print_plan_details(plan)

        await deactivate_free_plan(collection, dry_run)

        untagged = await count_untagged_plans(collection)
        if dry_run:
            print(f"   🏷️  {untagged} plan row(s) carry no plan_type before this run")
        elif untagged:
            raise RuntimeError(
                f"{untagged} plan row(s) carry no plan_type; the API cannot read them"
            )

        # Before the report below, so a failure while reading it back can never
        # leave the API serving a cached catalogue the database has moved past.
        if not dry_run:
            await invalidate_plan_cache()

        print_summary(outcomes, dry_run)
        await print_active_plans(collection, dry_run)

        if dry_run:
            print("✅ Dry run complete — nothing was written.")
        else:
            print("✅ Payment system setup complete!")
            print("🔗 Frontend can now fetch plans via GET /api/v1/payments/plans")
            print("🎯 Users can create subscriptions via POST /api/v1/payments/subscriptions")

        return True
    finally:
        client.close()
        print("🔌 Database connection closed")


async def main() -> None:
    """Run the payment setup script."""
    parser = argparse.ArgumentParser(description="Setup Payment plans for GAIA")
    parser.add_argument(
        "--monthly-product-id",
        required=True,
        help="Dodo product ID for monthly Pro plan",
    )
    parser.add_argument(
        "--yearly-product-id",
        required=True,
        help="Dodo product ID for yearly Pro plan",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the changes; without it the run only prints the diff against the database",
    )

    args = parser.parse_args()

    succeeded = await setup_payment_plans(
        args.monthly_product_id, args.yearly_product_id, dry_run=not args.apply
    )
    if not succeeded:
        sys.exit(1)

    print("\n🎉 Payment setup completed successfully!" if args.apply else "\n🎉 Dry run finished!")


if __name__ == "__main__":
    asyncio.run(main())
