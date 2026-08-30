"""The durable usage rollup: what ``record_cost`` books, and what ``get_activity`` shows.

Two invariants, both of them money:

1. Charged work and auxiliary background work must land in disjoint fields.
   ``cost``/``*_tokens`` are the exact durable mirror of the Redis windows the
   budget wall enforces; ``aux_*`` is COGS the user is never charged for. A
   crossed wire either eats a user's allowance for work they never asked for,
   or hides real spend from the wall.
2. Tokens must survive a pricing failure. ``record_llm_call`` books
   ``cost_usd=0`` when the pricing lookup misses, so gating the rollup on cost
   alone would silently drop the raw usage the call has to be re-priced from.

The repository is the seam (its own ``$inc`` semantics are proven against real
Mongo in ``tests/contracts/test_usage_daily_repository.py``); everything inside
``usage_activity`` runs for real.
"""

from collections.abc import Iterator
import os
import time
from unittest.mock import AsyncMock, patch

from pymongo.errors import PyMongoError
import pytest
import time_machine

from app.db.redis import redis_cache
from app.db.repositories.usage_daily import (
    UsageDailyDocument,
    UsageDailyIncrement,
    usage_daily_repository,
)
from app.services import usage_activity
from app.services.usage_activity import get_activity, record_cost

USER = "user-activity-1"
TODAY = "2026-03-04"
FROZEN = "2026-03-04T09:30:00+00:00"


def _row(date: str, **fields: object) -> UsageDailyDocument:
    return UsageDailyDocument(user_id=USER, date=date, **fields)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    """Both functions read ``datetime.now(UTC)`` to decide which day a write or
    a window belongs to, so the day boundary has to be pinned."""
    with time_machine.travel(FROZEN, tick=False):
        yield


@pytest.fixture
def a_box_a_day_ahead_of_utc() -> Iterator[None]:
    """A worker whose LOCAL calendar day runs ahead of the UTC one."""
    original = os.environ.get("TZ")
    os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


def _spend(
    cost: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> UsageDailyIncrement:
    return UsageDailyIncrement(
        cost=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


@pytest.fixture
def increment() -> Iterator[AsyncMock]:
    with patch.object(usage_daily_repository, "increment", AsyncMock()) as mock:
        yield mock


@pytest.mark.unit
class TestRecordCost:
    async def test_charged_spend_books_cost_and_tokens_under_the_charged_fields(
        self, increment: AsyncMock
    ) -> None:
        await record_cost(USER, _spend(0.02, 300, 120, 50, 40), charged=True)

        increment.assert_awaited_once_with(
            USER,
            TODAY,
            UsageDailyIncrement(
                cost=0.02,
                input_tokens=300,
                output_tokens=120,
                cached_tokens=50,
                reasoning_tokens=40,
            ),
            charged=True,
        )

    async def test_auxiliary_spend_books_everything_under_the_aux_mirrors(
        self, increment: AsyncMock
    ) -> None:
        await record_cost(USER, _spend(0.02, 300, 120, 50, 40), charged=False)

        increment.assert_awaited_once_with(
            USER,
            TODAY,
            UsageDailyIncrement(
                cost=0.02,
                input_tokens=300,
                output_tokens=120,
                cached_tokens=50,
                reasoning_tokens=40,
            ),
            charged=False,
        )

    async def test_tokens_still_land_when_pricing_failed_and_the_cost_is_zero(
        self, increment: AsyncMock
    ) -> None:
        # The real shape of a pricing-table miss: real usage, no dollar figure.
        # Dropping this write would make the call unrepriceable forever.
        await record_cost(USER, _spend(0.0, 300, 120), charged=True)

        increment.assert_awaited_once_with(
            USER,
            TODAY,
            UsageDailyIncrement(cost=0.0, input_tokens=300, output_tokens=120),
            charged=True,
        )

    @pytest.mark.parametrize(
        "token_field", ["input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]
    )
    async def test_any_single_token_field_alone_is_enough_to_write(
        self, increment: AsyncMock, token_field: str
    ) -> None:
        await record_cost(USER, UsageDailyIncrement(**{token_field: 7}), charged=True)

        increment.assert_awaited_once()
        assert getattr(increment.await_args.args[2], token_field) == 7

    async def test_priced_spend_lands_even_when_the_token_counts_are_missing(
        self, increment: AsyncMock
    ) -> None:
        # The mirror image of the pricing miss: a provider that priced the call
        # but returned no usage metadata. Spend without tokens is still spend,
        # and dropping it would under-bill the day's rollup against Redis.
        await record_cost(USER, _spend(0.02), charged=True)

        increment.assert_awaited_once_with(
            USER, TODAY, UsageDailyIncrement(cost=0.02), charged=True
        )

    async def test_spend_is_charged_unless_the_caller_says_otherwise(
        self, increment: AsyncMock
    ) -> None:
        # Defaulting to the aux bucket would quietly stop the durable rollup
        # mirroring the Redis windows the wall enforces.
        await record_cost(USER, _spend(0.02, 300))

        assert increment.await_args.kwargs["charged"] is True

    async def test_a_call_with_no_spend_and_no_tokens_writes_nothing(
        self, increment: AsyncMock
    ) -> None:
        await record_cost(USER, _spend(0.0), charged=True)

        increment.assert_not_awaited()

    async def test_a_call_without_a_user_writes_nothing(self, increment: AsyncMock) -> None:
        await record_cost("", _spend(0.02, 300), charged=True)

        increment.assert_not_awaited()

    async def test_the_rollup_day_is_the_utc_one_not_the_boxs_local_one(
        self, increment: AsyncMock, a_box_a_day_ahead_of_utc: None
    ) -> None:
        """The row key is a UTC day and every reader joins on that — the
        heatmap, the percentile window, and the true-cost backfill, which reads
        the day straight off the ``llm_call`` event's UTC timestamp. A worker
        reading its own local clock files the same call under a different day,
        so the durable history and the logs stop lining up for anyone outside
        UTC. CI runs in UTC, which is exactly why this needs saying out loud."""
        with time_machine.travel("2026-03-04T23:30:00+00:00", tick=False):
            await record_cost(USER, _spend(0.02), charged=True)

        assert increment.await_args.args[1] == "2026-03-04"  # not the local 03-05

    async def test_a_mongo_failure_never_reaches_the_caller(self, increment: AsyncMock) -> None:
        # record_cost runs after a model call has already completed and been
        # billed by the provider; raising here would fail a request the user
        # has already paid for.
        increment.side_effect = PyMongoError("rollup write failed")

        with patch.object(usage_activity.log, "warning") as warned:
            await record_cost(USER, _spend(0.02, 300), charged=True)

        increment.assert_awaited_once()
        # Swallowed, but never silent: the dropped rollup is the only per-day
        # cost history there is, so the warning has to name whose spend went
        # missing and what actually failed — otherwise the loss is invisible.
        assert warned.call_args.kwargs["user"] == {"id": USER}
        assert warned.call_args.kwargs["error"] == "rollup write failed"
        assert warned.call_args.kwargs["error_type"] == "PyMongoError"


@pytest.fixture
def rollups() -> Iterator[AsyncMock]:
    """The activity read seam: the window's rollup rows and the percentile inputs."""
    with (
        patch.object(usage_daily_repository, "rollups_since", AsyncMock(return_value=[])) as mock,
        patch.object(usage_daily_repository, "counts_since", AsyncMock(return_value={})),
        patch.object(usage_daily_repository, "rank_thresholds", AsyncMock(return_value={})),
        patch.object(redis_cache, "redis", None),
    ):
        yield mock


@pytest.mark.unit
class TestGetActivity:
    async def test_reports_one_entry_per_day_ending_today(self, rollups: AsyncMock) -> None:
        result = await get_activity(USER, 3)

        assert [day.date for day in result.days] == ["2026-03-02", "2026-03-03", "2026-03-04"]

    async def test_a_days_tokens_are_input_plus_output_only(self, rollups: AsyncMock) -> None:
        # Cached and reasoning tokens are reported so the input number is
        # explicable, but they are NOT added in — `tokens` matches how the
        # per-request ceiling counts them (input + output).
        rollups.return_value = [
            _row(
                TODAY,
                count=2,
                input_tokens=300,
                output_tokens=120,
                cached_tokens=50,
                reasoning_tokens=40,
            )
        ]

        today = (await get_activity(USER, 2)).days[-1]

        assert today.tokens == 420
        assert today.input_tokens == 300
        assert today.output_tokens == 120
        assert today.cached_tokens == 50
        assert today.reasoning_tokens == 40

    async def test_a_day_with_no_rollup_row_reports_zeros_rather_than_a_gap(
        self, rollups: AsyncMock
    ) -> None:
        rollups.return_value = [_row(TODAY, count=2, input_tokens=300, output_tokens=120)]

        quiet = (await get_activity(USER, 2)).days[0]

        assert quiet.date == "2026-03-03"
        assert (quiet.count, quiet.tokens, quiet.input_tokens, quiet.output_tokens) == (0, 0, 0, 0)
        assert (quiet.cached_tokens, quiet.reasoning_tokens) == (0, 0)

    async def test_totals_sum_the_whole_window(self, rollups: AsyncMock) -> None:
        rollups.return_value = [
            _row("2026-03-03", count=2, input_tokens=300, output_tokens=120),
            _row(TODAY, count=5, input_tokens=200, output_tokens=80),
        ]

        result = await get_activity(USER, 3)

        assert result.total == 7
        assert result.total_tokens == 700

    async def test_auxiliary_tokens_are_never_reported_as_the_users_own_usage(
        self, rollups: AsyncMock
    ) -> None:
        # Background work (memory extraction, onboarding) is COGS we absorb. If
        # it surfaced here the user would see token usage for work they never
        # did — and it would not match the budget percentage beside it.
        rollups.return_value = [
            _row(
                TODAY,
                count=0,
                aux_input_tokens=900,
                aux_output_tokens=400,
                aux_cached_tokens=100,
                aux_reasoning_tokens=50,
            )
        ]

        result = await get_activity(USER, 2)

        assert result.total_tokens == 0
        assert result.days[-1].tokens == 0
        assert result.days[-1].input_tokens == 0
        assert result.days[-1].cached_tokens == 0
        assert result.days[-1].reasoning_tokens == 0

    async def test_the_window_is_read_for_this_user_from_the_first_day_shown(
        self, rollups: AsyncMock
    ) -> None:
        # Both arguments are load-bearing: the wrong user_id serves someone
        # else's activity, and the wrong start day silently truncates or
        # over-reads the grid the percentile is then computed from.
        await get_activity(USER, 2)

        rollups.assert_awaited_once_with(USER, "2026-03-03")

    async def test_an_earned_tier_and_its_percentile_reach_the_response(
        self, rollups: AsyncMock
    ) -> None:
        # The badge is the whole point of the percentile pass — dropping it on
        # the way out leaves a user who earned gold seeing no badge at all.
        rollups.return_value = [_row(TODAY, count=100)]
        thresholds = {"p999": 1000.0, "p99": 90.0, "p90": 50.0, "p75": 10.0}

        with patch.object(
            usage_daily_repository, "rank_thresholds", AsyncMock(return_value=thresholds)
        ):
            result = await get_activity(USER, 365)

        assert result.tier == "gold"
        assert result.percentile == 99.0

    async def test_a_row_predating_the_token_fields_contributes_its_count_and_zero_tokens(
        self, rollups: AsyncMock
    ) -> None:
        rollups.return_value = [_row(TODAY, count=4)]

        result = await get_activity(USER, 2)

        assert result.total == 4
        assert result.total_tokens == 0

    async def test_a_streak_runs_back_from_today_over_active_days_only(
        self, rollups: AsyncMock
    ) -> None:
        rollups.return_value = [
            _row("2026-03-01", count=1),
            _row("2026-03-03", count=1),
            _row(TODAY, count=1),
        ]

        assert (await get_activity(USER, 5)).streak == 2

    async def test_an_empty_window_is_a_zero_filled_grid(self, rollups: AsyncMock) -> None:
        result = await get_activity(USER, 4)

        assert len(result.days) == 4
        assert all(day.count == 0 and day.tokens == 0 for day in result.days)
        assert (result.total, result.total_tokens, result.streak) == (0, 0, 0)
        assert result.percentile is None and result.tier is None
