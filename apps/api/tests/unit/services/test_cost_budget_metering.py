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
from app.services import cost_budget
from app.services.cost_budget import get_cost, get_request_tokens, record_model_call_usage

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


@pytest.mark.unit
class TestChargedSpend:
    """The agent middleware's route: work the user actively asked for."""

    async def test_moves_both_budget_windows_and_the_request_counter(self) -> None:
        await record_model_call_usage(USER, 0.01, REQUEST, 500, charge_to_budget=True)

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.01)
        assert await get_cost(USER, RateLimitPeriod.MONTH) == pytest.approx(0.01)
        assert await get_request_tokens(REQUEST) == 500

    async def test_is_booked_as_charged_in_the_durable_rollup(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(USER, 0.01, REQUEST, 500, charge_to_budget=True)

        rollup.assert_awaited_once_with(USER, 0.01, charged=True)

    async def test_accumulates_across_calls(self) -> None:
        await record_model_call_usage(USER, 0.01, REQUEST, 100, charge_to_budget=True)
        await record_model_call_usage(USER, 0.02, REQUEST, 200, charge_to_budget=True)

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.03)
        assert await get_request_tokens(REQUEST) == 300


@pytest.mark.unit
class TestAuxiliarySpend:
    """``ainvoke_structured``'s route: background work, measured but never charged."""

    async def test_never_moves_the_budget_windows_the_wall_reads(self) -> None:
        # The real auxiliary shape: no root_request_id (this work outlives the
        # turn that spawned it), so the pipeline carries no commands at all.
        await record_model_call_usage(USER, 0.02, None, 700, charge_to_budget=False)

        assert await get_cost(USER, RateLimitPeriod.DAY) == 0.0
        assert await get_cost(USER, RateLimitPeriod.MONTH) == 0.0

    async def test_cannot_erode_an_allowance_already_partly_spent(self) -> None:
        await record_model_call_usage(USER, 0.01, REQUEST, 100, charge_to_budget=True)

        # A whole memory-ingestion batch runs. The user's remaining allowance
        # must be exactly what it was before it ran.
        for _ in range(20):
            await record_model_call_usage(USER, 0.004, None, 300, charge_to_budget=False)

        assert await get_cost(USER, RateLimitPeriod.DAY) == pytest.approx(0.01)
        assert await get_cost(USER, RateLimitPeriod.MONTH) == pytest.approx(0.01)

    async def test_is_booked_as_uncharged_so_cogs_stays_measurable(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(USER, 0.02, None, 700, charge_to_budget=False)

        rollup.assert_awaited_once_with(USER, 0.02, charged=False)

    async def test_leaves_the_request_ceiling_alone_without_a_request_id(self) -> None:
        await record_model_call_usage(USER, 0.02, None, 700, charge_to_budget=False)

        assert await get_request_tokens(REQUEST) == 0

    async def test_still_counts_tokens_when_a_request_id_is_present(self) -> None:
        # An auxiliary call made from inside a turn still bounds that turn's
        # tree against runaway loops — only the money is exempt.
        await record_model_call_usage(USER, 0.02, REQUEST, 700, charge_to_budget=False)

        assert await get_request_tokens(REQUEST) == 700
        assert await get_cost(USER, RateLimitPeriod.DAY) == 0.0


@pytest.mark.unit
class TestDegradation:
    async def test_a_call_with_nothing_to_record_is_a_no_op(self, rollup: AsyncMock) -> None:
        await record_model_call_usage(None, 0.0, None, 0, charge_to_budget=True)

        rollup.assert_not_awaited()

    async def test_redis_being_down_does_not_fail_the_model_call(self, rollup: AsyncMock) -> None:
        with patch.object(redis_cache, "redis", None):
            await record_model_call_usage(USER, 0.01, REQUEST, 500, charge_to_budget=True)

        # The durable rollup still ran — losing Redis must not also lose the
        # cost history the usage charts are plotted from.
        rollup.assert_awaited_once_with(USER, 0.01, charged=True)
