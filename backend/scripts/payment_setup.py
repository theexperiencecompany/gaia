#!/usr/bin/env python3
"""
Complete Payment setup script for GAIA.
This script sets up subscription plans in the database using Dodo product IDs.

IMPORTANT: Run this script from the correct directory!

1. If running locally:
    cd /path/to/your/gaia/backend
    python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

2. If running inside Docker container:
    cd /app
    python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

3. Alternative Docker approach (set PYTHONPATH):
    PYTHONPATH=/app python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>

4. Run as module (from app directory):
    python -m scripts.payment_setup --monthly-product-id <id> --yearly-product-id <id>

Prerequisites:
- DODO_PAYMENTS_API_KEY must be available in Infisical secrets or as an environment variable.
  - The script will first attempt to fetch DODO_PAYMENTS_API_KEY from Infisical (if configured),
     and fallback to the environment variable or settings if not found.
- MongoDB connection string (MONGO_DB) must be configured
- Have your Dodo product IDs ready from your Dodo Payments dashboard

Usage:
     python payment_setup.py --monthly-product-id <product_id> --yearly-product-id <product_id>

Example:
     python payment_setup.py --monthly-product-id "xyz" --yearly-product-id "xyz"
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import os

# Ensure Infisical secrets are injected before importing settings
try:
    from app.config.secrets import inject_infisical_secrets

    inject_infisical_secrets()
    # Debug: Print Infisical ENV and credentials
    print(f"[DEBUG] ENV: {os.environ.get('ENV')}")
    print(f"[DEBUG] INFISICAL_PROJECT_ID: {os.environ.get('INFISICAL_PROJECT_ID')}")
    print(
        f"[DEBUG] INFISICAL_MACHINE_INDENTITY_CLIENT_ID: {os.environ.get('INFISICAL_MACHINE_INDENTITY_CLIENT_ID')}"
    )
    print(
        f"[DEBUG] INFISICAL_MACHINE_INDENTITY_CLIENT_SECRET: {os.environ.get('INFISICAL_MACHINE_INDENTITY_CLIENT_SECRET')}"
    )
    # Debug: Print if DODO_PAYMENTS_API_KEY is present after injection
    dodo_key = os.environ.get("DODO_PAYMENTS_API_KEY")
    if dodo_key:
        print(
            f"[DEBUG] DODO_PAYMENTS_API_KEY is present after Infisical injection (starts with: {dodo_key[:6]})"
        )
    else:
        print("[DEBUG] DODO_PAYMENTS_API_KEY is NOT present after Infisical injection")
except Exception as e:
    print(f"[WARN] Could not inject Infisical secrets: {e}")

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


from app.config.settings import settings  # noqa: E402
from app.models.payment_models import PlanDB  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def cleanup_old_indexes(collection):
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


async def setup_payment_plans(monthly_product_id: str, yearly_product_id: str):
    """Set up GAIA subscription plans in the database using Dodo product IDs."""
    print("🚀 GAIA Payment Setup")
    print("=" * 50)

    # Try to fetch DODO_PAYMENTS_API_KEY from Infisical-injected env, fallback to settings
    dodo_payments_api_key = os.environ.get("DODO_PAYMENTS_API_KEY") or getattr(
        settings, "DODO_PAYMENTS_API_KEY", None
    )
    if not dodo_payments_api_key:
        print(
            "❌ DODO_PAYMENTS_API_KEY not found in Infisical or environment variables/settings"
        )
        return False

    print(f"🔗 Using Dodo Payments API Key: {dodo_payments_api_key[:10]}...")
    print(f"📦 Monthly Product ID: {monthly_product_id}")
    print(f"📦 Yearly Product ID: {yearly_product_id}")
    print()

    # Define plans with their corresponding Dodo product IDs
    plans_data = [
        {
            "dodo_product_id": "",  # Free plan doesn't need Dodo product ID
            "name": "Free",
            "description": "Get started with GAIA for free",
            "amount": 0,
            "currency": "USD",
            "duration": "monthly",
            "max_users": 1,
            "features": [
                "Limited file uploads",
                "Limited calendar management",
                "Limited email actions",
                "Limited AI image generation",
                "Limited goal tracking",
                "Limited web search",
                "Limited deep research",
                "Limited todo operations",
                "Limited reminders",
                "Limited weather checks",
                "Limited webpage fetch",
                "Limited document generation",
                "Limited flowchart creation",
                "Limited code execution",
                "Limited Google Docs operations",
                "Basic memory features",
                "Standard support",
            ],
            "is_active": True,
        },
        {
            "dodo_product_id": monthly_product_id,  # Monthly plan
            "name": "GAIA Pro",
            "description": "For productivity nerds - billed monthly",
            "amount": 1500,  # $15.00 in cents
            "currency": "USD",
            "duration": "monthly",
            "max_users": 1,
            "features": [
                "Extended file uploads",
                "Extended calendar management",
                "Extended email actions",
                "Extended AI image generation",
                "Extended goal tracking",
                "Extended web search",
                "Extended deep research",
                "Extended todo operations",
                "Extended reminders",
                "Extended weather checks",
                "Extended webpage fetch",
                "Extended document generation",
                "Extended flowchart creation",
                "Extended code execution",
                "Extended Google Docs operations",
                "Advanced memory features",
                "Private Discord channels",
                "Priority support",
            ],
            "is_active": True,
        },
        {
            "dodo_product_id": yearly_product_id,  # Yearly plan
            "name": "GAIA Pro",
            "description": "For productivity nerds - billed annually (save 3 months - $45 off!)",
            "amount": 13500,  # $135.00 in cents (3 months free)
            "currency": "USD",
            "duration": "yearly",
            "max_users": 1,
            "features": [
                "Extended file uploads",
                "Extended calendar management",
                "Extended email actions",
                "Extended AI image generation",
                "Extended goal tracking",
                "Extended web search",
                "Extended deep research",
                "Extended todo operations",
                "Extended reminders",
                "Extended weather checks",
                "Extended webpage fetch",
                "Extended document generation",
                "Extended flowchart creation",
                "Extended code execution",
                "Extended Google Docs operations",
                "Advanced memory features",
                "Private Discord channels",
                "Priority support",
                "🎉 3 months FREE - Save $45",
            ],
            "is_active": True,
        },
    ]

    # Connect to database
    client = None
    try:
        client = AsyncIOMotorClient(settings.MONGO_DB)
        db = client["GAIA"]
        collection = db["subscription_plans"]

        # Clean up old payment gateway indexes first
        await cleanup_old_indexes(collection)

        print("📊 Setting up subscription plans...")
        print()

        created_count = 0
        updated_count = 0

        for plan_item in plans_data:
            try:
                plan_name = plan_item["name"]
                plan_duration: str = plan_item["duration"]
                dodo_product_id = plan_item["dodo_product_id"]

                print(f"⚙️  Processing: {plan_name} ({plan_duration.capitalize()})")

                # Check if plan already exists
                existing_plan = await collection.find_one(
                    {
                        "name": plan_name,
                        "duration": plan_duration,
                    }
                )

                plan_doc = PlanDB.model_validate(
                    {
                        "dodo_product_id": dodo_product_id,
                        "name": plan_item["name"],
                        "description": plan_item["description"],
                        "amount": plan_item["amount"],
                        "currency": plan_item["currency"],
                        "duration": plan_item["duration"],
                        "max_users": plan_item["max_users"],
                        "features": plan_item["features"],
                        "is_active": plan_item["is_active"],
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                )

                if existing_plan:
                    # Update existing plan
                    await collection.update_one(
                        {"_id": existing_plan["_id"]},
                        {
                            "$set": plan_doc.model_dump(
                                by_alias=True, exclude={"id", "created_at"}
                            )
                        },
                    )
                    updated_count += 1
                    print("   ✅ Updated existing plan")
                else:
                    # Insert new plan
                    await collection.insert_one(
                        plan_doc.model_dump(by_alias=True, exclude={"id"})
                    )
                    created_count += 1
                    print("   ✅ Created new plan")

                print(
                    f"   💰 Amount: ${int(plan_item['amount']) / 100:.2f} {plan_item['currency']}"
                )
                print(f"   📅 Duration: {plan_duration.capitalize()}")
                print(f"   👥 Max Users: {plan_item['max_users']}")
                print(
                    f"   🏷️  Dodo Product ID: {dodo_product_id or 'Free Plan (No Product ID)'}"
                )
                print(f"   🎯 Features: {len(list(plan_item['features']))} features")
                print()

            except Exception as e:
                print(f"   ❌ Error processing {plan_item['name']}: {e}")

        print("=" * 50)
        print("📈 Setup Summary:")
        print(f"   • Created: {created_count} plans")
        print(f"   • Updated: {updated_count} plans")
        print(f"   • Total: {created_count + updated_count} plans processed")
        print()

        # Display final plan list
        plans_cursor = collection.find({"is_active": True}).sort("amount", 1)
        plans = await plans_cursor.to_list(length=None)

        print("📋 Active Plans:")
        for plan in plans:
            print(
                f"   • {plan['name']} ({plan['duration']}) - ${plan['amount'] / 100:.2f}"
            )
            print(f"     Dodo Product ID: {plan.get('dodo_product_id') or 'N/A'}")

        print()
        print("✅ Payment system setup complete!")
        print("🔗 Frontend can now fetch plans via GET /api/v1/payments/plans")
        print(
            "🎯 Users can create subscriptions via POST /api/v1/payments/subscriptions"
        )

        return True

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return False
    finally:
        if client:
            client.close()
            print("🔌 Database connection closed")


async def main():
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

    args = parser.parse_args()

    try:
        await setup_payment_plans(args.monthly_product_id, args.yearly_product_id)
        print("\n🎉 Payment setup completed successfully!")
    except Exception as e:
        print(f"\n💥 Setup failed with error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
