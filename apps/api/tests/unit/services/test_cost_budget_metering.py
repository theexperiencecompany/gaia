"""The metering split: what charges the user's allowance and what only measures COGS.

Redis is real (fakeredis) so the budget windows and the request-token counter are
exercised through actual commands, not asserted against a mock's call list — a
pipeline that silently stopped issuing INCRBYFLOAT would pass the latter.

The invariant these tests exist to protect: work GAIA does on the user's behalf
(memory extraction, onboarding questions, workflow generation — every
``ainvoke_structured`` caller) must NEVER move the day/month cost windows the
budget wall reads. It is still priced and booked durably, under ``aux_cost``, so
per-user COGS stays measurable. See ``app.services.llm_metering``.
"""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.config.rate_limits import RateLimitPeriod
from app.db.redis import redis_cache
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.services import cost_budget
from app.services.cost_budget import (
    get_cost,
    get_request_tokens,
    record_model_call_usage,
)
from shared.py.wide_events import log

USER = "u-metering"
REQUEST = "root-req-1"


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture(autouse=True)
def rollup() -> Iterator[AsyncMock]:
    """The durable Mongo rollup, stubbed — its own writes are covered elsewhere;
    here we only care WHICH bucket a call is booked into."""
    with patch.object(cost_budget, "record_cost", AsyncMock()) as mock:
        yield mock


class TestChargedSpend:
    """The agent middleware's route: work the user actively asked for."""

    async def test_moves_both_budget_windows_and_the_request_counter(self) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=300, output_tokens=200),
            REQUEST,
            charge_to_budget=True,
        )

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.01)
        assert await get_cost(USER, RateLimitPeriod.MONTH) == pytest.approx(0.01)
        assert await get_request_tokens(REQUEST) == 500

    async def test_is_booked_as_charged_in_the_durable_rollup(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=300, output_tokens=200),
            REQUEST,
            charge_to_budget=True,
        )

        rollup.assert_awaited_once_with(
            USER, UsageDailyIncrement(cost=0.01, input_tokens=300, output_tokens=200), charged=True
        )

    async def test_accumulates_across_calls(self) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=60, output_tokens=40),
            REQUEST,
            charge_to_budget=True,
        )
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.02, input_tokens=120, output_tokens=80),
            REQUEST,
            charge_to_budget=True,
        )

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.03)
        assert await get_request_tokens(REQUEST) == 300


@pytest.mark.unit
class TestAuxiliarySpend:
    """``ainvoke_structured``'s route: background work, measured but never charged."""

    async def test_never_moves_the_budget_windows_the_wall_reads(self) -> None:
        # The real auxiliary shape: no root_request_id (this work outlives the
        # turn that spawned it), so the pipeline carries no commands at all.
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.02, input_tokens=400, output_tokens=300),
            None,
            charge_to_budget=False,
        )

        assert await get_cost(USER, RateLimitPeriod.DAY) == 0.0
        assert await get_cost(USER, RateLimitPeriod.MONTH) == 0.0

    async def test_cannot_erode_an_allowance_already_partly_spent(self) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=60, output_tokens=40),
            REQUEST,
            charge_to_budget=True,
        )

        # A whole memory-ingestion batch runs. The user's remaining allowance
        # must be exactly what it was before it ran.
        for _ in range(20):
            await record_model_call_usage(
                USER,
                UsageDailyIncrement(cost=0.004, input_tokens=200, output_tokens=100),
                None,
                charge_to_budget=False,
            )

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.01)
        assert await get_cost(USER, RateLimitPeriod.MONTH) == pytest.approx(0.01)

    async def test_is_booked_as_uncharged_so_cogs_stays_measurable(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.02, input_tokens=400, output_tokens=300),
            None,
            charge_to_budget=False,
        )

        rollup.assert_awaited_once_with(
            USER, UsageDailyIncrement(cost=0.02, input_tokens=400, output_tokens=300), charged=False
        )

    async def test_leaves_the_request_ceiling_alone_without_a_request_id(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.02, input_tokens=400, output_tokens=300),
            None,
            charge_to_budget=False,
        )

        assert await get_request_tokens(REQUEST) == 0
        # Not just unread under this request's id — nothing was written at all.
        # The counter key must never be minted for an unattributed call.
        assert await fake_redis.dbsize() == 0

    async def test_still_counts_tokens_when_a_request_id_is_present(self) -> None:
        # An auxiliary call made from inside a turn still bounds that turn's
        # tree against runaway loops — only the money is exempt.
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.02, input_tokens=400, output_tokens=300),
            REQUEST,
            charge_to_budget=False,
        )

        assert await get_request_tokens(REQUEST) == 700
        assert await get_cost(USER, RateLimitPeriod.DAY) == 0.0


@pytest.mark.unit
class TestRequestCounterBoundaries:
    """The ceiling counts every billable token, and ONLY billable tokens —
    pinned at the exact boundaries (1 token, 0 billable) where an off-by-one
    or a flipped comparison would otherwise be invisible."""

    async def test_a_single_billable_token_is_still_counted(self) -> None:
        await record_model_call_usage(
            None, UsageDailyIncrement(cost=0.0, input_tokens=1), REQUEST, charge_to_budget=False
        )

        assert await get_request_tokens(REQUEST) == 1

    async def test_zero_billable_tokens_writes_no_counter(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Fully cache-served with no output: the ceiling must not see the call,
        # not even as a zero — the key itself must not exist.
        await record_model_call_usage(
            None,
            UsageDailyIncrement(cost=0.0, input_tokens=1000, cached_tokens=1000),
            REQUEST,
            charge_to_budget=False,
        )

        assert await fake_redis.keys("req_tokens:*") == []


@pytest.mark.unit
class TestDegradation:
    async def test_a_call_with_nothing_to_record_is_a_no_op(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(
            None, UsageDailyIncrement(cost=0.0), None, charge_to_budget=True
        )

        rollup.assert_not_awaited()

    async def test_redis_being_down_does_not_fail_the_model_call(self, rollup: AsyncMock) -> None:
        with (
            patch.object(redis_cache, "redis", None),
            patch.object(cost_budget.log, "warning") as warned,
        ):
            await record_model_call_usage(
                USER,
                UsageDailyIncrement(cost=0.01, input_tokens=300, output_tokens=200),
                REQUEST,
                charge_to_budget=True,
            )

        # The durable rollup still ran — losing Redis must not also lose the
        # cost history the usage charts are plotted from.
        rollup.assert_awaited_once_with(
            USER, UsageDailyIncrement(cost=0.01, input_tokens=300, output_tokens=200), charged=True
        )
        # Degraded, not silent: the budget windows this call should have moved
        # are now short by it, and the wall enforces on them. A warning that
        # does not say what was lost is the same as no warning.
        assert "Redis unavailable" in warned.call_args.args[0]


@pytest.mark.unit
class TestTokenOnlyCalls:
    """A priced-at-zero call still burned real tokens.

    ``record_llm_call`` books ``cost_usd=0`` when the pricing lookup misses, so
    gating the durable rollup on spend alone would lose the token breakdown for
    exactly the calls that need re-pricing later. Each of the four counters has
    to be able to trigger the rollup on its own — the existing tests always send
    input and output together, so a single ``or`` flipped to ``and`` in that
    chain changes nothing they can see.
    """

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("input_tokens", 7),
            ("output_tokens", 7),
            ("cached_tokens", 7),
            ("reasoning_tokens", 7),
        ],
    )
    async def test_any_single_token_counter_books_the_rollup(
        self, rollup: AsyncMock, field: str, value: int
    ) -> None:
        await record_model_call_usage(
            USER, UsageDailyIncrement(**{field: value}), REQUEST, charge_to_budget=True
        )

        assert rollup.await_count == 1
        assert getattr(rollup.await_args.args[1], field) == value

    async def test_a_call_with_neither_spend_nor_tokens_books_nothing(
        self, rollup: AsyncMock
    ) -> None:
        await record_model_call_usage(
            USER, UsageDailyIncrement(cost=0.0), REQUEST, charge_to_budget=True
        )

        rollup.assert_not_awaited()

    async def test_unattributed_token_data_is_not_rolled_up(self, rollup: AsyncMock) -> None:
        """The rollup is per-user; with no user there is nothing to book it
        against, and writing it anyway would file another user's spend under a
        null key."""
        await record_model_call_usage(
            None,
            UsageDailyIncrement(cost=0.0, input_tokens=10, output_tokens=5),
            REQUEST,
            charge_to_budget=True,
        )

        rollup.assert_not_awaited()

    async def test_unattributed_tokens_still_count_against_the_request_ceiling(self) -> None:
        """Losing the rollup must not lose the runaway-loop guard with it. That
        ceiling is keyed on the request tree, not the user, so a call nobody can
        be billed for still has to move it — otherwise an unattributed loop runs
        forever."""
        await record_model_call_usage(
            None,
            UsageDailyIncrement(cost=0.0, input_tokens=10, output_tokens=5),
            REQUEST,
            charge_to_budget=True,
        )

        assert await get_request_tokens(REQUEST) == 15

    @pytest.mark.regression
    async def test_cached_input_does_not_count_against_the_request_ceiling(self) -> None:
        """The ceiling bounds runaway loops, not cache economics.

        A cached prompt prefix rides every model call in a turn nearly free —
        an ordinary retrieve→bind→act turn re-sends ~30k cached tokens per call
        and blew the 300k free ceiling (82% of it cache reads) before the agent
        could deliver its result. Only uncached input counts as work here.
        """
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=1000, output_tokens=100, cached_tokens=900),
            REQUEST,
            charge_to_budget=True,
        )
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(
                cost=0.01, input_tokens=1000, output_tokens=100, cached_tokens=1000
            ),
            REQUEST,  # fully cache-served call moves nothing
            charge_to_budget=True,
        )

        assert await get_request_tokens(REQUEST) == 300

    async def test_cached_tokens_exceeding_input_clamp_at_zero_uncached(self) -> None:
        """Malformed provider usage (cache_read > input) must not make the
        counter go backwards — output still counts, uncached floors at 0."""
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=100, output_tokens=50, cached_tokens=500),
            REQUEST,
            charge_to_budget=True,
        )

        assert await get_request_tokens(REQUEST) == 50

    async def test_a_fully_cache_served_call_with_no_output_moves_nothing(
        self, rollup: AsyncMock
    ) -> None:
        """Nothing fresh entered the tree, so the ceiling sees nothing — but the
        call was still real work and must keep its durable booking."""
        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.01, input_tokens=1000, cached_tokens=1000),
            REQUEST,
            charge_to_budget=True,
        )

        assert await get_request_tokens(REQUEST) == 0
        rollup.assert_awaited_once()
        assert rollup.await_args.args[1].cached_tokens == 1000

    async def test_an_ordinary_multi_call_turn_stays_well_under_the_ceiling(self) -> None:
        """The production shape that used to trip the wall: ~10 model calls per
        turn, each re-sending a ~30k prompt of which ~25k is cached prefix.
        Raw tokens cross 300k; the work is ~58k."""
        for _ in range(10):
            await record_model_call_usage(
                USER,
                UsageDailyIncrement(
                    cost=0.008, input_tokens=30_000, output_tokens=800, cached_tokens=25_000
                ),
                REQUEST,
                charge_to_budget=True,
            )

        # Raw would be 308_000; only the fresh 5_800/call counts here.
        assert await get_request_tokens(REQUEST) == 58_000

    async def test_a_failed_rollup_is_named_in_the_warning(self, rollup: AsyncMock) -> None:
        """Fail-open is only safe if the failure is findable: the operation label
        is what tells you the durable Mongo write dropped rather than the Redis
        pipeline."""
        log.reset()
        rollup.side_effect = RuntimeError("mongo down")

        await record_model_call_usage(
            USER,
            UsageDailyIncrement(cost=0.5, input_tokens=10, output_tokens=5),
            REQUEST,
            charge_to_budget=True,
        )

        failures = [w for w in log.get().get("warnings", []) if w.get("operation")]
        assert [w["operation"] for w in failures] == ["mongo_cost_rollup"]
        assert failures[0]["error_type"] == "RuntimeError"
