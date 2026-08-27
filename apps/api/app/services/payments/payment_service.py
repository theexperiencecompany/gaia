"""
Streamlined Dodo Payments integration service.
Clean, simple, and maintainable.
"""

import asyncio
from typing import Any, Literal

from dodopayments import DodoPayments
from fastapi import HTTPException

from app.config.settings import settings
from app.constants.cache import (
    ACTIVE_PLANS_CACHE_KEY,
    ALL_PLANS_CACHE_KEY,
    SUBSCRIPTION_PLAN_CACHE_PREFIX,
    SUBSCRIPTION_PLAN_CACHE_TTL,
    UPGRADE_LINK_CACHE_PREFIX,
    UPGRADE_LINK_CACHE_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.payments import PAYMENT_HISTORY_LIMIT
from app.db.redis import redis_cache
from app.db.repositories.plans import plan_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import (
    CreateSubscriptionResponse,
    PaymentHistoryEntry,
    PaymentVerificationResponse,
    PlanDuration,
    PlanResponse,
    PlanType,
    ProCheckout,
    SubscriptionDetails,
    SubscriptionDocument,
    SubscriptionStatus,
    SubscriptionUpdate,
    UserSubscriptionStatus,
)
from app.services.email import send_pro_subscription_email
from shared.py.wide_events import log


class DodoPaymentService:
    """Streamlined Dodo Payments service."""

    def __init__(self) -> None:
        try:
            environment: Literal["live_mode", "test_mode"] = (
                "live_mode" if settings.ENV == "production" else "test_mode"
            )

            # DODO_PAYMENTS_BASE_URL lets the SDK point at a non-default
            # endpoint (a stub or sandbox mirror) instead of the real API —
            # the same override pattern the LLM client uses. When set it wins
            # over the environment-derived URL; the SDK requires the
            # `environment` arg be omitted in that case.
            if settings.DODO_PAYMENTS_BASE_URL:
                self.client = DodoPayments(
                    bearer_token=settings.DODO_PAYMENTS_API_KEY,
                    base_url=settings.DODO_PAYMENTS_BASE_URL,
                )
            else:
                self.client = DodoPayments(
                    bearer_token=settings.DODO_PAYMENTS_API_KEY,
                    environment=environment,
                )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Failed to instantiate dodo payments",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def get_plans(self, active_only: bool = True) -> list[PlanResponse]:
        """Get subscription plans with caching."""
        cache_key = ACTIVE_PLANS_CACHE_KEY if active_only else ALL_PLANS_CACHE_KEY

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
        plans = await plan_repository.list_plans(active_only=active_only)

        plan_responses = [
            PlanResponse(
                id=plan.id,
                dodo_product_id=plan.dodo_product_id or "",
                name=plan.name,
                description=plan.description,
                amount=plan.amount,
                currency=plan.currency,
                duration=plan.duration,
                max_users=plan.max_users,
                features=plan.features,
                is_active=plan.is_active,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
            )
            for plan in plans
        ]

        # Cache result
        await redis_cache.set(cache_key, [plan.model_dump() for plan in plan_responses])
        return plan_responses

    async def create_subscription(
        self,
        user_id: str,
        product_id: str,
        quantity: int = 1,
        discount_code: str | None = None,
    ) -> CreateSubscriptionResponse:
        """Create subscription via Checkout Sessions; show promo code field and get hosted checkout url."""
        log.set(payment={"event_type": "create_subscription", "status": "initiated"})

        # Get user
        user = await user_repository.get(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        # Check for existing active subscription
        existing = await subscription_repository.get_active_for_user(user_id)
        if existing:
            raise HTTPException(409, "Active subscription exists")

        # Create hosted checkout session (preferred over deprecated subscriptions.create)
        try:
            params: dict[str, Any] = {
                "product_cart": [
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                    }
                ],
                "customer": {
                    "email": user.email,
                    "name": user.first_name or user.name or "User",
                },
                "feature_flags": {
                    # This renders the promo/discount code input on the hosted page
                    "allow_discount_code": True,
                    # Allow customers to change their billing address country
                    "allow_customer_editing_country": True,
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

            # The Dodo SDK's client is synchronous — run it off the event loop so a
            # slow HTTP round-trip doesn't stall other requests.
            checkout_session = await asyncio.to_thread(
                self.client.checkout_sessions.create, **params
            )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Error creating Dodo checkout session",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise HTTPException(502, f"Payment service error: {e!s}")

        # Look up plan name for richer logging
        plan_name: str | None = None
        try:
            plans = await self.get_plans(active_only=False)
            matched_plan = next((p for p in plans if p.dodo_product_id == product_id), None)
            if matched_plan:
                plan_name = matched_plan.name
        except Exception as e:  # nosec B110
            log.warning(f"{LogTag.PAYMENT} Failed to resolve plan name for logging", error=str(e))

        log.set(
            payment={
                "subscription_id": checkout_session.session_id,
                "plan_name": plan_name,
                "status": "created",
                "provider": "dodo",
            }
        )

        return CreateSubscriptionResponse(
            subscription_id=checkout_session.session_id,
            payment_link=checkout_session.checkout_url,
            status="payment_link_created",
        )

    async def cancel_subscription(self, user_id: str) -> UserSubscriptionStatus:
        """Cancel the user's subscription in Dodo and mirror it locally.

        Cancels at the end of the current billing period (``cancel_at_next_billing_date``)
        so the user keeps Pro access until the period ends — matching the Terms'
        auto-renewal promise. Dodo returns the updated subscription; the local
        row is synced with it.
        """
        subscription = await subscription_repository.get_active_for_user(user_id)
        if not subscription:
            raise HTTPException(404, "No active subscription to cancel")

        if not subscription.dodo_subscription_id:
            raise HTTPException(400, "Subscription has no Dodo id to cancel")

        try:
            # The Dodo SDK's client is synchronous — run it off the event loop
            # so a slow HTTP round-trip doesn't stall other requests.
            updated = await asyncio.to_thread(
                self.client.subscriptions.update,
                subscription.dodo_subscription_id,
                cancel_at_next_billing_date=True,
            )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Error cancelling subscription in Dodo",
                error_type=type(e).__name__,
                error=str(e),
            )
            raise HTTPException(502, f"Payment service error: {e!s}")

        # Mirror Dodo's authoritative state locally. cancelled_at is only set
        # when Dodo supplied one — leaving it unset keeps it out of the $set.
        update = SubscriptionUpdate(status=updated.status, cancel_at_next_billing_date=True)
        if updated.cancelled_at:
            update.cancelled_at = updated.cancelled_at.isoformat()
        if updated.next_billing_date:
            update.next_billing_date = updated.next_billing_date.isoformat()

        updated_local = await subscription_repository.apply_update_by_dodo_id(
            subscription.dodo_subscription_id, update
        )
        if not updated_local:
            # Dodo accepted the cancellation but no local row matched — surfacing
            # success here would leave the user's status stale and silently drop
            # the change. Fail loud so it gets attention instead of looking done.
            log.error(
                f"{LogTag.PAYMENT} Cancellation not mirrored locally; no subscription row matched",
                dodo_subscription_id=subscription.dodo_subscription_id,
                user_id=user_id,
            )
            raise HTTPException(
                502,
                "Cancellation processed by Dodo but could not be recorded locally",
            )
        await self.invalidate_plan_cache_by_dodo_id(subscription.dodo_subscription_id)

        return await self.get_user_subscription_status(user_id)

    async def verify_payment_completion(self, user_id: str) -> PaymentVerificationResponse:
        """Check payment completion status from webhook data."""
        subscription = await subscription_repository.get_latest_active_for_user(user_id)

        if not subscription:
            return PaymentVerificationResponse(
                payment_completed=False,
                message="No active subscription found",
            )

        # Send welcome email (don't fail if email fails)
        try:
            user = await user_repository.get(user_id)
            if user and user.email:
                await send_pro_subscription_email(
                    user_name=user.first_name or "User",
                    user_email=user.email,
                )
        except Exception as e:
            log.debug(
                f"{LogTag.PAYMENT} Failed to send welcome email",
                error=str(e),
                error_type=type(e).__name__,
            )

        return PaymentVerificationResponse(
            payment_completed=True,
            subscription_id=subscription.dodo_subscription_id,
            message="Payment completed",
        )

    async def get_user_subscription_status(self, user_id: str) -> UserSubscriptionStatus:
        """Get user subscription status."""
        subscription = await subscription_repository.get_active_for_user(user_id)

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

        plan = await self._plan_for_subscription(subscription)

        return UserSubscriptionStatus(
            user_id=user_id,
            current_plan=plan.model_dump() if plan else None,
            subscription=subscription.model_dump(mode="json"),
            is_subscribed=True,
            days_remaining=None,
            can_upgrade=True,
            can_downgrade=True,
            has_subscription=True,
            plan_type=PlanType.PRO,
            status=SubscriptionStatus(subscription.status),
        )

    async def _plan_for_subscription(
        self, subscription: SubscriptionDocument
    ) -> PlanResponse | None:
        """The catalogue entry this subscription was bought from, if it still exists.

        The catalogue is decoration on top of the authoritative subscription row —
        the user is subscribed whether or not their plan can be resolved — so a
        catalogue read that fails degrades to "no plan details" instead of taking
        the whole status lookup down. It is logged, never swallowed.
        """
        try:
            plans = await self.get_plans(active_only=False)
        except Exception as e:
            # Bounded fields, not provider error text: the warning stays
            # queryable without persisting unbounded upstream payloads.
            log.warning(
                f"{LogTag.PAYMENT} Could not resolve the plan behind a subscription",
                dodo_subscription_id=subscription.dodo_subscription_id,
                failure_reason="plan_resolution_failed",
                error_type=type(e).__name__,
            )
            return None
        return next((p for p in plans if p.dodo_product_id == subscription.product_id), None)

    async def get_pro_plan(self, billing_cycle: PlanDuration) -> PlanResponse:
        """The purchasable Pro plan for this billing cycle.

        Identified by shape rather than by name: Free and Enterprise are both
        priced at 0 with no Dodo product, so the one active plan that costs money
        and has a product id for a given cycle IS Pro (``PlanType`` has no other
        paid tier).
        """
        plans = await self.get_plans(active_only=True)
        plan = next(
            (
                candidate
                for candidate in plans
                if candidate.duration == billing_cycle
                and candidate.amount > 0
                and candidate.dodo_product_id
            ),
            None,
        )
        if plan is None:
            log.error(
                f"{LogTag.PAYMENT} No purchasable plan in the catalogue",
                billing_cycle=billing_cycle,
                active_plans=len(plans),
            )
            raise HTTPException(500, f"No purchasable {billing_cycle} plan is configured")
        return plan

    async def create_pro_checkout(
        self, user_id: str, billing_cycle: PlanDuration = PlanDuration.MONTHLY
    ) -> ProCheckout:
        """Mint (or reuse) a hosted checkout session that upgrades this user to Pro.

        Cached for an hour per user and cycle so asking twice — or hitting a usage
        wall repeatedly — reuses one session instead of stranding a new one in Dodo
        each time. The plan is cached alongside the session so a cached hit quotes
        the price the session was minted under, never a newer catalogue read.
        """
        cache_key = f"{UPGRADE_LINK_CACHE_PREFIX}{user_id}:{billing_cycle}"
        cached = await redis_cache.get(cache_key)
        if isinstance(cached, dict) and "plan" in cached and "checkout" in cached:
            return ProCheckout(
                plan=PlanResponse.model_validate(cached["plan"]),
                checkout=CreateSubscriptionResponse.model_validate(cached["checkout"]),
            )

        plan = await self.get_pro_plan(billing_cycle)
        checkout = await self.create_subscription(user_id, plan.dodo_product_id)
        await redis_cache.set(
            cache_key,
            {"plan": plan.model_dump(), "checkout": checkout.model_dump()},
            ttl=UPGRADE_LINK_CACHE_TTL,
        )
        return ProCheckout(plan=plan, checkout=checkout)

    async def get_payment_history(
        self, user_id: str, limit: int = PAYMENT_HISTORY_LIMIT
    ) -> list[PaymentHistoryEntry]:
        """This user's charges, newest first.

        Dodo is the ledger — nothing local records individual charges — so this
        reads ``payments.list`` for every subscription the user has ever had,
        including cancelled and expired ones.
        """
        subscriptions = await subscription_repository.list_for_user(user_id)
        dodo_ids = [sub.dodo_subscription_id for sub in subscriptions if sub.dodo_subscription_id]
        if not dodo_ids:
            return []

        pages = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.client.payments.list, subscription_id=dodo_id, page_size=limit
                )
                for dodo_id in dodo_ids
            )
        )
        entries = [
            PaymentHistoryEntry(
                payment_id=payment.payment_id,
                status=payment.status,
                amount=payment.total_amount,
                currency=payment.currency,
                created_at=payment.created_at,
                payment_method=payment.payment_method,
            )
            for page in pages
            for payment in page.items
        ]
        entries.sort(key=lambda entry: entry.created_at, reverse=True)
        return entries[:limit]

    async def get_subscription_details(
        self, user_id: str, history_limit: int = PAYMENT_HISTORY_LIMIT
    ) -> SubscriptionDetails:
        """Plan, billing state, and recent charges — the flattened view GAIA reads."""
        subscription = await subscription_repository.get_active_for_user(user_id)
        if not subscription:
            # No ACTIVE subscription — but a former subscriber's charges still
            # live in Dodo under their cancelled/expired subscription ids, so the
            # ledger is read before declaring this user plain free.
            payments = await self.get_payment_history(user_id, history_limit)
            return SubscriptionDetails(
                plan_type=PlanType.FREE, is_subscribed=False, payments=payments
            )

        plan = await self._plan_for_subscription(subscription)
        payments = await self.get_payment_history(user_id, history_limit)

        return SubscriptionDetails(
            plan_type=PlanType.PRO,
            is_subscribed=True,
            status=SubscriptionStatus(subscription.status),
            plan_name=plan.name if plan else None,
            amount=plan.amount if plan else None,
            currency=plan.currency if plan else None,
            billing_cycle=plan.duration if plan else None,
            next_billing_date=subscription.next_billing_date,
            cancel_at_next_billing_date=bool(subscription.cancel_at_next_billing_date),
            payments=payments,
        )

    async def get_cached_plan_type(self, user_id: str) -> PlanType:
        """Plan tier, Redis-cached for hot paths; eventually consistent within the TTL."""
        cache_key = f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}"
        cached = await redis_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("plan_type"):
            return PlanType(cached["plan_type"])

        plan_raw = (await self.get_user_subscription_status(user_id)).plan_type or PlanType.FREE
        # Pydantic v2 coerces str, Enum fields to plain strings; normalize before calling .value
        plan = plan_raw if isinstance(plan_raw, PlanType) else PlanType(plan_raw)
        await redis_cache.set(cache_key, {"plan_type": plan.value}, ttl=SUBSCRIPTION_PLAN_CACHE_TTL)
        return plan

    async def invalidate_plan_cache_by_dodo_id(self, dodo_subscription_id: str) -> None:
        """Drop the cached plan tier after a subscription change (applies immediately)."""
        if not dodo_subscription_id:
            return
        user_id = await subscription_repository.get_user_id_by_dodo_id(dodo_subscription_id)
        if user_id:
            await redis_cache.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}")


payment_service = DodoPaymentService()
