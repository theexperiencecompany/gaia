"""Behavior spec for app/api/v1/middleware/tiered_rate_limiter.py.

UNIT: RateLimitExceededException.__init__
EXPECTED: Build an HTTPException(429) whose detail carries error/feature/message,
          optionally plan_required (with an upgrade message naming PLAN.upper()),
          optionally reset_time as ISO-8601.
MECHANISM: detail = {"error": "rate_limit_exceeded", "feature": f, "message": "Rate limit exceeded for {f}"};
           if plan_required -> detail["plan_required"]=plan_required, detail["message"] mentions {f} and PLAN.upper();
           if reset_time -> detail["reset_time"]=reset_time.isoformat(); super().__init__(429, detail).
MUST-CATCH:
  - status_code is exactly 429
  - detail["error"] == "rate_limit_exceeded" and detail["feature"] is the passed feature
  - without plan_required/reset_time those keys are ABSENT (not None)
  - plan_required path: key present AND message switches to the upgrade wording with PLAN.upper()
  - reset_time path: key present and equals .isoformat()

UNIT: TieredRateLimiter._get_redis_key
EXPECTED: "rate_limit:{user_id}:{feature}:{period}:{time_window}" where period renders as the
          enum (RateLimitPeriod.DAY) and time_window comes from get_time_window_key(period).
MECHANISM: f-string with get_time_window_key(period) appended.
MUST-CATCH:
  - exact key shape & ordering of segments
  - time window comes from get_time_window_key called with the SAME period

UNIT: TieredRateLimiter._get_ttl
EXPECTED: integer seconds between get_reset_time(period) and now (positive for a future reset).
MECHANISM: int((get_reset_time(period) - now(UTC)).total_seconds()).
MUST-CATCH:
  - returns the real future delta (not a constant), int seconds

UNIT: TieredRateLimiter.check_and_increment
EXPECTED: For each of DAY/MONTH with limit>0, read usage; if at/over limit raise 429
          (plan_required="pro" only when FREE plan AND free limit for that period is 0);
          else atomically incr+expire via a WATCH pipeline, retrying on WatchError, and
          double-checking the limit inside the pipeline. Schedules a background sync and
          returns {period_value: UsageInfo} for every checked period.
MECHANISM: see module. asyncio.create_task(self._sync_usage_real_time(...)) fire-and-forget.
MUST-CATCH:
  - limit<=0 periods are skipped (not in result, no redis read/incr)
  - returned UsageInfo carries the real used/limit/reset_time
  - at-limit before increment raises RateLimitExceededException with reset_time
  - plan_required gating: FREE + free-limit-0 -> "pro"; otherwise None
  - missing redis connection raises "Redis connection not available"
  - WatchError retries the transaction (does not abort)
  - concurrent over-limit inside the pipeline unwatches and raises
  - under limit: pipe.incr + pipe.expire(ttl) + pipe.execute run, usage incremented
  - background sync task is scheduled with the same user/feature/plan/credits

UNIT: TieredRateLimiter._sync_usage_real_time
EXPECTED: Collect feature usage; if any feature usage OR credits_used>0, save a snapshot
          (with a CreditUsage only when credits>0). Never raise — log on failure.
MECHANISM: see module.
MUST-CATCH:
  - credits_used>0 -> snapshot saved with exactly one CreditUsage of that amount
  - credits_used==0 AND no feature usage -> NO save
  - feature usage present (no credits) -> snapshot saved, no credits
  - snapshot carries plan_type from PlanType.value and the collected features
  - collector raising is swallowed and logged, not re-raised

UNIT: TieredRateLimiter._collect_feature_usage
EXPECTED: For every feature/period with limit>0, fetch redis usage in parallel; build a
          FeatureUsage only when usage>0; skip exceptions and unparseable values.
MECHANISM: asyncio.gather; int(str(raw)); FeatureUsage(...).
MUST-CATCH:
  - usage>0 -> one FeatureUsage with correct feature_key/used/limit/title/period
  - limit<=0 period skipped entirely
  - redis exception for a key is skipped (no FeatureUsage)
  - usage==0 -> skipped
  - non-numeric redis value -> treated as 0 -> skipped

UNIT: tiered_rate_limit (decorator)
EXPECTED: Resolve the user from a dict arg containing "user_id" or kwargs["user"];
          with no user, skip limiting and just call the function; with a user but no
          user_id raise 401; otherwise fetch the subscription, default plan to FREE,
          enforce limits, then return the wrapped function's result. Exposes
          _rate_limit_metadata = {"feature_key": key}.
MECHANISM: see module.
MUST-CATCH:
  - user in kwargs -> limit checked with resolved plan, function result returned
  - user in positional args (dict with user_id) -> same
  - no user at all -> function called, NO subscription/limit lookups
  - user without user_id -> HTTPException 401
  - plan_type None -> defaults to PlanType.FREE passed to check_and_increment
  - feature_key forwarded to check_and_increment is the decorator argument
  - metadata stored under _rate_limit_metadata with the feature_key

EQUIVALENT MUTANTS (allowed survivors, justified):
  - Docstrings (str -> '') of tiered_rate_limit, _sync_usage_real_time, and
    _collect_feature_usage have no runtime behavior.
  - _collect_feature_usage L243 `raw_usage is not None and not isinstance(raw_usage,
    Exception)` (And -> Or): the upstream guard `if isinstance(raw_usage, Exception):
    continue` makes the right operand `not isinstance(raw_usage, Exception)` ALWAYS True
    by the time L243 runs, so `X and True` == `X or True` only differs when X is False
    (raw is None); both branches then yield current_usage 0 -> skipped. Behaviour-identical.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as aioredis

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
    tiered_rate_limit,
)
from app.config.rate_limits import RateLimitConfig, RateLimitPeriod
from app.models.payment_models import PlanType
from app.models.usage_models import FeatureUsage, UsagePeriod

RESET = datetime(2099, 4, 1, tzinfo=UTC)


def _capture_create_task(captured: list) -> object:
    """Replacement for asyncio.create_task that records the coroutine and closes it.

    Returns a side_effect callable so the fire-and-forget sync task never actually
    runs (it touches real services) but we can still assert it was scheduled.
    """

    def _side_effect(coro, **kwargs: object) -> MagicMock:
        captured.append(coro)
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    return _side_effect


def _make_pipe() -> MagicMock:
    """An async-context-manager Redis pipeline double with the WATCH/MULTI API."""
    pipe = MagicMock()
    pipe.watch = AsyncMock()
    pipe.unwatch = AsyncMock()
    pipe.multi = MagicMock()
    pipe.incr = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    return pipe


def _attach_pipe(limiter: TieredRateLimiter, pipe: MagicMock) -> None:
    redis_conn = MagicMock()
    redis_conn.pipeline = MagicMock(return_value=pipe)
    limiter.redis.redis = redis_conn


# ---------------------------------------------------------------------------
# RateLimitExceededException
# ---------------------------------------------------------------------------


class TestRateLimitExceededException:
    def test_basic_shape(self) -> None:
        exc = RateLimitExceededException("file_upload")
        assert exc.status_code == 429
        assert exc.detail == {
            "error": "rate_limit_exceeded",
            "feature": "file_upload",
            "message": "Rate limit exceeded for file_upload",
        }

    def test_plan_required_switches_message_and_uppercases_plan(self) -> None:
        exc = RateLimitExceededException("file_upload", plan_required="pro")
        assert exc.detail["plan_required"] == "pro"  # type: ignore[index]
        # The message is replaced by the upgrade wording naming the feature + PLAN.upper().
        assert exc.detail["message"] == (  # type: ignore[index]
            "file_upload is not available in your current plan. "
            "Upgrade to PRO to access this feature."
        )

    def test_reset_time_serialized_iso(self) -> None:
        exc = RateLimitExceededException("file_upload", reset_time=RESET)
        assert exc.detail["reset_time"] == RESET.isoformat()  # type: ignore[index]
        # Default (no plan) keeps the basic message and omits plan_required.
        assert "plan_required" not in exc.detail  # type: ignore[operator]
        assert exc.detail["message"] == "Rate limit exceeded for file_upload"  # type: ignore[index]


# ---------------------------------------------------------------------------
# TieredRateLimiter helpers
# ---------------------------------------------------------------------------


class TestRedisKeyAndTtl:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    def test_redis_key_exact_shape(self, mock_twk: MagicMock) -> None:
        key = self.limiter._get_redis_key("user1", "chat_messages", RateLimitPeriod.DAY)
        # period renders as the enum object, not its .value -> "RateLimitPeriod.DAY".
        assert key == "rate_limit:user1:chat_messages:RateLimitPeriod.DAY:20990401"
        mock_twk.assert_called_once_with(RateLimitPeriod.DAY)

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    def test_ttl_is_real_future_delta(self, mock_reset: MagicMock) -> None:
        mock_reset.return_value = datetime.now(UTC) + timedelta(seconds=3600)
        ttl = self.limiter._get_ttl(RateLimitPeriod.DAY)
        # ~1 hour ahead; allow scheduling jitter but pin it to the real delta.
        assert 3500 <= ttl <= 3600
        mock_reset.assert_called_once_with(RateLimitPeriod.DAY)


# ---------------------------------------------------------------------------
# check_and_increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckAndIncrement:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_under_limit_increments_and_returns_usage(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=1000)
        self.limiter.redis.get = AsyncMock(return_value="5")
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)
        captured: list = []

        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
            side_effect=_capture_create_task(captured),
        ):
            result = await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

        # Both periods checked -> both in result with the real read usage and limits.
        assert set(result) == {"day", "month"}
        assert result["day"].used == 5
        assert result["day"].limit == 100
        assert result["day"].reset_time == RESET
        assert result["month"].limit == 1000
        # Atomic increment happened for both periods (incr + expire + execute each).
        assert pipe.incr.await_count == 2
        assert pipe.expire.await_count == 2
        assert pipe.execute.await_count == 2
        # A background sync was scheduled exactly once.
        assert len(captured) == 1

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_zero_limit_period_is_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=0, month=0)
        self.limiter.redis.get = AsyncMock(return_value="999")
        captured: list = []

        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
            side_effect=_capture_create_task(captured),
        ):
            result = await self.limiter.check_and_increment("user1", "chat_messages", PlanType.FREE)

        assert result == {}
        # Skipped periods never touch redis.
        self.limiter.redis.get.assert_not_called()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_at_limit_raises_with_reset_time(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=10, month=100)
        self.limiter.redis.get = AsyncMock(return_value="10")

        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["reset_time"] == RESET.isoformat()  # type: ignore[index]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_limit_of_one_is_enforced_not_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # Boundary: a limit of exactly 1 must be ENFORCED (the skip is limit <= 0, not <= 1).
        # DAY limit 1, usage already 1 -> at limit -> raise.
        mock_limits.return_value = RateLimitConfig(day=1, month=0)
        self.limiter.redis.get = AsyncMock(return_value="1")

        with pytest.raises(RateLimitExceededException):
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_limit_of_one_under_usage_increments(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # Boundary on the increment loop: limit 1, no prior usage -> must still increment
        # (the increment-loop skip is also limit <= 0, not <= 1).
        mock_limits.return_value = RateLimitConfig(day=1, month=0)
        self.limiter.redis.get = AsyncMock(return_value=None)
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)
        captured: list = []

        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
            side_effect=_capture_create_task(captured),
        ):
            result = await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

        # Empty redis value -> usage parsed as 0 (not 1), and the DAY period increments.
        assert result["day"].used == 0
        assert pipe.incr.await_count == 1

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20990401",
    )
    async def test_plan_gated_free_user_gets_pro_upgrade(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # FREE caller. DAY: active limit 10 (reached at usage 10) but the FREE gate for
        # DAY is 0 -> plan-gated -> plan_required="pro". MONTH limit 0 -> skipped.
        # get_limits_for_plan is called in order: (1) current_limits for the loop,
        # (2) free_limits for the gate check.
        mock_limits.side_effect = [
            RateLimitConfig(day=10, month=0),  # current_limits: DAY checked
            RateLimitConfig(day=0, month=0),  # free_limits gate: DAY == 0 -> gated
        ]
        self.limiter.redis.get = AsyncMock(return_value="10")

        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.FREE)

        assert exc_info.value.detail["plan_required"] == "pro"  # type: ignore[index]
        assert "PRO" in exc_info.value.detail["message"]  # type: ignore[index]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_not_plan_gated_when_free_gate_nonzero(
        self, mock_twk: MagicMock, mock_reset: MagicMock
    ) -> None:
        # FREE caller at limit, but the FREE gate for the period is NON-zero ->
        # plan_required must stay None (no upgrade prompt).
        with patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan") as gp:
            gp.return_value = RateLimitConfig(day=10, month=0)
            self.limiter.redis.get = AsyncMock(return_value="10")
            with pytest.raises(RateLimitExceededException) as exc_info:
                await self.limiter.check_and_increment("user1", "chat_messages", PlanType.FREE)

        assert "plan_required" not in exc_info.value.detail  # type: ignore[operator]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_pro_user_not_plan_gated(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # PRO caller at limit -> never plan-gated regardless of FREE gate.
        mock_limits.return_value = RateLimitConfig(day=10, month=0)
        self.limiter.redis.get = AsyncMock(return_value="10")
        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)
        assert "plan_required" not in exc_info.value.detail  # type: ignore[operator]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_missing_redis_connection_raises(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="5")
        self.limiter.redis.redis = None

        with pytest.raises(Exception, match="Redis connection not available"):
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_watch_error_retries_transaction(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="5")
        pipe = _make_pipe()
        calls = {"n": 0}

        async def watch_side_effect(*_a: object, **_k: object) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise aioredis.WatchError()

        pipe.watch = AsyncMock(side_effect=watch_side_effect)
        _attach_pipe(self.limiter, pipe)
        captured: list = []

        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
            side_effect=_capture_create_task(captured),
        ):
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

        # First watch raised WatchError -> loop retried; second watch succeeded -> incr ran.
        assert calls["n"] == 2
        assert pipe.incr.await_count == 1

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_concurrent_over_limit_in_pipeline_unwatches_and_raises(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=10, month=0)
        # First (pre-pipeline) read is under limit (9); the in-pipeline re-read hits 10.
        self.limiter.redis.get = AsyncMock(side_effect=["9", "10"])
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)

        with pytest.raises(RateLimitExceededException):
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

        # It unwatched and never incremented when the concurrent limit was hit.
        pipe.unwatch.assert_awaited_once()
        pipe.incr.assert_not_called()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_concurrent_over_limit_in_pipeline_free_gated_returns_pro(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # The in-pipeline limit check has its OWN plan-gating branch. FREE caller whose
        # FREE gate for the period is 0 must get plan_required="pro" from that path too.
        # get_limits_for_plan order: (1) current_limits for the check loop,
        # (2) free_limits for the in-pipeline gate.
        mock_limits.side_effect = [
            RateLimitConfig(day=10, month=0),  # current_limits: DAY checked, usage 9 < 10
            RateLimitConfig(day=0, month=0),  # in-pipeline free_limits gate: 0 -> gated
        ]
        self.limiter.redis.get = AsyncMock(side_effect=["9", "10"])
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)

        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.FREE)

        assert exc_info.value.detail["plan_required"] == "pro"  # type: ignore[index]
        assert "PRO" in exc_info.value.detail["message"]  # type: ignore[index]
        pipe.incr.assert_not_called()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_concurrent_over_limit_in_pipeline_free_not_gated_no_pro(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # In-pipeline gate: FREE caller but FREE gate is non-zero -> NOT plan-gated.
        mock_limits.side_effect = [
            RateLimitConfig(day=10, month=0),  # current_limits
            RateLimitConfig(day=10, month=0),  # in-pipeline free_limits gate: 10 != 0
        ]
        self.limiter.redis.get = AsyncMock(side_effect=["9", "10"])
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)

        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.FREE)

        assert "plan_required" not in exc_info.value.detail  # type: ignore[operator]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_concurrent_over_limit_in_pipeline_pro_no_pro_flag(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        # In-pipeline gate: PRO caller is never plan-gated, even if FREE gate is 0.
        mock_limits.side_effect = [
            RateLimitConfig(day=10, month=0),  # current_limits
            RateLimitConfig(day=0, month=0),  # in-pipeline free_limits gate: 0 but caller PRO
        ]
        self.limiter.redis.get = AsyncMock(side_effect=["9", "10"])
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)

        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "chat_messages", PlanType.PRO)

        assert "plan_required" not in exc_info.value.detail  # type: ignore[operator]

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_background_sync_scheduled_with_call_args(
        self, mock_twk: MagicMock, mock_limits: MagicMock, mock_reset: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="5")
        pipe = _make_pipe()
        _attach_pipe(self.limiter, pipe)
        # Replace the coroutine factory so we can inspect the args without awaiting it.
        self.limiter._sync_usage_real_time = MagicMock(return_value=AsyncMock()())  # type: ignore[method-assign]
        captured: list = []

        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
            side_effect=_capture_create_task(captured),
        ):
            await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.PRO, credits_used=2.5
            )

        self.limiter._sync_usage_real_time.assert_called_once_with(  # type: ignore[attr-defined]
            user_id="user1",
            feature_key="chat_messages",
            user_plan=PlanType.PRO,
            credits_used=2.5,
        )


# ---------------------------------------------------------------------------
# _sync_usage_real_time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncUsageRealTime:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    async def test_credits_saved_as_single_credit_usage(
        self, mock_reset: MagicMock, mock_save: AsyncMock
    ) -> None:
        self.limiter._collect_feature_usage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # 0.5 is positive but <= 1 -> proves the threshold is `> 0`, not `> 1`.
        await self.limiter._sync_usage_real_time(
            "user1", "chat_messages", PlanType.PRO, credits_used=0.5
        )

        snapshot = mock_save.call_args[0][0]
        assert snapshot.user_id == "user1"
        assert snapshot.plan_type == "pro"  # PlanType.PRO.value
        assert len(snapshot.credits) == 1
        assert snapshot.credits[0].credits_used == pytest.approx(0.5)
        assert snapshot.credits[0].reset_time == RESET

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    async def test_feature_usage_saved_without_credits(
        self, mock_reset: MagicMock, mock_save: AsyncMock
    ) -> None:
        feature = FeatureUsage(
            feature_key="chat_messages",
            feature_title="Chat",
            period=UsagePeriod.DAY,
            used=3,
            limit=100,
            reset_time=RESET,
        )
        self.limiter._collect_feature_usage = AsyncMock(return_value=[feature])  # type: ignore[method-assign]

        await self.limiter._sync_usage_real_time(
            "user1", "chat_messages", PlanType.PRO, credits_used=0.0
        )

        snapshot = mock_save.call_args[0][0]
        assert snapshot.features == [feature]
        assert snapshot.credits == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    async def test_no_features_no_credits_does_not_save(self, mock_save: AsyncMock) -> None:
        self.limiter._collect_feature_usage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await self.limiter._sync_usage_real_time(
            "user1", "chat_messages", PlanType.PRO, credits_used=0.0
        )

        mock_save.assert_not_called()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.log")
    async def test_collector_error_is_swallowed_and_logged(
        self, mock_log: MagicMock, mock_save: AsyncMock
    ) -> None:
        self.limiter._collect_feature_usage = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )

        # Must not raise.
        await self.limiter._sync_usage_real_time("user1", "chat_messages", PlanType.PRO)

        mock_log.error.assert_called_once()
        # The diagnostic message names the user, the feature, and the underlying error.
        logged = mock_log.error.call_args[0][0]
        assert logged == ("Real-time usage sync failed for user user1, feature chat_messages: boom")
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# _collect_feature_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCollectFeatureUsage:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_feature_info",
        return_value={"title": "Chat"},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time", return_value=RESET)
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_active_usage_builds_feature_usage(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
        mock_info: MagicMock,
    ) -> None:
        # Only the DAY period has a positive limit. Boundary values (limit 1, usage 1)
        # prove the limit guard is `<= 0` (not `<= 1`) and the usage guard is `> 0`
        # (not `> 1`): both 1s must still produce a FeatureUsage.
        mock_limits.return_value = RateLimitConfig(day=1, month=0)
        self.limiter.redis.get = AsyncMock(return_value="1")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)

        assert len(result) == 1
        fu = result[0]
        assert fu.feature_key == "test_feat"
        assert fu.feature_title == "Chat"
        assert fu.used == 1
        assert fu.limit == 1
        assert fu.period == UsagePeriod.DAY
        assert fu.reset_time == RESET

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_redis_exception_for_key_is_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_zero_usage_is_skipped(self, mock_twk: MagicMock, mock_limits: MagicMock) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="0")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_missing_redis_value_is_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock
    ) -> None:
        # No stored usage (redis returns None) -> usage defaults to 0 -> no FeatureUsage.
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value=None)

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_empty_string_value_is_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock
    ) -> None:
        # Empty redis string is falsy -> parsed as 0 -> no FeatureUsage.
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_non_numeric_value_treated_as_zero_and_skipped(
        self, mock_twk: MagicMock, mock_limits: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="not_a_number")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_time_window_key", return_value="20990401")
    async def test_all_periods_zero_limit_yields_empty(
        self, mock_twk: MagicMock, mock_limits: MagicMock
    ) -> None:
        mock_limits.return_value = RateLimitConfig(day=0, month=0)
        self.limiter.redis.get = AsyncMock(return_value="50")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []
        # No redis read happens when every period is limit<=0.
        self.limiter.redis.get.assert_not_called()


# ---------------------------------------------------------------------------
# tiered_rate_limit decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTieredRateLimitDecorator:
    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_user_in_kwargs_enforces_limit_and_returns_result(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub = MagicMock()
        sub.plan_type = PlanType.PRO
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def endpoint(user: dict | None = None) -> str:
            return "ok"

        result = await endpoint(user={"user_id": "u1"})

        assert result == "ok"
        mock_limiter.check_and_increment.assert_awaited_once_with(
            user_id="u1", feature_key="file_upload", user_plan=PlanType.PRO
        )

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_user_in_positional_args(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub = MagicMock()
        sub.plan_type = PlanType.PRO
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def endpoint(user: dict) -> str:
            return "ok"

        result = await endpoint({"user_id": "u1"})

        assert result == "ok"
        mock_limiter.check_and_increment.assert_awaited_once_with(
            user_id="u1", feature_key="file_upload", user_plan=PlanType.PRO
        )

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_positional_dict_without_user_id_is_not_a_user(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        # A positional dict is only the user when it CONTAINS "user_id" (dict AND key).
        # A dict lacking the key must fall through to the public-endpoint path: no limit
        # check, no 401, just the function result.
        mock_pay.get_user_subscription_status = AsyncMock()
        mock_limiter.check_and_increment = AsyncMock()

        @tiered_rate_limit("file_upload")
        async def endpoint(payload: dict) -> str:
            return "ok"

        result = await endpoint({"not_a_user": True})

        assert result == "ok"
        mock_limiter.check_and_increment.assert_not_called()
        mock_pay.get_user_subscription_status.assert_not_called()

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_no_user_skips_limiting_entirely(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        mock_pay.get_user_subscription_status = AsyncMock()
        mock_limiter.check_and_increment = AsyncMock()

        @tiered_rate_limit("file_upload")
        async def endpoint() -> str:
            return "ok"

        result = await endpoint()

        assert result == "ok"
        # Public endpoint path: no subscription lookup and no limit check.
        mock_pay.get_user_subscription_status.assert_not_called()
        mock_limiter.check_and_increment.assert_not_called()

    async def test_user_without_user_id_raises_401(self) -> None:
        from fastapi import HTTPException

        @tiered_rate_limit("file_upload")
        async def endpoint(user: dict | None = None) -> str:
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(user={"email": "no_id"})
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User ID not found"

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_none_plan_defaults_to_free(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub = MagicMock()
        sub.plan_type = None
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def endpoint(user: dict | None = None) -> str:
            return "ok"

        await endpoint(user={"user_id": "u1"})

        assert mock_limiter.check_and_increment.call_args.kwargs["user_plan"] == PlanType.FREE

    async def test_stores_feature_key_metadata(self) -> None:
        @tiered_rate_limit("file_upload")
        async def endpoint() -> str:
            return "ok"

        assert endpoint._rate_limit_metadata == {"feature_key": "file_upload"}  # type: ignore[attr-defined]
