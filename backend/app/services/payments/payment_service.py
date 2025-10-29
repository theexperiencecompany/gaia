"""
Streamlined Dodo Payments integration service.
Clean, simple, and maintainable.
"""

from typing import Any, Dict, List

from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import (
    plans_collection,
    subscriptions_collection,
    users_collection,
)
from app.db.redis import redis_cache
from app.db.utils import serialize_document
from app.models.payment_models import (
    PlanResponse,
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.utils.email_utils import send_pro_subscription_email
from bson import ObjectId
from dodopayments import DodoPayments
from fastapi import HTTPException


class DodoPaymentService:
    """Streamlined Dodo Payments service."""

    def __init__(self):
        try:
            environment = "live_mode" if settings.ENV == "production" else "test_mode"

            self.client = DodoPayments(
                bearer_token=settings.DODO_PAYMENTS_API_KEY,
                environment=environment,
            )
        except Exception as e:
            logger.error(f"Failed to instantiate dodo payments: {e}")

    async def get_plans(self, active_only: bool = True) -> List[PlanResponse]:
        """Get subscription plans with caching."""
        cache_key = f"plans:{'active' if active_only else 'all'}"

        # Try cache first
        cached = await redis_cache.get(cache_key)
        if cached:
            try:
                # Try to create PlanResponse objects from cached data
                plan_responses = []
                for plan_data in cached:
                    # Ensure dodo_product_id exists in cached data
                    if "dodo_product_id" not in plan_data:
                        plan_data["dodo_product_id"] = ""
                    plan_responses.append(PlanResponse(**plan_data))
                return plan_responses
            except Exception:
                # If cached data is incompatible, clear cache and fetch fresh
                await redis_cache.delete(cache_key)

        # Fetch from database
        query = {"is_active": True} if active_only else {}
        plans = await plans_collection.find(query).sort("amount", 1).to_list(None)

        plan_responses = [
            PlanResponse(
                id=str(plan["_id"]),
                dodo_product_id=plan.get("dodo_product_id", ""),
                name=plan["name"],
                description=plan.get("description"),
                amount=plan["amount"],
                currency=plan["currency"],
                duration=plan["duration"],
                max_users=plan.get("max_users"),
                features=plan.get("features", []),
                is_active=plan["is_active"],
                created_at=plan["created_at"],
                updated_at=plan["updated_at"],
            )
            for plan in plans
        ]

        # Cache result
        await redis_cache.set(cache_key, [plan.model_dump() for plan in plan_responses])
        return plan_responses

    async def create_subscription(
        self, user_id: str, product_id: str, quantity: int = 1
    ) -> Dict[str, Any]:
        """Create subscription - only get payment link, store data after webhook."""
        # Get user
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(404, "User not found")

        # Check for existing active subscription
        existing = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}
        )
        if existing:
            raise HTTPException(409, "Active subscription exists")

        # Create with Dodo - get payment link only
        try:
            subscription = self.client.subscriptions.create(
                billing={
                    "city": "N/A",
                    "country": "IN",
                    "state": "N/A",
                    "street": "N/A",
                    "zipcode": "000000",
                },
                customer={
                    "email": user.get("email"),
                    "name": user.get("first_name") or user.get("name", "User"),
                },
                product_id=product_id,
                quantity=quantity,
                payment_link=True,
                return_url=f"{settings.FRONTEND_URL}/payment/success",
                metadata={"user_id": user_id, "product_id": product_id},
            )
        except Exception as e:
            raise HTTPException(502, f"Payment service error: {str(e)}")

        # Return payment link without storing in database
        return {
            "subscription_id": subscription.subscription_id,
            "payment_link": getattr(subscription, "payment_link", None),
            "status": "payment_link_created",
        }

    async def verify_payment_completion(self, user_id: str) -> Dict[str, Any]:
        """Check payment completion status from webhook data."""
        subscription = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}, sort=[("created_at", -1)]
        )

        if not subscription:
            return {
                "payment_completed": False,
                "message": "No active subscription found",
            }

        # Send welcome email (don't fail if email fails)
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user and user.get("email"):
                await send_pro_subscription_email(
                    user_name=user.get("first_name", "User"),
                    user_email=user["email"],
                )
        except Exception:
            pass  # Email failure shouldn't break payment verification

        return {
            "payment_completed": True,
            "subscription_id": subscription["dodo_subscription_id"],
            "message": "Payment completed",
        }

    async def get_user_subscription_status(
        self, user_id: str
    ) -> UserSubscriptionStatus:
        """Get user subscription status."""
        subscription = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}
        )

        if not subscription:
            return UserSubscriptionStatus(
                user_id=user_id,
                current_plan=None,
                subscription=None,
                is_subscribed=False,
                days_remaining=None,
                can_upgrade=True,
                can_downgrade=False,
                has_subscription=False,
                plan_type=PlanType.FREE,
                status=SubscriptionStatus.PENDING,
            )

        # Get plan details
        try:
            plans = await self.get_plans(active_only=False)
            plan = next(
                (
                    p
                    for p in plans
                    if p.dodo_product_id == subscription.get("product_id")
                ),
                None,
            )
        except Exception:
            plan = None

        return UserSubscriptionStatus(
            user_id=user_id,
            current_plan=plan.model_dump() if plan else None,
            subscription=serialize_document(subscription),
            is_subscribed=True,
            days_remaining=None,
            can_upgrade=True,
            can_downgrade=True,
            has_subscription=True,
            plan_type=PlanType.PRO,
            status=SubscriptionStatus(subscription["status"]),
        )


payment_service = DodoPaymentService()
