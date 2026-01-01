"""
Streamlined Dodo Payments integration service.
Clean, simple, and maintainable.
"""

import time
from typing import Any, Dict, List, Optional

from app.config.loggers import app_logger as logger, get_current_event
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
            logger.info(
                "payment_service_initialized",
                environment=environment,
            )
        except Exception as e:
            logger.error(
                "payment_service_init_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def get_plans(self, active_only: bool = True) -> List[PlanResponse]:
        """Get subscription plans with caching."""
        start_time = time.time()
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

                # Enrich wide event with cache hit
                wide_event = get_current_event()
                if wide_event:
                    wide_event.set_cache_result(hit=True, key=cache_key)

                logger.debug(
                    "plans_cache_hit",
                    cache_key=cache_key,
                    plan_count=len(plan_responses),
                    duration_ms=(time.time() - start_time) * 1000,
                )
                return plan_responses
            except Exception:
                # If cached data is incompatible, clear cache and fetch fresh
                await redis_cache.delete(cache_key)

        # Enrich wide event with cache miss
        wide_event = get_current_event()
        if wide_event:
            wide_event.set_cache_result(hit=False, key=cache_key)

        # Fetch from database
        db_start = time.time()
        query = {"is_active": True} if active_only else {}
        plans = await plans_collection.find(query).sort("amount", 1).to_list(None)
        db_duration_ms = (time.time() - db_start) * 1000

        if wide_event:
            wide_event.add_db_query(db_duration_ms)

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

        logger.info(
            "plans_fetched",
            active_only=active_only,
            plan_count=len(plan_responses),
            db_query_ms=db_duration_ms,
            total_duration_ms=(time.time() - start_time) * 1000,
        )
        return plan_responses

    async def create_subscription(
        self,
        user_id: str,
        product_id: str,
        quantity: int = 1,
        discount_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create subscription via Checkout Sessions; show promo code field and get hosted checkout url."""
        start_time = time.time()

        logger.info(
            "subscription_creation_started",
            user_id=user_id,
            product_id=product_id,
            quantity=quantity,
            has_discount_code=bool(discount_code),
        )

        # Enrich wide event
        wide_event = get_current_event()
        if wide_event:
            wide_event.set_operation(
                operation="create_subscription",
                resource_type="subscription",
            )
            wide_event.set_business_context(
                product_id=product_id,
                quantity=quantity,
                has_discount_code=bool(discount_code),
            )

        # Get user
        db_start = time.time()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if wide_event:
            wide_event.add_db_query((time.time() - db_start) * 1000)

        if not user:
            logger.warning(
                "subscription_user_not_found",
                user_id=user_id,
            )
            raise HTTPException(404, "User not found")

        # Check for existing active subscription
        db_start = time.time()
        existing = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}
        )
        if wide_event:
            wide_event.add_db_query((time.time() - db_start) * 1000)

        if existing:
            logger.warning(
                "subscription_already_exists",
                user_id=user_id,
                existing_subscription_id=str(existing.get("_id")),
            )
            raise HTTPException(409, "Active subscription exists")

        # Create hosted checkout session (preferred over deprecated subscriptions.create)
        try:
            external_start = time.time()
            params: Dict[str, Any] = {
                "product_cart": [
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                    }
                ],
                "customer": {
                    "email": user.get("email"),
                    "name": user.get("first_name") or user.get("name", "User"),
                },
                "billing_address": {
                    "country": "IN",
                },
                "feature_flags": {
                    # This renders the promo/discount code input on the hosted page
                    "allow_discount_code": True,
                },
                "return_url": f"{settings.FRONTEND_URL}/payment/success",
                "metadata": {"user_id": user_id, "product_id": product_id},
                "subscription_data": {
                    # Use product's stored price; override trial if needed
                },
            }
            if discount_code:
                # Pre-apply a known discount (customer can still edit it on the page)
                params["discount_code"] = discount_code

            checkout_session = self.client.checkout_sessions.create(**params)
            external_duration_ms = (time.time() - external_start) * 1000

            if wide_event:
                wide_event.add_external_call(external_duration_ms)

            logger.info(
                "subscription_checkout_created",
                user_id=user_id,
                product_id=product_id,
                session_id=checkout_session.session_id,
                external_call_ms=external_duration_ms,
                total_duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(
                "subscription_checkout_failed",
                user_id=user_id,
                product_id=product_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise HTTPException(502, f"Payment service error: {str(e)}")

        return {
            "subscription_id": checkout_session.session_id,
            "payment_link": checkout_session.checkout_url,
            "status": "payment_link_created",
        }

    async def verify_payment_completion(self, user_id: str) -> Dict[str, Any]:
        """Check payment completion status from webhook data."""
        start_time = time.time()

        db_start = time.time()
        subscription = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}, sort=[("created_at", -1)]
        )
        db_duration_ms = (time.time() - db_start) * 1000

        wide_event = get_current_event()
        if wide_event:
            wide_event.add_db_query(db_duration_ms)
            wide_event.set_operation(
                operation="verify_payment",
                resource_type="subscription",
            )

        if not subscription:
            logger.info(
                "payment_verification_no_subscription",
                user_id=user_id,
                duration_ms=(time.time() - start_time) * 1000,
            )
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
                logger.info(
                    "welcome_email_sent",
                    user_id=user_id,
                    email=user.get("email"),
                )
        except Exception as e:
            logger.warning(
                "welcome_email_failed",
                user_id=user_id,
                error=str(e),
            )

        logger.info(
            "payment_verified",
            user_id=user_id,
            subscription_id=subscription.get("dodo_subscription_id"),
            duration_ms=(time.time() - start_time) * 1000,
        )

        return {
            "payment_completed": True,
            "subscription_id": subscription["dodo_subscription_id"],
            "message": "Payment completed",
        }

    async def get_user_subscription_status(
        self, user_id: str
    ) -> UserSubscriptionStatus:
        """Get user subscription status."""
        start_time = time.time()

        db_start = time.time()
        subscription = await subscriptions_collection.find_one(
            {"user_id": user_id, "status": "active"}
        )
        db_duration_ms = (time.time() - db_start) * 1000

        wide_event = get_current_event()
        if wide_event:
            wide_event.add_db_query(db_duration_ms)

        if not subscription:
            logger.debug(
                "subscription_status_free",
                user_id=user_id,
                duration_ms=(time.time() - start_time) * 1000,
            )
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
        except Exception as e:
            logger.warning(
                "plan_lookup_failed",
                user_id=user_id,
                product_id=subscription.get("product_id"),
                error=str(e),
            )
            plan = None

        logger.debug(
            "subscription_status_active",
            user_id=user_id,
            plan_type=PlanType.PRO.value,
            plan_name=plan.name if plan else None,
            duration_ms=(time.time() - start_time) * 1000,
        )

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
