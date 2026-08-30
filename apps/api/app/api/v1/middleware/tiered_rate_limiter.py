"""
Tiered rate limiting engine.

Provides the ``TieredRateLimiter`` (Redis-backed per-user, per-feature daily and
monthly counters), the ``tiered_limiter`` singleton, and the 429 exception types.
The ``@tiered_rate_limit`` endpoint decorator that wraps this engine lives in
``app.decorators.rate_limiting`` (the canonical home for rate-limit decorators).
"""

import asyncio
from datetime import UTC, datetime
from typing import ParamSpec, TypeVar

from fastapi import HTTPException
import redis.asyncio as redis

from app.config.rate_limits import (
    FEATURE_LIMITS,
    RateLimitConfig,
    RateLimitPeriod,
    get_feature_info,
    get_feature_limits,
    get_limits_for_plan,
    get_reset_time,
    get_time_window_key,
)
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.models.usage_models import (
    FeatureUsage,
    UsageInfo,
    UsagePeriod,
    UserUsageSnapshot,
)
from app.services.limit_upsell import LimitHitOrigin, current_limit_origin, schedule_limit_upsell
from app.services.usage_activity import counts_as_activity, record_activity
from app.services.usage_service import UsageService
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log, spawn_logged_task

# UsageInfo is imported (not defined here) but re-exported for
# `app.api.v1.middleware.__init__` — explicit re-export required under
# no_implicit_reexport.
__all__ = ["UsageInfo"]

P = ParamSpec("P")
R = TypeVar("R")


class RateLimitExceededException(HTTPException):
    """429 carrying the feature, required plan (when gated), and reset time."""

    def __init__(
        self,
        feature: str,
        plan_required: str | None = None,
        reset_time: datetime | None = None,
        message: str | None = None,
        current_plan: str | None = None,
    ) -> None:
        detail = {
            "error": "rate_limit_exceeded",
            "feature": feature,
            "message": f"Rate limit exceeded for {feature}",
        }
        if plan_required:
            detail["plan_required"] = plan_required
            detail["message"] = (
                f"{feature} is not available in your current plan. Upgrade to {plan_required.capitalize()} to access this feature."
            )
        if reset_time:
            detail["reset_time"] = reset_time.isoformat()
        if message:
            detail["message"] = message
        # The user's actual plan travels with the 429 so every surface (chat
        # toast, workflow-pause notification, bot notice) can suppress the
        # upgrade pitch for a user who is already on the top tier.
        if current_plan:
            detail["current_plan"] = current_plan

        # Kept as attributes so consumers that rewrite ``detail`` (e.g. the
        # agent-facing exception conversion) can still read the gate and reset.
        self.plan_required = plan_required
        self.reset_time = reset_time

        super().__init__(status_code=429, detail=detail)


class CostBudgetExceededException(RateLimitExceededException):
    """429 raised when a rolling USD cost budget (not a count limit) binds.

    Same wire shape as the count-limit 429 — the frontend toast / upgrade
    modal path renders identically — but a distinct type so callers (e.g.
    the workflow worker) can branch their user-facing copy on the cause.
    """

    def __init__(
        self,
        feature: str,
        plan_required: str | None = None,
        reset_time: datetime | None = None,
        current_plan: str | None = None,
    ):
        budget_message = "You've used today's AI usage allowance."
        if plan_required:
            budget_message += f" Upgrade to {plan_required.capitalize()} for higher limits."
        super().__init__(
            feature, plan_required, reset_time, message=budget_message, current_plan=current_plan
        )


class TieredRateLimiter:
    """Redis-backed per-user, per-feature counters across daily/monthly windows."""

    def __init__(self) -> None:
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
        origin: LimitHitOrigin | None = None,
    ) -> dict[str, UsageInfo]:
        """Enforce all limits for a feature, then atomically count this use.

        Raises ``RateLimitExceededException`` when any window is exhausted or
        the user's plan has no access to the feature at all. Every exceed for
        a FREE user also fires the upsell side effects (analytics event +
        weekly-deduped email) — one seam covering all decorated endpoints and
        agent tools. ``origin`` selects the email: interactive surfaces get the
        upsell, background runs (worker-executed workflows) get the
        workflows-paused note.
        """
        origin = origin or current_limit_origin()
        # Checked here rather than inside `_check_and_increment` so the bypass
        # also skips the upsell side effects: a dev run must not fire analytics
        # or send a user an upgrade email.
        if settings.DEV_UNLIMITED_RATE_LIMITS:
            return {}
        try:
            return await self._check_and_increment(user_id, feature_key, user_plan)
        except RateLimitExceededException:
            schedule_limit_upsell(user_id, feature_key, user_plan, origin)
            raise

    @staticmethod
    def _plan_required(feature_key: str, user_plan: PlanType) -> str | None:
        """``"pro"`` when a FREE user needs the paid tier to reach this feature."""
        paid_limits = get_feature_limits(feature_key).pro
        paid_has_access = paid_limits.day > 0 or paid_limits.month > 0
        return "pro" if (user_plan == PlanType.FREE and paid_has_access) else None

    async def _snapshot_usage(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
        current_limits: RateLimitConfig,
    ) -> dict[str, UsageInfo]:
        """Read current counters; raise when any non-zero window is exhausted."""
        usage_info: dict[str, UsageInfo] = {}
        for period in [RateLimitPeriod.DAY, RateLimitPeriod.MONTH]:
            limit = getattr(current_limits, period.value)
            if limit <= 0:
                continue

            redis_key = self._get_redis_key(user_id, feature_key, period)
            current_usage = await self.redis.get(redis_key)
            used = int(current_usage) if current_usage else 0
            reset_time = get_reset_time(period)

            usage_info[period.value] = UsageInfo(used=used, limit=limit, reset_time=reset_time)

            if used >= limit:
                # No plan_required: an exhausted window is a spent budget, not a
                # paywall. Both are only reachable when the CALLER's own limit for
                # this period is non-zero, and a paywalled period is one whose
                # limit is zero — so the two can never coincide. The whole-feature
                # gate in _check_and_increment is where an upsell comes from.
                raise RateLimitExceededException(
                    feature_key, reset_time=reset_time, current_plan=user_plan.value
                )
        return usage_info

    async def _check_and_increment(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
    ) -> dict[str, UsageInfo]:
        current_limits = get_limits_for_plan(feature_key, user_plan)
        usage_info = {}

        # Plan gate: a plan with NO limits at all (day and month both 0) has no
        # access to the feature — the per-period loop in _snapshot_usage skips 0
        # limits, so without this check a fully-zeroed plan would be unlimited
        # instead of blocked. plan_required is set when a paid plan has access.
        if current_limits.day <= 0 and current_limits.month <= 0:
            raise RateLimitExceededException(
                feature_key,
                self._plan_required(feature_key, user_plan),
                current_plan=user_plan.value,
            )

        usage_info.update(
            await self._snapshot_usage(user_id, feature_key, user_plan, current_limits)
        )

        # Increment usage atomically. Unlimited periods (limit 0) are still
        # COUNTED — a plain INCR with no enforcement — so usage charts (e.g. a
        # pro user's day-by-day messages) have data even where no cap applies.
        for period in [RateLimitPeriod.DAY, RateLimitPeriod.MONTH]:
            limit = getattr(current_limits, period.value)

            redis_key = self._get_redis_key(user_id, feature_key, period)
            ttl = self._get_ttl(period)

            if not self.redis.redis:
                raise Exception("Redis connection not available")

            if limit <= 0:
                await self.redis.redis.incr(redis_key)
                await self.redis.redis.expire(redis_key, ttl)
                continue

            # Use Redis pipeline with WATCH for atomic check-and-increment
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
                            # No plan_required, for the same reason as in
                            # _snapshot_usage: this branch needs limit > 0.
                            raise RateLimitExceededException(
                                feature_key,
                                reset_time=get_reset_time(period),
                                current_plan=user_plan.value,
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
        spawn_logged_task(
            "usage_sync",
            self._sync_usage_real_time(
                user_id=user_id,
                feature_key=feature_key,
                user_plan=user_plan,
            ),
            user={"id": user_id},
            feature_key=feature_key,
        )

        # Durable daily rollup for the activity heatmap (meaningful actions only).
        if counts_as_activity(feature_key):
            spawn_background_task(record_activity(user_id))

        return usage_info

    async def _sync_usage_real_time(
        self,
        user_id: str,
        feature_key: str,
        user_plan: PlanType,
    ) -> None:
        """Snapshot every feature that has usage, for the usage-history charts.

        Runs as a background task so it never blocks the request.
        """
        try:
            all_feature_usage = await self._collect_feature_usage(user_id, user_plan)
            if all_feature_usage:
                snapshot = UserUsageSnapshot(
                    user_id=user_id,
                    plan_type=(user_plan.value if hasattr(user_plan, "value") else str(user_plan)),
                    features=all_feature_usage,
                )
                await UsageService.save_usage_snapshot(snapshot)

        except Exception as e:
            # Log error but don't raise - this shouldn't break the main request
            log.error(
                f"{LogTag.API} Real-time usage sync failed",
                user_id=user_id,
                feature_key=feature_key,
                error_type=type(e).__name__,
                error=str(e),
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
                # Unlimited periods (limit 0) are included too — their counters
                # are still incremented (see _check_and_increment) and feed the
                # usage charts; zero-usage rows are dropped below either way.
                limit = getattr(current_limits, period.value)

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
                        feature_title=feature_info.title,
                        period=UsagePeriod(period.value),
                        used=current_usage,
                        limit=limit,
                        reset_time=reset_time,
                    )
                    all_feature_usage.append(feature_usage)

        return all_feature_usage


# Global rate limiter instance
tiered_limiter = TieredRateLimiter()


# The `tiered_rate_limit` decorator lives in app/decorators/rate_limiting.py.
# A second copy used to live here and drifted: it resolved the caller by looking
# for a kwarg named `user`, so endpoints importing this copy silently skipped
# rate limiting. One canonical implementation, imported from `app.decorators`.
