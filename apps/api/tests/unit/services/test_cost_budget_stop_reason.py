"""The budget wall's verdict: which stop text binds, and what spend it was read at.

``get_budget_stop_reason`` runs before EVERY model call, so it is both the wall
and the only cheap read of the user's daily spend. It returns a ``BudgetCheck``
triple — stop text, the spend actually read, and the resolved plan — precisely so
the middleware can decide on the softer wrap-up nudge without a second Redis
round trip. A ``None`` spend where a real read happened silently disables that
nudge; a stop text on the wrong plan shows a free-plan upsell to a paying user.

Redis is real (fakeredis) and the windows are seeded through the production
writer, so the numbers the wall compares are the numbers production would have
written. Only the plan lookup — an external payments boundary — is stubbed.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.config.rate_limits import get_daily_cost_budget_usd, get_per_request_token_ceiling
from app.constants.llm import BUDGET_WRAPUP_REMAINING_FRACTION
from app.db.redis import redis_cache
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.models.payment_models import PlanType
from app.services.cost_budget import (
    DAILY_BUDGET_STOP_FREE,
    DAILY_BUDGET_STOP_PRO,
    REQUEST_CEILING_STOP_FREE,
    REQUEST_CEILING_STOP_PRO,
    get_budget_stop_reason,
    is_budget_wrapup_threshold,
    is_daily_budget_exhausted,
    record_model_call_usage,
)
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
def no_rollup() -> AsyncIterator[None]:
    """Seeding spend goes through the real Redis writer; its Mongo sibling is
    covered in ``test_usage_activity_rollup.py`` and needs no database here."""
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


@pytest.mark.unit
class TestDailyWall:
    async def test_binds_once_spend_reaches_the_plan_budget(self) -> None:
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, REQUEST)

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE
        assert check.spent_usd == pytest.approx(get_daily_cost_budget_usd(PlanType.FREE))
        assert check.plan_type == PlanType.FREE

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

        assert check.stop_reason == REQUEST_CEILING_STOP_FREE

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

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE

    async def test_a_free_users_token_burn_does_not_bind_the_pro_ceiling(self) -> None:
        await _burn_tokens(get_per_request_token_ceiling(PlanType.FREE))

        assert (await get_budget_stop_reason(USER, PlanType.PRO, REQUEST)).stop_reason is None

    @pytest.mark.regression
    async def test_a_cache_heavy_turn_does_not_bind_the_ceiling_on_raw_tokens(self) -> None:
        """The production bug this pins: an ordinary retrieve→bind→act turn made
        ~10 model calls re-sending a ~30k prompt that is mostly cached prefix —
        316k RAW tokens, 259k of them cache reads, and the ceiling stopped the
        turn right after `create_upgrade_link` returned, so the minted checkout
        link never reached the user. The wall bounds fresh work, not cache
        economics: raw over 300k with billable well under must not bind."""
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

        assert check == (None, None, None)

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

        assert check == (None, None, None)

    async def test_a_plan_lookup_failure_names_the_user_it_stopped_enforcing_for(
        self,
    ) -> None:
        """Failing open means an over-budget user keeps spending. The warning is
        the only trace that happened, so it has to say who and why — a bare
        "budget check failed" cannot be turned into a refund or a bug report."""
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

    # NB: the zero-budget guard's own test lives in
    # tests/unit/middleware/test_accounting.py — that is the file the mutation
    # gate runs cost_budget.py against, so a test here would never see the
    # mutant. See the comment there.

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
    """``plan_type`` is returned so the caller can test the wrap-up threshold
    without a second lookup — and the caller reads it on exactly the runs that
    stopped. The daily-wall tests above assert it; the ceiling path and the
    no-root_request_id path return it too and nothing checked either, so the
    field could be dropped on a bound wall and only those two paths would lie.
    """

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
        """No ``root_request_id`` skips the token read entirely — a separate
        return statement from the both-reads path, with its own copy of the
        three fields."""
        await _spend(get_daily_cost_budget_usd(PlanType.FREE))

        check = await get_budget_stop_reason(USER, PlanType.FREE, None)

        assert check.stop_reason == DAILY_BUDGET_STOP_FREE
        assert check.plan_type == PlanType.FREE
