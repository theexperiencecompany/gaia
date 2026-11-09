"""The budget wall's verdict: which stop text binds, and what spend it was read at.

get_budget_stop_reason runs before EVERY model call, so it is both the wall
and the only cheap read of the user's daily spend. It returns a BudgetCheck
triple — stop text, the spend actually read, and the resolved plan — precisely so
the middleware can decide on the softer wrap-up nudge without a second Redis
round trip. A None spend where a real read happened silently disables that
nudge; a stop text on the wrong plan shows a free-plan upsell to a paying user.

Redis is real (fakeredis) and the windows are seeded through the production
writer, so the numbers the wall compares are the numbers production would have
written. Only the plan lookup — an external payments boundary — is stubbed.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
import time_machine

from app.config.rate_limits import (
    RateLimitPeriod,
    get_daily_cost_budget_usd,
    get_per_request_token_ceiling,
    get_reset_time,
)
from app.config.settings import settings
from app.constants.llm import (
    BUDGET_WRAPUP_REMAINING_FRACTION,
    PRO_MONTHLY_BUDGET_HEADS_UP_FRACTION,
    PRO_MONTHLY_COST_BUDGET_USD,
)
from app.db.redis import redis_cache
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.models.payment_models import PlanType
from app.services import cost_budget
from app.services.cost_budget import (
    DAILY_BUDGET_STOP_FREE,
    DAILY_BUDGET_STOP_PRO,
    REQUEST_CEILING_STOP_FREE,
    REQUEST_CEILING_STOP_PRO,
    BudgetCheck,
    BudgetWall,
    get_budget_stop_reason,
    is_budget_wrapup_threshold,
    is_daily_budget_exhausted,
    is_monthly_heads_up_due,
    record_model_call_usage,
)
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

USER = "u-wall"
REQUEST = "root-req-wall"


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture(autouse=True)
def no_rollup() -> Iterator[None]:
    """Seeding spend uses the real Redis writer; the Mongo sibling is covered in test_usage_activity_rollup.py."""
    with patch("app.services.cost_budget.record_cost", AsyncMock()):
        yield


async def _spend(amount: float) -> None:
    await record_model_call_usage(
        USER, UsageDailyIncrement(cost=amount), None, charge_to_budget=True
    )


async def _burn_tokens(count: int) -> None:
    await record_model_call_usage(
        USER, UsageDailyIncrement(cost=0.0, input_tokens=count), REQUEST, charge_to_budget=True
    )


async def _spend_earlier_this_month(amount: float) -> None:
    """Spend booked on an earlier day: it sits in the month window, not today's."""
    assert redis_cache.redis is not None
    pipe = redis_cache.redis.pipeline(transaction=False)
    pipe.incrbyfloat(await cost_budget._budget_key(USER, RateLimitPeriod.MONTH), amount)
    await pipe.execute()


#: The user bills on the 15th, and today is mid-cycle, so the allowance resets on the next 15th.
BILLING_DAY = 15
TODAY = datetime(2099, 1, 20, 9, tzinfo=UTC)
MONTH_RESET = datetime(2099, 2, 15, tzinfo=UTC)
STOP_TEXT = (
    "You've used this month's AI usage allowance, so chat, workflows and tracked "
    "todos are paused until February 15, when it resets."
)


@pytest.fixture(autouse=True)
def billing_day() -> Iterator[None]:
    """Answer the billing-day lookup for USER only, so the month window is anchored on it."""

    async def _billing_day(user_id: str) -> int:
        return {USER: BILLING_DAY}[user_id]

    with patch.object(payment_service, "get_cached_billing_day", _billing_day):
        yield


@pytest.fixture
def month_reset() -> Iterator[None]:
    """Freeze the clock mid-cycle so the reset date in the copy is a fixed value."""
    with time_machine.travel(TODAY, tick=False):
        yield


@pytest.mark.unit
@pytest.mark.usefixtures("month_reset")
class TestMonthlyWall:
    async def test_binds_a_pro_run_once_the_month_reaches_the_allowance(self) -> None:
        await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD)

        check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check == BudgetCheck(
            BudgetWall.MONTHLY_USAGE, 0.0, PlanType.PRO, PRO_MONTHLY_COST_BUDGET_USD, MONTH_RESET
        )
        assert check.stop_reason == STOP_TEXT

    async def test_binds_without_a_request_id_too(self) -> None:
        await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD)

        check = await get_budget_stop_reason(USER, PlanType.PRO, None)

        assert check == BudgetCheck(
            BudgetWall.MONTHLY_USAGE, 0.0, PlanType.PRO, PRO_MONTHLY_COST_BUDGET_USD, MONTH_RESET
        )
        assert check.stop_reason == STOP_TEXT

    async def test_lets_a_pro_run_through_one_cent_short_and_reports_the_month(self) -> None:
        await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD - 0.01)

        check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check == BudgetCheck(None, 0.0, PlanType.PRO, PRO_MONTHLY_COST_BUDGET_USD - 0.01)

    async def test_reports_the_month_without_a_request_id_too(self) -> None:
        log.reset()
        await _spend_earlier_this_month(1.5)

        check = await get_budget_stop_reason(USER, PlanType.PRO, None)

        assert check == BudgetCheck(None, 0.0, PlanType.PRO, 1.5)
        assert [w["msg"] for w in log.get().get("warnings", [])] == [
            "[AGENT] Per-request ceiling skipped — missing root_request_id "
            "in configurable (threading gap?)."
        ]

    def test_the_monthly_stop_text_refuses_to_render_without_its_reset_day(self) -> None:
        with pytest.raises(
            ValueError, match="^The monthly wall's stop text needs the day it resets.$"
        ):
            BudgetWall.MONTHLY_USAGE.stop_text(PlanType.PRO, None)

    async def test_free_has_no_monthly_wall(self) -> None:
        await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD * 10)

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason is None


@pytest.mark.unit
class TestMonthlyHeadsUpBand:
    def test_opens_at_the_heads_up_line(self) -> None:
        line = PRO_MONTHLY_COST_BUDGET_USD * PRO_MONTHLY_BUDGET_HEADS_UP_FRACTION
        assert is_monthly_heads_up_due(line, PlanType.PRO) is True

    def test_closes_at_the_allowance_where_the_wall_takes_over(self) -> None:
        assert is_monthly_heads_up_due(PRO_MONTHLY_COST_BUDGET_USD, PlanType.PRO) is False

    def test_free_never_gets_it(self) -> None:
        assert is_monthly_heads_up_due(PRO_MONTHLY_COST_BUDGET_USD * 0.9, PlanType.FREE) is False


@pytest.mark.unit
class TestDailyWall:
    async def test_binds_once_spend_reaches_the_plan_budget(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.wall == BudgetWall.DAILY_USAGE
        assert check.stop_reason == DAILY_BUDGET_STOP_FREE
        assert check.spent_usd == pytest.approx(get_daily_cost_budget_usd(PlanType.FREE))
        assert check.plan_type == PlanType.FREE
        assert check.reset_at == get_reset_time(RateLimitPeriod.DAY)

    async def test_the_dev_unlimited_flag_lifts_a_bound_wall(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "DEV_UNLIMITED_RATE_LIMITS", True)
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check == BudgetCheck(None, None, None)

    async def test_lets_a_run_through_one_cent_short_of_the_budget(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE) - 0.01)

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason is None
        assert check.spent_usd == pytest.approx(get_daily_cost_budget_usd(PlanType.FREE) - 0.01)

    async def test_a_pro_user_gets_the_neutral_copy_not_the_upgrade_pitch(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.PRO))

        check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check.stop_reason == DAILY_BUDGET_STOP_PRO
        assert check.plan_type == PlanType.PRO

    async def test_a_free_users_spend_does_not_bind_a_pro_users_budget(self) -> None:
        # The same dollar figure is a wall on free and unremarkable on pro —
        # reading the budget off the wrong plan is how a paying user gets cut off.
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        assert (await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)).stop_reason is None

    async def test_zero_spend_reports_a_real_zero_not_an_absent_read(self) -> None:
        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason is None
        assert check.spent_usd == 0.0
        assert check.plan_type == PlanType.FREE


@pytest.mark.unit
class TestRequestCeiling:
    async def test_binds_once_the_request_tree_reaches_the_token_ceiling(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.wall == BudgetWall.TASK_SIZE
        assert check.stop_reason == REQUEST_CEILING_STOP_FREE
        assert check.reset_at is None

    async def test_still_reports_the_daily_spend_it_read(self) -> None:
        # The wrap-up nudge is decided from this number; a None here would mean
        # a run stopped on the ceiling silently loses the spend context.
        await _spend(0.01)
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason == REQUEST_CEILING_STOP_FREE
        assert check.spent_usd == pytest.approx(0.01)

    async def test_lets_a_run_through_one_token_short_of_the_ceiling(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE) - 1)

        assert (await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)).stop_reason is None

    async def test_a_pro_user_gets_the_neutral_copy(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.PRO))

        check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check.stop_reason == REQUEST_CEILING_STOP_PRO

    async def test_the_daily_wall_takes_priority_over_the_ceiling(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.wall == BudgetWall.DAILY_USAGE
        assert check.stop_reason == DAILY_BUDGET_STOP_FREE

    async def test_a_free_users_token_burn_does_not_bind_the_pro_ceiling(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        assert (await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)).stop_reason is None

    @pytest.mark.regression
    async def test_a_cache_heavy_turn_does_not_bind_the_ceiling_on_raw_tokens(self) -> None:
        """Regression: 316k raw/259k cached tokens must not bind the ceiling — it bounds fresh work, not cache-heavy raw totals."""
        for _ in range(10):
            await record_model_call_usage(
                USER,
                UsageDailyIncrement(
                    cost=0.003, input_tokens=32_000, output_tokens=800, cached_tokens=27_000
                ),
                REQUEST,
                charge_to_budget=True,
            )

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason is None


@pytest.mark.unit
class TestThreadingGaps:
    async def test_no_user_id_reports_nothing_read_at_all(self) -> None:
        check = await get_budget_stop_reason(None, PlanType.FREE, REQUEST)

        assert check == BudgetCheck(None, None, None)

    async def test_a_missing_plan_is_derived_and_reported_back(self) -> None:
        await _spend(0.01)

        with patch(
            "app.services.cost_budget.payment_service.get_cached_plan_type",
            AsyncMock(return_value=PlanType.PRO),
        ):
            check = await get_budget_stop_reason(USER, None, REQUEST)

        assert check.plan_type == PlanType.PRO
        assert check.spent_usd == pytest.approx(0.01)

    async def test_a_derived_plan_still_binds_the_wall(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        with patch(
            "app.services.cost_budget.payment_service.get_cached_plan_type",
            AsyncMock(return_value=PlanType.FREE),
        ):
            check = await get_budget_stop_reason(USER, None, REQUEST)

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE

    async def test_a_plan_lookup_failure_fails_open_with_nothing_read(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        with patch(
            "app.services.cost_budget.payment_service.get_cached_plan_type",
            AsyncMock(side_effect=RuntimeError("payments down")),
        ):
            check = await get_budget_stop_reason(USER, None, REQUEST)

        assert check == BudgetCheck(None, None, None)

    async def test_a_plan_lookup_failure_names_the_user_it_stopped_enforcing_for(
        self,
    ) -> None:
        """Fail-open must name the user in the warning — the only trace of who kept spending after the check failed."""
        log.reset()
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        with patch(
            "app.services.cost_budget.payment_service.get_cached_plan_type",
            AsyncMock(side_effect=RuntimeError("payments down")),
        ):
            await get_budget_stop_reason(USER, None, REQUEST)

        failed_open = [w for w in log.get().get("warnings", []) if "failing open" in w["msg"]]
        assert len(failed_open) == 1
        assert failed_open[0]["user"] == {"id": USER}
        assert failed_open[0]["error"] == "payments down"
        assert failed_open[0]["error_type"] == "RuntimeError"

    async def test_a_missing_request_id_still_enforces_the_daily_wall(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, None)

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE
        assert check.spent_usd == pytest.approx(get_daily_cost_budget_usd(PlanType.FREE))

    async def test_a_missing_request_id_still_reports_the_spend_when_nothing_binds(self) -> None:
        # Skipping the ceiling read must not also cost the wrap-up nudge its input.
        await _spend(0.01)

        check = await get_budget_stop_reason(USER, PlanType.FREE, None)

        assert check.stop_reason is None
        assert check.spent_usd == pytest.approx(0.01)
        assert check.plan_type == PlanType.FREE

    async def test_a_missing_request_id_cannot_bind_the_token_ceiling(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        assert (await get_budget_stop_reason(USER, PlanType.FREE, None)).stop_reason is None


@pytest.mark.unit
class TestWrapupThreshold:
    """The soft nudge fires strictly inside the headroom the hard wall leaves.

    The fraction itself is a tuning knob, so the threshold is derived from it;
    what these pin is the boundary behaviour around it (inclusive, and strictly
    before exhaustion), which no amount of tuning may change.
    """

    @staticmethod
    def _threshold(plan: PlanType) -> float:
        return get_daily_cost_budget_usd(plan) * (1 - BUDGET_WRAPUP_REMAINING_FRACTION)

    @pytest.mark.parametrize("plan", [PlanType.FREE, PlanType.PRO])
    def test_fires_exactly_at_the_threshold(self, plan: PlanType) -> None:
        spent = self._threshold(plan)

        assert is_budget_wrapup_threshold(spent, plan) is True
        assert is_daily_budget_exhausted(spent, plan) is False

    @pytest.mark.parametrize("plan", [PlanType.FREE, PlanType.PRO])
    def test_stays_quiet_just_below_the_threshold(self, plan: PlanType) -> None:
        spent = self._threshold(plan) - 0.0001

        assert is_budget_wrapup_threshold(spent, plan) is False

    @pytest.mark.parametrize("plan", [PlanType.FREE, PlanType.PRO])
    def test_stays_quiet_at_zero_spend(self, plan: PlanType) -> None:
        assert is_budget_wrapup_threshold(0.0, plan) is False

    # NB: the zero-budget guard's test lives in
    # tests/unit/middleware/test_accounting.py — the mutation gate runs
    # cost_budget.py against that file, not this one.

    @pytest.mark.parametrize("plan", [PlanType.FREE, PlanType.PRO])
    def test_is_still_true_once_the_hard_wall_binds(self, plan: PlanType) -> None:
        # The nudge is a subset of exhaustion, not an alternative to it — the
        # middleware relies on the stop text short-circuiting, not on this
        # going false.
        spent = get_daily_cost_budget_usd(plan)

        assert is_budget_wrapup_threshold(spent, plan) is True
        assert is_daily_budget_exhausted(spent, plan) is True


@pytest.mark.unit
class TestResolvedPlanSurvivesABoundWall:
    """plan_type lets the caller test the wrap-up threshold without a second lookup; the ceiling and no-request-id paths could silently drop it too."""

    async def test_the_ceiling_path_reports_the_plan_it_enforced(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason == REQUEST_CEILING_STOP_FREE
        assert check.plan_type == PlanType.FREE

    async def test_the_pro_ceiling_path_reports_the_plan_it_enforced(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.PRO))

        check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check.stop_reason == REQUEST_CEILING_STOP_PRO
        assert check.plan_type == PlanType.PRO

    async def test_a_daily_wall_bound_without_a_request_id_still_reports_the_plan(self) -> None:
        """A missing root_request_id skips token reads entirely, via a separate return path with its own copy of the three fields."""
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, None)

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE
        assert check.plan_type == PlanType.FREE


@pytest.mark.unit
class TestBillingAnchoredMonth:
    async def test_spend_before_the_billing_day_does_not_count_after_it(self) -> None:
        with time_machine.travel(datetime(2099, 1, 14, 23, tzinfo=UTC), tick=False):
            await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD)
        with time_machine.travel(datetime(2099, 1, 15, 1, tzinfo=UTC), tick=False):
            check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check == BudgetCheck(None, 0.0, PlanType.PRO, 0.0)

    async def test_spend_early_in_the_cycle_still_counts_across_the_calendar_month(self) -> None:
        with time_machine.travel(datetime(2099, 1, 20, tzinfo=UTC), tick=False):
            await _spend_earlier_this_month(PRO_MONTHLY_COST_BUDGET_USD)
        with time_machine.travel(datetime(2099, 2, 3, tzinfo=UTC), tick=False):
            check = await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)

        assert check.stop_reason is not None
        assert "February 15" in check.stop_reason
