#!/usr/bin/env python3
"""
Complete Payment setup script for GAIA.
This script sets up subscription plans in the database using Dodo product IDs.

IMPORTANT: Run this script from the correct directory!

1. If running locally:
    cd /path/to/your/gaia/apps/api
    python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

2. If running inside Docker container:
    cd /app
    python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

3. Alternative Docker approach (set PYTHONPATH):
    PYTHONPATH=/app python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

4. Run as module (from app directory):
    python -m scripts.payment_setup --monthly-product-id <id> --yearly-product-id <id>

`docker exec` does not run the image entrypoint, so the Infisical machine-identity
variables it exports from the Docker Swarm secrets are absent in an exec shell and
settings import fails. Export them from /run/secrets/gaia_infisical_* first, the
same way scripts/docker-entrypoint.sh does.

Prerequisites:
- DODO_PAYMENTS_API_KEY must be available in Infisical secrets or as an environment variable.
  - The script will first attempt to fetch DODO_PAYMENTS_API_KEY from Infisical (if configured),
     and fallback to the environment variable or settings if not found.
- MongoDB connection string (MONGO_DB) must be configured
- Have your Dodo product IDs ready from your Dodo Payments dashboard

Usage:
     python payment_setup.py --monthly-product-id <product_id> --yearly-product-id <product_id>

Pass --dry-run first to print the per-field diff without writing anything.
"""

import argparse
import asyncio
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


from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.config.settings import settings
from app.constants.cache import PLANS_CACHE_KEYS
from app.constants.memory import FREE_MEMORY_FACT_LIMIT
from app.db.redis import redis_cache
from app.models.payment_models import PlanDocument

# Timestamps are bookkeeping, not catalogue content: a run that changes none of
# these fields is a no-op, so they are what the diff compares.
_TIMESTAMP_FIELDS = {"created_at", "updated_at"}

Outcome = Literal["created", "updated", "unchanged"]


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
            duration="monthly",
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
            duration="monthly",
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
            description="For teams ready to roll GAIA out to every employee.",
            amount=0,  # Custom pricing, frontend shows 'Custom' label.
            currency="USD",
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
    """The plan's content, without the id and the timestamps that always move."""
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
    """The human-readable summary printed under each processed plan."""
    print(f"   💰 Amount: ${plan.amount / 100:.2f} {plan.currency}")
    print(f"   📅 Duration: {plan.duration.capitalize()}")
    print(f"   👥 Max Users: {plan.max_users}")
    print(f"   🏷️  Dodo Product ID: {plan.dodo_product_id or 'Free Plan (No Product ID)'}")
    print(f"   🎯 Features: {len(plan.features)} features")
    print()


def print_summary(outcomes: list[Outcome], dry_run: bool) -> None:
    """Counts per outcome, worded for whichever mode the run was in."""
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
    monthly_product_id: str, yearly_product_id: str, dry_run: bool = False
) -> bool:
    """Set up GAIA subscription plans in the database using Dodo product IDs."""
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
    print(f"📦 Monthly Product ID: {monthly_product_id}")
    print(f"📦 Yearly Product ID: {yearly_product_id}")
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
        for plan in build_plan_catalogue(monthly_product_id, yearly_product_id):
            outcomes.append(await reconcile_plan(collection, plan, dry_run))
            print_plan_details(plan)

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
    """Main entry point."""
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
        "--dry-run",
        action="store_true",
        help="Print the changes that would be made without writing to the database",
    )

    args = parser.parse_args()

    succeeded = await setup_payment_plans(
        args.monthly_product_id, args.yearly_product_id, dry_run=args.dry_run
    )
    if not succeeded:
        sys.exit(1)

    print(
        "\n🎉 Dry run finished!" if args.dry_run else "\n🎉 Payment setup completed successfully!"
    )


if __name__ == "__main__":
    asyncio.run(main())
