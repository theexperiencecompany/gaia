"""
Tiered rate limiting middleware for API endpoints.

Enforces daily and monthly rate limits based on user subscription plans.
Automatically checks both time periods and rejects requests that exceed any limit.

Usage:
    @tiered_rate_limit("generate_image")
    async def make_image(user: dict = Depends(get_current_user)):
        return await generate()
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps

from fastapi import HTTPException
import redis.asyncio as redis

from app.config.rate_limits import (
    FEATURE_LIMITS,
    RateLimitPeriod,
    get_feature_info,
    get_limits_for_plan,
    get_reset_time,
    get_time_window_key,
)
from app.constants.credits import CREDITS_FEATURE_KEY
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.models.usage_models import (
    CreditUsage,
    FeatureUsage,
    UsageInfo,
    UsagePeriod,
    UserUsageSnapshot,
)
from app.services.payments.payment_service import payment_service
from app.services.usage_service import UsageService
from shared.py.wide_events import log


class RateLimitExceededException(HTTPException):
    def __init__(
        self,
        feature: str,
        plan_required: str | None = None,
        reset_time: datetime | None = None,
    ):
        detail = {
            "error": "rate_limit_exceeded",
            "feature": feature,
            "message": f"Rate limit exceeded for {feature}",
        }
        if plan_required:
            detail["plan_required"] = plan_required
            detail["message"] = (
                f"{feature} is not available in your current plan. Upgrade to {plan_required.upper()} to access this feature."
            )
        if reset_time:
            detail["reset_time"] = reset_time.isoformat()

        super().__init__(status_code=429, detail=detail)


class TieredRateLimiter:
    def __init__(self):
        self.redis = redis_cache

    def _get_redis_key(self, user_id: str, feature: str, period: RateLimitPeriod) -> str:
        time_window = get_time_window_key(period)
        return f"rate_limit:{user_id}:{feature}:{period}:{time_window}"

    def _get_ttl(self, period: RateLimitPeriod) -> int:
        reset_time = get_reset_time(period)
        return int((reset_time - datetime.now(UTC)).total_seconds())

    async def check_and_increment(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
        credits_used: float = 0.0,
    ) -> dict[str, UsageInfo]:
        current_limits = get_limits_for_plan(feature_key, user_plan)
        usage_info = {}

        for period in [RateLimitPeriod.DAY, RateLimitPeriod.MONTH]:
            limit = getattr(current_limits, period.value)
            if limit <= 0:
                continue

            redis_key = self._get_redis_key(user_id, feature_key, period)
            current_usage = await self.redis.get(redis_key)
            current_usage = int(current_usage) if current_usage else 0
            reset_time = get_reset_time(period)

            usage_info[period.value] = UsageInfo(
                used=current_usage, limit=limit, reset_time=reset_time
            )

            if current_usage >= limit:
                free_limits = get_limits_for_plan(feature_key, PlanType.FREE)
                is_plan_gated = getattr(free_limits, period.value) == 0
                plan_required = "pro" if (user_plan == PlanType.FREE and is_plan_gated) else None
                raise RateLimitExceededException(feature_key, plan_required, reset_time)

        # Increment usage atomically
        for period in [RateLimitPeriod.DAY, RateLimitPeriod.MONTH]:
            limit = getattr(current_limits, period.value)
            if limit <= 0:
                continue

            redis_key = self._get_redis_key(user_id, feature_key, period)
            ttl = self._get_ttl(period)

            # Use Redis pipeline with WATCH for atomic check-and-increment
            if not self.redis.redis:
                raise Exception("Redis connection not available")
            async with self.redis.redis.pipeline() as pipe:
                while True:
                    try:
                        # Watch the key for changes
                        await pipe.watch(redis_key)

                        # Get current value
                        current_val = await self.redis.get(redis_key)
                        current_val = int(current_val) if current_val else 0

                        # Double-check limit hasn't been exceeded by concurrent requests
                        if current_val >= limit:
                            await pipe.unwatch()
                            free_limits = get_limits_for_plan(feature_key, PlanType.FREE)
                            is_plan_gated = getattr(free_limits, period.value) == 0
                            plan_required = (
                                "pro" if (user_plan == PlanType.FREE and is_plan_gated) else None
                            )
                            raise RateLimitExceededException(
                                feature_key, plan_required, get_reset_time(period)
                            )

                        # Execute atomic increment
                        pipe.multi()
                        await pipe.incr(redis_key)
                        await pipe.expire(redis_key, ttl)
                        await pipe.execute()
                        break  # Success, exit retry loop

                    except redis.WatchError:
                        # Key was modified, retry the transaction
                        continue

        # Real-time usage sync after rate limit usage
        asyncio.create_task(
            self._sync_usage_real_time(
                user_id=user_id,
                feature_key=feature_key,
                user_plan=user_plan,
                credits_used=credits_used,
            )
        )

        return usage_info

    async def get_pool1_remaining(self, user_id: str, user_plan: PlanType) -> int:
        """Remaining plan-allotment credits (the binding day/month limit)."""
        limits = get_limits_for_plan(CREDITS_FEATURE_KEY, user_plan)
        remaining: int | None = None
        for period in (RateLimitPeriod.DAY, RateLimitPeriod.MONTH):
            limit = getattr(limits, period.value)
            if limit <= 0:
                continue
            used = await self.redis.get(self._get_redis_key(user_id, CREDITS_FEATURE_KEY, period))
            rem = max(0, limit - (int(used) if used else 0))
            remaining = rem if remaining is None else min(remaining, rem)
        return remaining or 0

    async def add_credit_usage(self, user_id: str, user_plan: PlanType, amount: int) -> int:
        """Charge up to ``amount`` credits to the plan allotment.

        Applies ``min(amount, remaining)`` to both the day and month counters so
        neither exceeds its limit, and returns the amount actually applied. Any
        shortfall is the caller's to draw from the top-up wallet (Pool 2).
        """
        if amount <= 0 or not self.redis.redis:
            return 0
        applied = min(amount, await self.get_pool1_remaining(user_id, user_plan))
        if applied <= 0:
            return 0
        limits = get_limits_for_plan(CREDITS_FEATURE_KEY, user_plan)
        for period in (RateLimitPeriod.DAY, RateLimitPeriod.MONTH):
            if getattr(limits, period.value) <= 0:
                continue
            key = self._get_redis_key(user_id, CREDITS_FEATURE_KEY, period)
            await self.redis.redis.incrby(key, applied)
            await self.redis.redis.expire(key, self._get_ttl(period))
        asyncio.create_task(self._sync_usage_real_time(user_id, CREDITS_FEATURE_KEY, user_plan))
        return applied

    async def remove_credit_usage(self, user_id: str, user_plan: PlanType, amount: int) -> None:
        """Refund ``amount`` plan-allotment credits (reverse of add_credit_usage)."""
        if amount <= 0 or not self.redis.redis:
            return
        limits = get_limits_for_plan(CREDITS_FEATURE_KEY, user_plan)
        for period in (RateLimitPeriod.DAY, RateLimitPeriod.MONTH):
            if getattr(limits, period.value) <= 0:
                continue
            key = self._get_redis_key(user_id, CREDITS_FEATURE_KEY, period)
            new_value = await self.redis.redis.decrby(key, amount)
            if new_value < 0:
                await self.redis.redis.set(key, 0, keepttl=True)

    async def _sync_usage_real_time(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
        credits_used: float = 0.0,
    ) -> None:
        """
        Sync usage data to database in real-time after rate limit usage.
        Runs asynchronously to avoid blocking the main request.
        Creates comprehensive snapshot with ALL features that have usage data.
        Tracks credits used for billing purposes.
        """
        try:
            # Get feature usage
            all_feature_usage = await self._collect_feature_usage(user_id, user_plan)

            # Create credit usage object if credits were used
            credit_usage_list = []
            if credits_used > 0:
                credit_usage = CreditUsage(
                    credits_used=credits_used,
                    period=UsagePeriod.MONTH,
                    reset_time=get_reset_time(RateLimitPeriod.MONTH),
                )
                credit_usage_list.append(credit_usage)

            if all_feature_usage or credit_usage_list:
                # Create and save comprehensive usage snapshot

                snapshot = UserUsageSnapshot(
                    user_id=user_id,
                    plan_type=(user_plan.value if hasattr(user_plan, "value") else str(user_plan)),
                    features=all_feature_usage,
                    credits=credit_usage_list,  # Add credits to snapshot
                )

                await UsageService.save_usage_snapshot(snapshot)

        except Exception as e:
            # Log error but don't raise - this shouldn't break the main request
            log.error(
                f"Real-time usage sync failed for user {user_id}, feature {feature_key}: {e!s}"
            )

    async def _collect_feature_usage(self, user_id: str, user_plan: PlanType) -> list[FeatureUsage]:
        """Collect feature usage data in parallel."""
        all_feature_usage = []

        # Collect all Redis keys to fetch in parallel
        redis_tasks = []
        feature_configs = []

        for check_feature_key in FEATURE_LIMITS:
            current_limits = get_limits_for_plan(check_feature_key, user_plan)

            for period in [RateLimitPeriod.DAY, RateLimitPeriod.MONTH]:
                limit = getattr(current_limits, period.value)
                if limit <= 0:
                    continue

                redis_key = self._get_redis_key(user_id, check_feature_key, period)
                redis_tasks.append(self.redis.get(redis_key))
                feature_configs.append((check_feature_key, period, limit))

        # Fetch all Redis values in parallel
        if redis_tasks:
            usage_values = await asyncio.gather(*redis_tasks, return_exceptions=True)

            # Process results
            for i, (check_feature_key, period, limit) in enumerate(feature_configs):
                raw_usage = usage_values[i]
                if isinstance(raw_usage, Exception):
                    continue

                # Safe type conversion
                current_usage = 0
                if raw_usage is not None and not isinstance(raw_usage, Exception):
                    try:
                        current_usage = int(str(raw_usage)) if raw_usage else 0
                    except (ValueError, TypeError):
                        current_usage = 0

                if current_usage > 0:
                    reset_time = get_reset_time(period)
                    feature_info = get_feature_info(check_feature_key)
                    feature_usage = FeatureUsage(
                        feature_key=check_feature_key,
                        feature_title=feature_info["title"],
                        period=UsagePeriod(period.value),
                        used=current_usage,
                        limit=limit,
                        reset_time=reset_time,
                    )
                    all_feature_usage.append(feature_usage)

        return all_feature_usage


# Global rate limiter instance
tiered_limiter = TieredRateLimiter()


def tiered_rate_limit(feature_key: str):
    """Rate limiting decorator for API endpoints."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request and user from dependencies
            user = None

            for arg in args:
                if isinstance(arg, dict) and "user_id" in arg:
                    user = arg

            if not user:
                user = kwargs.get("user")
                if not user:
                    # If no user found, skip rate limiting (for public endpoints)
                    return await func(*args, **kwargs)

            user_id = user.get("user_id")
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")

            # Get user subscription
            subscription = await payment_service.get_user_subscription_status(user_id)
            user_plan = subscription.plan_type or PlanType.FREE

            # Check rate limits before executing function
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key=feature_key,
                user_plan=user_plan,
            )

            # Execute the original function
            result = await func(*args, **kwargs)
            return result

        # Store metadata for usage tracking
        wrapper._rate_limit_metadata = {"feature_key": feature_key}  # type: ignore[attr-defined]

        return wrapper

    return decorator
