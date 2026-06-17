"""Create the Max plan + top-up pack products in Dodo and register them in Mongo.

In development this hits Dodo **test mode** (environment is derived from ``ENV``).
Idempotent: products already present in Mongo are skipped, so it's safe to re-run.

Run from apps/api:  uv run python scripts/credits_setup.py
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config.settings import settings
from app.constants.credits import CREDIT_TOPUP_EXPIRY_DAYS, CREDIT_TOPUP_PACKS
from app.db.mongodb.collections import credit_packs_collection, plans_collection
from app.services.payments.payment_service import payment_service

_CREDIT_ENTITLEMENT_NAME = "GAIA Credits"

# Max plan pricing (USD cents): $150/mo, $1,350/yr (25% off, matching Pro).
_MAX_PLANS = [
    ("monthly", 1, "Month", 15000),
    ("yearly", 1, "Year", 135000),
]
_MAX_FEATURES = [
    "1,000,000 credits/month",
    "Everything in Pro",
    "Highest daily limits",
    "Top up credits anytime",
]


def _create_product(name: str, price: dict[str, Any]) -> Any:
    return payment_service.client.products.create(name=name, price=price, tax_category="saas")


async def setup_topup_packs() -> None:
    for pack in CREDIT_TOPUP_PACKS:
        key = str(pack["key"])
        existing = await credit_packs_collection.find_one({"key": key})
        if existing and existing.get("dodo_product_id"):
            print(f"  pack '{key}' already set up ({existing['dodo_product_id']}) — skip")
            continue
        product = _create_product(
            name=f"GAIA {pack['name']}",
            price={
                "type": "one_time_price",
                "currency": "USD",
                "price": pack["price_cents"],
                "discount": 0,
                "purchasing_power_parity": False,
            },
        )
        await credit_packs_collection.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "dodo_product_id": product.product_id,
                    "credits": pack["credits"],
                    "price_cents": pack["price_cents"],
                    "name": pack["name"],
                    "is_active": True,
                    "updated_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        print(f"  created pack '{key}' -> {product.product_id}")


async def setup_max_plan() -> None:
    for duration, count, interval, amount in _MAX_PLANS:
        existing = await plans_collection.find_one({"name": "Max", "duration": duration})
        product_id = existing.get("dodo_product_id") if existing else None
        if product_id:
            print(f"  Max ({duration}) Dodo product exists ({product_id}) — syncing fields")
        else:
            product = _create_product(
                name=f"Max ({duration})",
                price={
                    "type": "recurring_price",
                    "currency": "USD",
                    "price": amount,
                    "discount": 0,
                    "purchasing_power_parity": False,
                    "payment_frequency_count": count,
                    "payment_frequency_interval": interval,
                    "subscription_period_count": count,
                    "subscription_period_interval": interval,
                },
            )
            product_id = product.product_id
            print(f"  created Max ({duration}) -> {product_id}")
        now = datetime.now(UTC)
        await plans_collection.update_one(
            {"name": "Max", "duration": duration},
            {
                "$set": {
                    "dodo_product_id": product_id,
                    "name": "Max",
                    "description": "For power users who live in GAIA.",
                    "amount": amount,
                    "currency": "USD",
                    "duration": duration,
                    "max_users": 1,
                    "features": _MAX_FEATURES,
                    "is_active": True,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )


async def setup_credit_entitlement() -> None:
    """Create the GAIA credit entitlement (Pool 2 system of record) if absent.

    The custom "credits" unit + 12-month expiry are owned by Dodo. Prints the
    entitlement id to set as ``DODO_CREDIT_ENTITLEMENT_ID``.
    """
    base = str(payment_service.client.base_url).rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.DODO_PAYMENTS_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
        existing = (await client.get("/credit-entitlements")).json().get("items", [])
        for ent in existing:
            if ent.get("name") == _CREDIT_ENTITLEMENT_NAME:
                print(f"  credit entitlement exists -> {ent['id']}")
                print(f"  set DODO_CREDIT_ENTITLEMENT_ID={ent['id']}")
                return
        resp = await client.post(
            "/credit-entitlements",
            json={
                "name": _CREDIT_ENTITLEMENT_NAME,
                "precision": 0,
                "unit": "credits",
                "rollover_enabled": False,
                "overage_enabled": False,
                "expires_after_days": CREDIT_TOPUP_EXPIRY_DAYS,
            },
        )
        resp.raise_for_status()
        entitlement_id = resp.json()["id"]
        print(f"  created credit entitlement -> {entitlement_id}")
        print(f"  set DODO_CREDIT_ENTITLEMENT_ID={entitlement_id}")


async def main() -> None:
    print("Setting up GAIA credit entitlement in Dodo...")
    await setup_credit_entitlement()
    print("Setting up top-up packs in Dodo...")
    await setup_topup_packs()
    print("Setting up Max plan in Dodo...")
    await setup_max_plan()
    await payment_service.invalidate_plans_cache()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
