"""
Streamlined Dodo Payments integration service.
Clean, simple, and maintainable.
"""

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from dodopayments import DodoPayments, NotFoundError
from dodopayments.types import Subscription
from fastapi import HTTPException

from app.config.settings import settings
from app.constants.cache import (
    ACTIVE_PLANS_CACHE_KEY,
    ALL_PLANS_CACHE_KEY,
    CHECKOUT_SCAN_MISS_CACHE_PREFIX,
    CHECKOUT_SCAN_MISS_TTL,
    SUBSCRIPTION_PLAN_CACHE_PREFIX,
    SUBSCRIPTION_PLAN_CACHE_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.payments import (
    CHECKOUT_SESSION_SCAN_LIMIT,
    DODO_TEST_MODE_BILLING_ADDRESS,
    DODO_TEST_MODE_PHONE_NUMBER,
    PAYMENT_HISTORY_LIMIT,
)
from app.db.redis import redis_cache
from app.db.repositories.checkout_sessions import checkout_session_repository
from app.db.repositories.plans import plan_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import (
    PAYMENT_RESULT_PATH,
    CheckoutSessionDocument,
    CheckoutSource,
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
    UserSubscriptionStatus,
)
from app.models.webhook_models import DodoSubscriptionData
from app.services.payments.plan_cache import invalidate_plan_cache
from app.services.payments.subscription_events import (
    SubscriptionEvent,
    SubscriptionEventKind,
    SubscriptionEventOutcome,
    apply_subscription_event,
    resolve_subscription_owner,
)
from shared.py.wide_events import log


class CheckoutScanOutcome(StrEnum):
    """Why a verify found no subscription behind the user's checkout sessions.

    Only ``MISS`` — every session answered, none paid — is cached; the other
    two are exactly what the client's next retry should ask about again.
    """

    MISS = "miss"
    CACHED_MISS = "cached_miss"
    INCONCLUSIVE = "inconclusive"


def _is_free_plan(name: str, amount: int) -> bool:
    """GAIA is paid-only — the seeded Free row (``amount=0``, ``name="Free"``)
    must never reach the frontend. ``amount`` alone would also catch Enterprise
    ($0, contact-sales), so both must match."""
    return amount == 0 and name.strip().lower() == PlanType.FREE.value


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
                return [
                    plan for plan in plan_responses if not _is_free_plan(plan.name, plan.amount)
                ]
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

        # Cache result — full catalogue, including the free row, so the cache
        # stays a faithful mirror of the DB; the free row is filtered on every
        # read path instead (see the cache-hit branch above).
        await redis_cache.set(cache_key, [plan.model_dump() for plan in plan_responses])
        return [plan for plan in plan_responses if not _is_free_plan(plan.name, plan.amount)]

    async def create_subscription(
        self,
        user_id: str,
        product_id: str,
        quantity: int = 1,
        discount_code: str | None = None,
        return_path: str = PAYMENT_RESULT_PATH,
    ) -> CreateSubscriptionResponse:
        """Create subscription via Checkout Sessions; show promo code field and get hosted checkout url.

        ``return_path`` is where Dodo sends the browser afterwards, relative to
        the frontend origin; the caller derives it from the checkout's source.
        """
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
                "return_url": f"{settings.FRONTEND_URL}{return_path}",
                "metadata": {"user_id": user_id, "product_id": product_id},
                "subscription_data": {
                    # Use product's stored price; override trial if needed
                },
            }
            if discount_code:
                # Pre-apply a known discount (customer can still edit it on the page)
                params["discount_code"] = discount_code
            if settings.ENV == "development":
                # Opt-in for local development only: everything but the card is
                # filled in, and a card used once is offered back as a saved
                # method, so a developer pays in one click after the first run.
                # Nothing here is sent unless the environment says development.
                params["billing_address"] = dict(DODO_TEST_MODE_BILLING_ADDRESS)
                params["customer"]["phone_number"] = DODO_TEST_MODE_PHONE_NUMBER
                params["show_saved_payment_methods"] = True

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
            raise HTTPException(502, f"Payment service error: {e!s}") from e

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

        # Record the checkout session so the result page can resolve the
        # purchase against Dodo even when the subscription.active webhook has
        # not landed yet (the webhook-vs-redirect race). The webhook stays the
        # authoritative path; losing this record only disables that fallback.
        try:
            await checkout_session_repository.create(
                CheckoutSessionDocument(
                    session_id=checkout_session.session_id,
                    user_id=user_id,
                    product_id=product_id,
                    created_at=datetime.now(UTC),
                )
            )
        except Exception as e:
            log.error(
                f"{LogTag.PAYMENT} Failed to record checkout session",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                session_id=checkout_session.session_id,
            )
        # "None of this user's sessions is paid" was judged against the
        # sessions that existed; this one is not among them.
        await redis_cache.delete(f"{CHECKOUT_SCAN_MISS_CACHE_PREFIX}{user_id}")

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
            raise HTTPException(502, f"Payment service error: {e!s}") from e

        # Recorded as the scheduled cancel that was asked for, whatever status
        # Dodo reports back: the same reducer the webhook goes through keeps
        # the user on Pro until ``subscription.expired``, and the webhook that
        # follows finds the state already written.
        applied = await apply_subscription_event(
            SubscriptionEvent(
                kind=SubscriptionEventKind.CANCELLED,
                occurred_at=datetime.now(UTC),
                data=DodoSubscriptionData.model_validate(
                    {**updated.model_dump(mode="json"), "cancel_at_next_billing_date": True}
                ),
            )
        )
        if applied.outcome is SubscriptionEventOutcome.NO_ROW:
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

        return await self.get_user_subscription_status(user_id)

    async def _reconcile_subscription_with_dodo(
        self, user_id: str, subscription_id: str
    ) -> SubscriptionDocument | None:
        """Recover a paid user whose ``subscription.active`` webhook never landed.

        ``subscription_id`` comes off the Dodo return URL, so it is a hint the
        client could forge: Dodo is asked what it actually is, and it is only
        acted on once it is both active and demonstrably this user's. Activation
        then runs through the same path the webhook uses, so the recovered state
        is indistinguishable from the delivered one.
        """
        try:
            remote = await asyncio.to_thread(self.client.subscriptions.retrieve, subscription_id)
        except NotFoundError:
            log.warning(
                f"{LogTag.PAYMENT} Dodo has no such subscription to reconcile",
                failure_reason="subscription_not_found",
                user_id=user_id,
            )
            return None

        return await self._activate_verified_subscription(user_id, remote)

    async def _activate_verified_subscription(
        self, user_id: str, remote: Subscription
    ) -> SubscriptionDocument | None:
        """Record a Dodo subscription for ``user_id`` through the shared write path.

        Both recovery routes end here, so neither can drift from the webhook:
        the subscription is acted on only once Dodo reports it active and it is
        demonstrably this user's, and the row is then written by the same
        reducer the webhook goes through — which is also what drops the cached
        plan tier and restores the workflows that lapsed.
        """
        sub_data = DodoSubscriptionData.model_validate(remote.model_dump(mode="json"))
        if sub_data.status != SubscriptionStatus.ACTIVE.value:
            log.warning(
                f"{LogTag.PAYMENT} Dodo subscription is not active; nothing to reconcile",
                failure_reason="subscription_not_active",
                subscription_status=sub_data.status,
                user_id=user_id,
            )
            return None

        owner_id = await resolve_subscription_owner(sub_data)
        if owner_id != user_id:
            log.audit(
                "payment verification refused",
                actor=user_id,
                provider="dodo",
                reason="subscription_owner_mismatch",
            )
            return None

        await apply_subscription_event(
            SubscriptionEvent(
                kind=SubscriptionEventKind.ACTIVATED,
                occurred_at=datetime.now(UTC),
                data=sub_data,
            )
        )
        return await subscription_repository.get_latest_active_for_user(user_id)

    async def _subscription_behind_checkout(
        self, checkout: CheckoutSessionDocument
    ) -> Subscription | None:
        """The Dodo subscription this checkout session was paid for, if it was.

        ``None`` is the ordinary answer for a session nobody paid, or for a
        settled one-off payment with no subscription behind it. A Dodo API
        failure propagates: the scan decides what one unanswerable session
        means for the rest.
        """
        checkout_status = await asyncio.to_thread(
            self.client.checkout_sessions.retrieve, checkout.session_id
        )
        payment_id = checkout_status.payment_id
        if not payment_id or checkout_status.payment_status != "succeeded":
            return None

        payment = await asyncio.to_thread(self.client.payments.retrieve, payment_id)
        subscription_id: str | None = getattr(payment, "subscription_id", None)
        if not subscription_id:
            # Payment settled but has no subscription behind it.
            return None

        return await asyncio.to_thread(self.client.subscriptions.retrieve, subscription_id)

    async def _materialize_subscription_from_dodo(
        self, user_id: str
    ) -> SubscriptionDocument | None:
        """Resolve this user's recent checkout sessions against Dodo and record
        the subscription behind whichever one was actually paid.

        Covers the webhook-vs-redirect race (and a genuinely lost webhook): the
        sessions recorded at checkout-creation time are the stable references
        Dodo can answer for before a subscription row exists.

        It scans, rather than trusting the newest session, because minting is
        not rare — every paywall block hands the user a fresh checkout link, so
        by the time they come back from paying, the session they paid is
        routinely no longer the latest one. Reading only the latest asked Dodo
        about a link nobody opened and told a paying user they had not paid,
        and each further block buried the real session deeper. One failed
        session does not end the scan for the same reason.

        A scan that found nothing paid is cached for the result page's retry
        window (``CHECKOUT_SCAN_MISS_TTL``): the web client verifies eight
        times over about fifty seconds, and each verify re-asked Dodo about
        every session. Only a conclusive miss is cached — a session Dodo could
        not answer for, or a paid one whose subscription is not active yet, is
        exactly what the next retry should ask about again.

        The sessions name the purchase; they do not authorise it. Ownership and
        the write itself are settled by ``_activate_verified_subscription``,
        the same way the ``subscription_id`` hint route settles them.
        """
        miss_key = f"{CHECKOUT_SCAN_MISS_CACHE_PREFIX}{user_id}"
        if await redis_cache.get(miss_key):
            log.set_ns("payment", checkout_scan=CheckoutScanOutcome.CACHED_MISS.value)
            return None

        sessions = await checkout_session_repository.list_recent_for_user(
            user_id, limit=CHECKOUT_SESSION_SCAN_LIMIT
        )
        found = await self._scan_checkout_sessions(user_id, sessions)
        if isinstance(found, SubscriptionDocument):
            return found
        log.set_ns("payment", checkout_scan=found.value)
        if found is CheckoutScanOutcome.MISS:
            await redis_cache.set(miss_key, True, ttl=CHECKOUT_SCAN_MISS_TTL)
        return None

    async def _scan_checkout_sessions(
        self, user_id: str, sessions: list[CheckoutSessionDocument]
    ) -> SubscriptionDocument | CheckoutScanOutcome:
        """The activated subscription behind the first paid session, or why not."""
        outcome = CheckoutScanOutcome.MISS
        for checkout in sessions:
            try:
                subscription = await self._subscription_behind_checkout(checkout)
            except Exception as e:
                log.warning(
                    f"{LogTag.PAYMENT} Failed to resolve checkout with Dodo during verify",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                    session_id=checkout.session_id,
                )
                outcome = CheckoutScanOutcome.INCONCLUSIVE
                continue
            if subscription is None:
                continue
            activated = await self._activate_verified_subscription(user_id, subscription)
            if activated:
                return activated
            outcome = CheckoutScanOutcome.INCONCLUSIVE
        return outcome

    async def verify_payment_completion(
        self, user_id: str, subscription_id: str | None = None
    ) -> PaymentVerificationResponse:
        """Whether this user's payment has landed, reconciling with Dodo if it hasn't.

        The webhook is the normal way a subscription becomes active. When it is
        dropped or rejected the local row never appears, so a caller that knows
        which subscription was just paid for can hand it over and have Dodo
        settle the question instead of stranding the user on the free tier.
        """
        subscription = await subscription_repository.get_latest_active_for_user(user_id)

        if not subscription and subscription_id:
            subscription = await self._reconcile_subscription_with_dodo(user_id, subscription_id)

        if not subscription:
            # The Dodo redirect can land the user on the result page before the
            # subscription.active webhook has been processed — ask Dodo directly
            # whether the checkout turned into an active subscription and record
            # it locally (idempotent with the webhook handler).
            subscription = await self._materialize_subscription_from_dodo(user_id)

        if not subscription:
            return PaymentVerificationResponse(
                payment_completed=False,
                message="No active subscription found",
            )

        # The row can exist while the gate still caches the pre-payment tier: a
        # request 402'd from the paywall page re-populates the key for five
        # minutes, and it can land after the activation dropped it. Telling the
        # browser the payment completed while that key stands is how a paid
        # user gets locked out of what they just bought.
        await invalidate_plan_cache(user_id)

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
                has_ever_subscribed=await subscription_repository.has_any_for_user(user_id),
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
            has_ever_subscribed=True,
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
        self,
        user_id: str,
        billing_cycle: PlanDuration = PlanDuration.MONTHLY,
        source: CheckoutSource | None = None,
    ) -> ProCheckout:
        """Mint a hosted checkout session that upgrades this user to Pro.

        Every call mints a fresh session. Dodo sessions are single-use: the
        moment a payment runs against one, declined or not, its page only says
        "link expired". A per-user cache of the last session handed exactly
        that page back after a failed card, so there is no cache.

        ``settings.PAYWALL_DISCOUNT_CODE`` is pre-applied here rather than passed
        in by callers: every caller (the 402 paywall body, the bot notice, the
        subscription tool) advertises that same code, so applying it at the one
        place the session is minted keeps the link and the pitch from drifting.
        """
        return_path = source.return_path if source else PAYMENT_RESULT_PATH
        plan = await self.get_pro_plan(billing_cycle)
        checkout = await self.create_subscription(
            user_id,
            plan.dodo_product_id,
            discount_code=settings.PAYWALL_DISCOUNT_CODE,
            return_path=return_path,
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
        """Plan tier, Redis-cached for hot paths; eventually consistent within the TTL.

        Both branches record the tier and where it came from. The gate's entire
        decision is this one value, and a stale cached FREE is indistinguishable
        downstream from a user who really is free — so without ``plan_source``
        the first question of every paywall incident has no answer.
        """
        cache_key = f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}"
        cached = await redis_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("plan_type"):
            cached_plan = PlanType(cached["plan_type"])
            log.set_ns("payment", plan_type=cached_plan.value, plan_source="cache")
            return cached_plan

        plan_raw = (await self.get_user_subscription_status(user_id)).plan_type or PlanType.FREE
        # Pydantic v2 coerces str, Enum fields to plain strings; normalize before calling .value
        plan = plan_raw if isinstance(plan_raw, PlanType) else PlanType(plan_raw)
        await redis_cache.set(cache_key, {"plan_type": plan.value}, ttl=SUBSCRIPTION_PLAN_CACHE_TTL)
        log.set_ns("payment", plan_type=plan.value, plan_source="subscription")
        return plan


payment_service = DodoPaymentService()
