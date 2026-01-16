"""
Tiered rate limiting middleware for API endpoints.

Enforces daily and monthly rate limits based on user subscription plans.
Automatically checks both time periods and rejects requests that exceed any limit.

Usage:
    @tiered_rate_limit("file_analysis", count_tokens=True)
    async def analyze_file(user: dict = Depends(get_current_user)):
        # Also validates token usage limits per request
        return await analyze()
"""

import asyncio
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Dict, List, Optional

import redis.asyncio as redis
from app.config.loggers import app_logger as logger
from app.config.rate_limits import (
    FEATURE_LIMITS,
    RateLimitPeriod,
    get_feature_info,
    get_limits_for_plan,
    get_reset_time,
    get_time_window_key,
)
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
from fastapi import HTTPException


class RateLimitExceededException(HTTPException):
    def __init__(
        self,
        feature: str,
        plan_required: Optional[str] = None,
        reset_time: Optional[datetime] = None,
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

    def _get_redis_key(
        self, user_id: str, feature: str, period: RateLimitPeriod
    ) -> str:
        time_window = get_time_window_key(period)
        return f"rate_limit:{user_id}:{feature}:{period}:{time_window}"

    def _get_ttl(self, period: RateLimitPeriod) -> int:
        reset_time = get_reset_time(period)
        return int((reset_time - datetime.now(timezone.utc)).total_seconds())

    async def check_and_increment(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
        credits_used: float = 0.0,
    ) -> Dict[str, UsageInfo]:
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
                plan_required = "pro" if user_plan == PlanType.FREE else None
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
                            plan_required = (
                                "pro" if user_plan == PlanType.FREE else None
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

    async def get_usage_info(
        self, user_id: str, feature_key: str, user_plan: PlanType
    ) -> Dict[str, UsageInfo]:
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

        return usage_info

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
                    plan_type=(
                        user_plan.value
                        if hasattr(user_plan, "value")
                        else str(user_plan)
                    ),
                    features=all_feature_usage,
                    credits=credit_usage_list,  # Add credits to snapshot
                )

                await UsageService.save_usage_snapshot(snapshot)

        except Exception as e:
            # Log error but don't raise - this shouldn't break the main request
            logger.error(
                f"Real-time usage sync failed for user {user_id}, feature {feature_key}: {str(e)}"
            )

    async def _collect_feature_usage(
        self, user_id: str, user_plan: PlanType
    ) -> List[FeatureUsage]:
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
        setattr(wrapper, "_rate_limit_metadata", {"feature_key": feature_key})

        return wrapper

    return decorator
