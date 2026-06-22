#!/usr/bin/env python3
# mypy: ignore-errors
"""
Grant or revoke Pro access for a user in the local dev MongoDB.

Inserts a synthetic active subscription record so the user is treated as Pro
without going through the Dodo Payments webhook flow. Useful for testing Pro
features locally when you don't want to set up real payment infrastructure.

Usage (from apps/api/):
    python scripts/grant_pro_access.py --email user@example.com
    python scripts/grant_pro_access.py --email user@example.com --remove

The script creates a subscription document with dodo_subscription_id prefixed
"dev_" so it's easy to identify and clean up later. Running --remove sets that
document's status to "cancelled". Redis plan-type cache is invalidated either way.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

# Inject Infisical secrets before importing settings (mirrors payment_setup.py)
try:
    from app.config.secrets import inject_infisical_secrets

    inject_infisical_secrets()
except Exception as e:
    print(f"[warn] Could not inject Infisical secrets (expected in local dev): {e}")

# Allow `from app.*` imports when running the script directly
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX  # noqa: E402

DEV_SUBSCRIPTION_PREFIX = "dev_"


async def _invalidate_redis_cache(user_id: str) -> None:
    cache_key = f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}"
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        deleted = await r.delete(cache_key)
        await r.aclose()
        if deleted:
            print(f"  Redis: invalidated plan cache for user {user_id}")
        else:
            print(f"  Redis: no cached plan entry found (key: {cache_key})")
    except Exception as e:
        print(f"  Redis: could not invalidate cache ({e}) — it will expire on its own")


async def grant_pro(email: str) -> None:
    client = AsyncIOMotorClient(settings.MONGO_DB)
    try:
        db = client["GAIA"]
        users = db["users"]
        subscriptions = db["subscriptions"]

        user = await users.find_one({"email": email})
        if not user:
            print(f"Error: no user found with email '{email}'")
            return

        user_id = str(user["_id"])
        print(f"Found user: {user.get('name') or email} (id={user_id})")

        # Check for an existing active subscription (real or dev)
        existing_active = await subscriptions.find_one({"user_id": user_id, "status": "active"})
        if existing_active:
            sub_id = existing_active.get("dodo_subscription_id", "")
            if sub_id.startswith(DEV_SUBSCRIPTION_PREFIX):
                print(f"User already has an active dev subscription ({sub_id}). Nothing to do.")
            else:
                print(
                    f"User already has an active real subscription ({sub_id}). "
                    "Not overwriting — revoke via Dodo dashboard if needed."
                )
            return

        # Upsert a dev subscription: if one exists but is inactive, reactivate it
        dev_sub_id = f"{DEV_SUBSCRIPTION_PREFIX}{user_id}"
        now = datetime.now(UTC)
        existing_dev = await subscriptions.find_one({"dodo_subscription_id": dev_sub_id})

        if existing_dev:
            await subscriptions.update_one(
                {"dodo_subscription_id": dev_sub_id},
                {
                    "$set": {
                        "status": "active",
                        "next_billing_date": now + timedelta(days=365),
                        "updated_at": now,
                    }
                },
            )
            print(f"Reactivated existing dev subscription ({dev_sub_id})")
        else:
            await subscriptions.insert_one(
                {
                    "dodo_subscription_id": dev_sub_id,
                    "user_id": user_id,
                    "product_id": "dev_pro_product",
                    "status": "active",
                    "quantity": 1,
                    "currency": "USD",
                    "recurring_pre_tax_amount": 3000,
                    "payment_frequency_count": 1,
                    "payment_frequency_interval": "month",
                    "subscription_period_count": 1,
                    "subscription_period_interval": "month",
                    "next_billing_date": now + timedelta(days=365),
                    "previous_billing_date": now,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": {"dev": True, "granted_by": "grant_pro_access.py"},
                }
            )
            print(f"Created dev subscription ({dev_sub_id})")

        await _invalidate_redis_cache(user_id)
        print(f"Done. '{email}' now has Pro access.")

    finally:
        client.close()


async def revoke_pro(email: str) -> None:
    client = AsyncIOMotorClient(settings.MONGO_DB)
    try:
        db = client["GAIA"]
        users = db["users"]
        subscriptions = db["subscriptions"]

        user = await users.find_one({"email": email})
        if not user:
            print(f"Error: no user found with email '{email}'")
            return

        user_id = str(user["_id"])
        print(f"Found user: {user.get('name') or email} (id={user_id})")

        dev_sub_id = f"{DEV_SUBSCRIPTION_PREFIX}{user_id}"
        result = await subscriptions.update_one(
            {"dodo_subscription_id": dev_sub_id},
            {"$set": {"status": "cancelled", "updated_at": datetime.now(UTC)}},
        )

        if result.matched_count == 0:
            print("No dev subscription found for this user. Nothing to remove.")
            return

        await _invalidate_redis_cache(user_id)
        print(f"Done. Pro access revoked for '{email}'.")

    finally:
        client.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Grant or revoke dev Pro access for a GAIA user")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Revoke Pro access instead of granting it",
    )
    args = parser.parse_args()

    if args.remove:
        await revoke_pro(args.email)
    else:
        await grant_pro(args.email)


if __name__ == "__main__":
    asyncio.run(main())
